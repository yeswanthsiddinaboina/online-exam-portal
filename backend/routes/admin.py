from flask import Blueprint, request, jsonify, send_file
import io
import re
from backend.models import db, User, Exam, ExamAttempt, ViolationLog, AuditLog, Result, EvidenceRecord
from backend.utils.security import token_required, role_required
from backend.utils.logger import get_logger
from backend.config import Config
from pathlib import Path

logger = get_logger()
admin_bp = Blueprint("admin", __name__)

@admin_bp.route("/dashboard", methods=["GET"])
@token_required
@role_required(["admin"])
def get_dashboard_metrics():
    try:
        total_exams = Exam.query.filter_by(is_deleted=False).count()
        active_exams = Exam.query.filter_by(is_active=True, is_deleted=False).count()
        
        # Candidate counts
        total_candidates = User.query.filter_by(role="student").count()
        
        # Exam attempts counts
        completed_attempts = ExamAttempt.query.filter(
            ExamAttempt.status.in_(["SUBMITTED", "AUTO_SUBMITTED", "EXPIRED"])
        ).count()
        
        malpractice_cases = db.session.query(ExamAttempt.student_id).join(ViolationLog).distinct().count()
        
        # Active sessions
        active_sessions = ExamAttempt.query.filter_by(status="IN_PROGRESS").count()

        # Average Score
        avg_score_query = db.session.query(db.func.avg(Result.percentage)).scalar()
        average_score = round(float(avg_score_query), 2) if avg_score_query else 0.0

        # Recent violations aggregated uniquely per student attempt
        recent_violation_records = ViolationLog.query.order_by(
            ViolationLog.timestamp.desc()
        ).all()

        violations_by_attempt = {}
        ordered_attempt_ids = []

        for v in recent_violation_records:
            attempt = v.attempt
            if not attempt or not attempt.student or not attempt.exam:
                continue

            att_id = attempt.id
            if att_id not in violations_by_attempt:
                ordered_attempt_ids.append(att_id)
                student = attempt.student
                user_id_val = student.last_name if (student.last_name and student.last_name.strip()) else f"STU{student.id}"
                
                # Fetch/evaluate candidate score if attempt is completed or terminated
                res = Result.query.filter_by(attempt_id=att_id).first()
                if not res and attempt.status in ["SUBMITTED", "AUTO_SUBMITTED", "MALPRACTICE_CANCELLED", "EXPIRED"]:
                    try:
                        from backend.services.evaluation import EvaluationService
                        res = EvaluationService.evaluate_attempt(att_id)
                    except Exception:
                        pass

                total_marks_val = sum(float(q.marks or 1.0) for q in attempt.exam.questions) if attempt.exam else 0.0

                violations_by_attempt[att_id] = {
                    "id": v.id,
                    "attempt_id": att_id,
                    "student_id": student.id,
                    "student_name": student.first_name if student.first_name else "Candidate",
                    "student_userid": user_id_val,
                    "student_email": student.email if student.email else "",
                    "exam_id": attempt.exam.id,
                    "exam_title": attempt.exam.title,
                    "status": attempt.status,
                    "total_violations": 0,
                    "score_obtained": res.total_score if res else 0.0,
                    "percentage": res.percentage if res else 0.0,
                    "total_marks": total_marks_val,
                    "passed": res.passed if res else False,
                    "latest_event_type": v.event_type,
                    "event_type": v.event_type,
                    "latest_confidence": v.confidence,
                    "confidence": v.confidence,
                    "latest_timestamp": (v.timestamp.isoformat() + "Z") if v.timestamp else None,
                    "timestamp": (v.timestamp.isoformat() + "Z") if v.timestamp else None,
                    "action_taken": "TERMINATE" if attempt.status == "MALPRACTICE_CANCELLED" else v.action_taken,
                    "violations": []
                }

            group = violations_by_attempt[att_id]
            group["total_violations"] += 1
            if v.action_taken == "TERMINATE" or attempt.status == "MALPRACTICE_CANCELLED":
                group["action_taken"] = "TERMINATE"

            evidence_url = f"/api/admin/evidence/{v.evidence.id}" if (v.evidence and v.evidence.file_path) else None
            group["violations"].append({
                "id": v.id,
                "event_type": v.event_type,
                "confidence": v.confidence,
                "timestamp": (v.timestamp.isoformat() + "Z") if v.timestamp else None,
                "action_taken": v.action_taken,
                "evidence_path": evidence_url
            })

        recent_violations = [violations_by_attempt[aid] for aid in ordered_attempt_ids[:20]]

        return jsonify({
            "success": True,
            "metrics": {
                "total_exams": total_exams,
                "active_exams": active_exams,
                "total_candidates": total_candidates,
                "completed_exams": completed_attempts,
                "malpractice_cases": malpractice_cases,
                "active_sessions": active_sessions,
                "average_score": average_score
            },
            "recent_violations": recent_violations
        }), 200

    except Exception as e:
        logger.error(f"Error compiling dashboard metrics: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "DASHBOARD_METRICS_ERROR",
            "message": "Failed to compile administration metrics."
        }), 500

@admin_bp.route("/violations", methods=["GET"])
@token_required
@role_required(["admin"])
def get_all_violations():
    try:
        violations = ViolationLog.query.order_by(ViolationLog.timestamp.desc()).all()
        
        violations_by_attempt = {}
        ordered_attempt_ids = []
        total_raw_count = len(violations)
        phone_count = 0
        faces_count = 0
        tabs_count = 0

        for v in violations:
            attempt = v.attempt
            if not attempt or not attempt.student or not attempt.exam:
                continue

            ev_type = v.event_type or ""
            if ev_type == "PHONE_DETECTED":
                phone_count += 1
            elif ev_type in ["MULTIPLE_PERSON", "MULTIPLE_FACES"]:
                faces_count += 1
            elif ev_type in ["TAB_SWITCH", "FULLSCREEN_EXIT"]:
                tabs_count += 1

            att_id = attempt.id
            if att_id not in violations_by_attempt:
                ordered_attempt_ids.append(att_id)
                student = attempt.student
                user_id_val = student.last_name if (student.last_name and student.last_name.strip()) else f"STU{student.id}"
                
                # Fetch/evaluate candidate score if attempt is completed or terminated
                res = Result.query.filter_by(attempt_id=att_id).first()
                if not res and attempt.status in ["SUBMITTED", "AUTO_SUBMITTED", "MALPRACTICE_CANCELLED", "EXPIRED"]:
                    try:
                        from backend.services.evaluation import EvaluationService
                        res = EvaluationService.evaluate_attempt(att_id)
                    except Exception:
                        pass

                total_marks_val = sum(float(q.marks or 1.0) for q in attempt.exam.questions) if attempt.exam else 0.0

                violations_by_attempt[att_id] = {
                    "id": v.id,
                    "attempt_id": att_id,
                    "student_id": student.id,
                    "student_name": student.first_name if student.first_name else "Candidate",
                    "student_userid": user_id_val,
                    "student_email": student.email if student.email else "",
                    "exam_id": attempt.exam.id,
                    "exam_title": attempt.exam.title,
                    "status": attempt.status,
                    "total_violations": 0,
                    "score_obtained": res.total_score if res else 0.0,
                    "percentage": res.percentage if res else 0.0,
                    "total_marks": total_marks_val,
                    "passed": res.passed if res else False,
                    "latest_event_type": v.event_type,
                    "event_type": v.event_type,
                    "latest_confidence": v.confidence,
                    "confidence": v.confidence,
                    "latest_timestamp": (v.timestamp.isoformat() + "Z") if v.timestamp else None,
                    "timestamp": (v.timestamp.isoformat() + "Z") if v.timestamp else None,
                    "action_taken": "TERMINATE" if attempt.status == "MALPRACTICE_CANCELLED" else v.action_taken,
                    "violations": []
                }

            group = violations_by_attempt[att_id]
            group["total_violations"] += 1
            if v.action_taken == "TERMINATE" or attempt.status == "MALPRACTICE_CANCELLED":
                group["action_taken"] = "TERMINATE"

            evidence_url = f"/api/admin/evidence/{v.evidence.id}" if (v.evidence and v.evidence.file_path) else None
            group["violations"].append({
                "id": v.id,
                "event_type": v.event_type,
                "confidence": v.confidence,
                "timestamp": (v.timestamp.isoformat() + "Z") if v.timestamp else None,
                "action_taken": v.action_taken,
                "evidence_path": evidence_url
            })

        data = [violations_by_attempt[aid] for aid in ordered_attempt_ids]

        return jsonify({
            "success": True,
            "violations": data,
            "stats": {
                "total": total_raw_count,
                "phone": phone_count,
                "faces": faces_count,
                "tabs": tabs_count
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching violations: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "VIOLATIONS_ERROR",
            "message": "Failed to fetch violations log."
        }), 500

@admin_bp.route("/audit-logs", methods=["GET"])
@token_required
@role_required(["admin"])
def get_audit_logs():
    try:
        logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).all()
        
        data = []
        for log in logs:
            user = log.user
            data.append({
                "id": log.id,
                "user_email": user.email if user else "System/Guest",
                "action": log.action,
                "ip_address": log.ip_address,
                "user_agent": log.user_agent,
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                "details": log.details
            })
            
        return jsonify({
            "success": True,
            "audit_logs": data
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching audit logs: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "AUDIT_LOG_ERROR",
            "message": "Failed to fetch audit log records."
        }), 500

@admin_bp.route("/evidence/<int:evidence_id>", methods=["GET"])
@token_required
@role_required(["admin"])
def serve_evidence(evidence_id):
    evidence = EvidenceRecord.query.get(evidence_id)
    if not evidence:
        return jsonify({
            "success": False,
            "error_code": "EVIDENCE_NOT_FOUND",
            "message": "Evidence record not found."
        }), 404
        
    # Resolve the absolute path of the file
    # Config.EVIDENCE_DIR.parent because relative path is saved relative to it
    base_dir = Config.EVIDENCE_DIR.parent
    file_path = base_dir / evidence.file_path
    
    if not file_path.exists():
        # Cross-platform fallback: try direct EVIDENCE_DIR with filename
        fallback_path = Config.EVIDENCE_DIR / Path(evidence.file_path).name
        if fallback_path.exists():
            file_path = fallback_path
        else:
            logger.warning(f"Physical evidence file not found at {file_path} or {fallback_path}")
            return jsonify({
                "success": False,
                "error_code": "FILE_NOT_FOUND",
                "message": "The physical evidence image file is missing."
            }), 404

    return send_file(file_path, mimetype=evidence.content_type)


@admin_bp.route("/reports", methods=["GET"])
@token_required
@role_required(["admin"])
def get_reports():
    try:
        # Get exam list for selection (strictly non-deleted examinations)
        exams = Exam.query.filter_by(is_deleted=False).all()
        exams_data = [{"id": e.id, "title": e.title} for e in exams]

        exam_id = request.args.get("exam_id", type=int)
        valid_exam_ids = [e.id for e in exams]
        
        # If no exam selected or requested exam is deleted/not found, use the first valid one if any exist
        if not exam_id or exam_id not in valid_exam_ids:
            exam_id = valid_exam_ids[0] if valid_exam_ids else None

        if not exam_id:
            return jsonify({
                "success": True,
                "exams": [],
                "selected_exam_id": None,
                "statistics": {
                    "total_students": 0,
                    "submitted_count": 0,
                    "cancelled_count": 0,
                    "attending_count": 0,
                    "average_percentage": 0.0,
                    "max_percentage": 0.0,
                    "min_percentage": 0.0,
                    "pass_rate": 0.0
                },
                "attempts": [],
                "pending_access": []
            }), 200

        # Fetch attempts for selected exam (ordered by newest started first)
        attempts = ExamAttempt.query.filter_by(exam_id=exam_id).order_by(ExamAttempt.started_at.desc()).all()
        
        # Auto-heal any existing EXPIRED attempts to SUBMITTED
        needs_commit = False
        for a in attempts:
            if a.status == "EXPIRED":
                a.status = "SUBMITTED"
                if not a.ended_at:
                    a.ended_at = a.started_at
                needs_commit = True
        if needs_commit:
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()

        # Calculate overall stats
        total_students = len(attempts)
        submitted_attempts = [a for a in attempts if a.status in ["SUBMITTED", "AUTO_SUBMITTED", "EXPIRED"]]
        cancelled_attempts = [a for a in attempts if a.status == "MALPRACTICE_CANCELLED"]
        attending_attempts = [a for a in attempts if a.status == "IN_PROGRESS"]
        
        scores = []
        passed_count = 0
        attempts_data = []
        
        for a in attempts:
            result = Result.query.filter_by(attempt_id=a.id).first()
            if not result and a.status in ["SUBMITTED", "AUTO_SUBMITTED", "MALPRACTICE_CANCELLED", "EXPIRED"]:
                try:
                    from backend.services.evaluation import EvaluationService
                    result = EvaluationService.evaluate_attempt(a.id)
                except Exception as eval_err:
                    logger.error(f"Error auto-evaluating attempt {a.id} in get_reports: {str(eval_err)}")

            score = result.total_score if result else 0.0
            percentage = result.percentage if result else 0.0
            passed = result.passed if result else False
            
            if result:
                scores.append(percentage)
                if passed:
                    passed_count += 1
            
            # Count violations
            violations_count = len(a.violations)

            total_marks_val = sum(float(q.marks or 1.0) for q in a.exam.questions) if a.exam else 0.0

            attempts_data.append({
                "attempt_id": a.id,
                "student_email": a.student.email if a.student else "Unknown",
                "student_username": a.student.first_name if a.student else "Unknown",
                "student_userid": a.student.last_name if a.student else "Unknown",
                "status": "SUBMITTED" if a.status in ["SUBMITTED", "AUTO_SUBMITTED", "EXPIRED"] else a.status,
                "score_obtained": score,
                "percentage": percentage,
                "total_marks": total_marks_val,
                "passed": passed,
                "violations_count": violations_count,
                "started_at": a.started_at.isoformat() + "Z" if a.started_at else None,
                "ended_at": a.ended_at.isoformat() + "Z" if a.ended_at else None
            })

        avg_score = round(sum(scores) / len(scores), 2) if scores else 0.0
        max_score = round(max(scores), 2) if scores else 0.0
        min_score = round(min(scores), 2) if scores else 0.0
        pass_rate = round((passed_count / len(scores)) * 100, 2) if scores else 0.0

        stats = {
            "total_students": total_students,
            "submitted_count": len(submitted_attempts),
            "cancelled_count": len(cancelled_attempts),
            "attending_count": len(attending_attempts),
            "average_percentage": avg_score,
            "max_percentage": max_score,
            "min_percentage": min_score,
            "pass_rate": pass_rate
        }

        # Fetch all pending access requests across all active non-deleted exams
        from backend.models import ExamAccess
        pending_access = ExamAccess.query.filter_by(approved=False).order_by(ExamAccess.requested_at.desc()).all()
        pending_data = [{
            "id": pa.id,
            "exam_id": pa.exam_id,
            "exam_title": pa.exam.title if pa.exam else "Unknown",
            "student_email": pa.student.email if pa.student else "Unknown",
            "student_username": pa.student.first_name if pa.student else "Unknown",
            "student_userid": pa.student.last_name if pa.student else "Unknown",
            "requested_at": pa.requested_at.isoformat() + "Z" if pa.requested_at else None
        } for pa in pending_access if pa.exam and not getattr(pa.exam, 'is_deleted', False)]

        return jsonify({
            "success": True,
            "exams": exams_data,
            "selected_exam_id": exam_id,
            "statistics": stats,
            "attempts": attempts_data,
            "pending_access": pending_data
        }), 200

    except Exception as e:
        logger.error(f"Error compiling exam report statistics: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "REPORT_COMPILATION_ERROR",
            "message": "Failed to compile exam results reports."
        }), 500


@admin_bp.route("/reports/export-pdf", methods=["GET"])
@token_required
@role_required(["admin"])
def export_marks_pdf():
    """Generates and streams the Student Examination Marks List PDF report."""
    try:
        from backend.services.pdf_generator import StudentExamMarksPDFService
        exam_id = request.args.get("exam_id", type=int)
        
        if not exam_id:
            first_exam = Exam.query.filter_by(is_deleted=False).first()
            if not first_exam:
                return jsonify({
                    "success": False,
                    "error_code": "NO_EXAMS_FOUND",
                    "message": "No examinations found to generate marks report."
                }), 404
            exam_id = first_exam.id

        exam = Exam.query.filter_by(id=exam_id, is_deleted=False).first()
        if not exam:
            return jsonify({
                "success": False,
                "error_code": "EXAM_NOT_FOUND",
                "message": f"Examination with ID {exam_id} not found."
            }), 404

        pdf_bytes = StudentExamMarksPDFService.generate_exam_marks_pdf(exam_id)

        # Sanitize exam title for attachment filename
        clean_title = re.sub(r'[^\w\-_\. ]', '_', exam.title).strip().replace(' ', '_')
        filename = f"Student_Marks_Report_{clean_title}.pdf"

        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        logger.error(f"Error generating marks list PDF: {str(e)}", exc_info=True)
        return jsonify({
            "success": False,
            "error_code": "PDF_GENERATION_FAILED",
            "message": f"Failed to generate marks report PDF: {str(e)}"
        }), 500


@admin_bp.route("/presentation/download-pdf", methods=["GET"])
def download_presentation_pdf():
    """Streams the 12-slide executive presentation PDF."""
    try:
        from backend.services.presentation_generator import PresentationService
        pdf_bytes = PresentationService.generate_presentation_pdf()
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name="AI_Proctored_Exam_System_Presentation.pdf"
        )
    except Exception as e:
        logger.error(f"Error downloading presentation PDF: {str(e)}", exc_info=True)
        return jsonify({"success": False, "message": str(e)}), 500


@admin_bp.route("/presentation/download-pptx", methods=["GET"])
def download_presentation_pptx():
    """Generates and streams the PowerPoint (.pptx) presentation."""
    try:
        from pathlib import Path
        project_root = Path(__file__).resolve().parent.parent.parent
        pptx_path = project_root / "client_presentation.pptx"
        
        # If file doesn't exist, try generating it via scripts.generate_pptx
        if not pptx_path.exists():
            try:
                from scripts.generate_pptx import create_presentation
                create_presentation()
            except Exception as gen_err:
                logger.warning(f"Could not generate PPTX: {str(gen_err)}")

        if pptx_path.exists():
            return send_file(
                str(pptx_path),
                mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                as_attachment=True,
                download_name="AI_Proctored_Exam_System_Presentation.pptx"
            )
        else:
            # Fallback to streaming the PDF presentation
            from backend.services.presentation_generator import PresentationService
            pdf_bytes = PresentationService.generate_presentation_pdf()
            return send_file(
                io.BytesIO(pdf_bytes),
                mimetype="application/pdf",
                as_attachment=True,
                download_name="AI_Proctored_Exam_System_Presentation.pdf"
            )
    except Exception as e:
        logger.error(f"Error downloading presentation PPTX: {str(e)}", exc_info=True)
        return jsonify({"success": False, "message": str(e)}), 500


@admin_bp.route("/presentation/download-html", methods=["GET"])
def download_presentation_html():
    """Streams the standalone interactive HTML presentation file."""
    try:
        from pathlib import Path
        project_root = Path(__file__).resolve().parent.parent.parent
        html_path = project_root / "frontend" / "client_presentation.html"
        return send_file(
            str(html_path),
            mimetype="text/html",
            as_attachment=True,
            download_name="AI_Proctored_Exam_System_Presentation.html"
        )
    except Exception as e:
        logger.error(f"Error downloading presentation HTML: {str(e)}", exc_info=True)
        return jsonify({"success": False, "message": str(e)}), 500


@admin_bp.route("/access/<int:access_id>/approve", methods=["POST"])
@token_required
@role_required(["admin"])
def approve_access(access_id):
    from backend.models import ExamAccess
    access = ExamAccess.query.get(access_id)
    if not access:
        return jsonify({
            "success": False,
            "error_code": "ACCESS_RECORD_NOT_FOUND",
            "message": "Access record not found."
        }), 404

    try:
        access.approved = True
        db.session.commit()
        logger.info(f"Admin approved exam access for student {access.student.email} on exam {access.exam.title}")
        return jsonify({
            "success": True,
            "message": f"Successfully approved access for {access.student.email}."
        }), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to approve access: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "APPROVE_ACCESS_FAILED",
            "message": "Failed to approve student access."
        }), 500


@admin_bp.route("/access/<int:access_id>/reject", methods=["POST"])
@token_required
@role_required(["admin"])
def reject_access(access_id):
    from backend.models import ExamAccess
    access = ExamAccess.query.get(access_id)
    if not access:
        return jsonify({
            "success": False,
            "error_code": "ACCESS_RECORD_NOT_FOUND",
            "message": "Access record not found."
        }), 404

    try:
        db.session.delete(access)
        db.session.commit()
        logger.info(f"Admin rejected exam access for student {access.student.email} on exam {access.exam.title}")
        return jsonify({
            "success": True,
            "message": "Successfully rejected access request."
        }), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to reject access: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "REJECT_ACCESS_FAILED",
            "message": "Failed to reject student access request."
        }), 500


@admin_bp.route("/access/exam/<int:exam_id>/approve-all", methods=["POST"])
@token_required
@role_required(["admin"])
def approve_all_access(exam_id):
    from backend.models import ExamAccess
    try:
        pending = ExamAccess.query.filter_by(exam_id=exam_id, approved=False).all()
        for pa in pending:
            pa.approved = True
        db.session.commit()
        logger.info(f"Admin approved all pending access requests for exam {exam_id} ({len(pending)} requests approved)")
        return jsonify({
            "success": True,
            "message": f"Successfully approved access for all {len(pending)} pending students."
        }), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to approve all access: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "APPROVE_ALL_FAILED",
            "message": "Failed to approve all student access requests."
        }), 500


@admin_bp.route("/access/approve-all", methods=["POST"])
@token_required
@role_required(["admin"])
def approve_all_pending_access():
    from backend.models import ExamAccess
    try:
        pending = ExamAccess.query.filter_by(approved=False).all()
        for pa in pending:
            pa.approved = True
        db.session.commit()
        logger.info(f"Admin approved all pending access requests across all exams ({len(pending)} requests approved)")
        return jsonify({
            "success": True,
            "message": f"Successfully approved all {len(pending)} pending student access requests."
        }), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to approve all pending access: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "APPROVE_ALL_FAILED",
            "message": "Failed to approve all pending student access requests."
        }), 500


@admin_bp.route("/access/pending", methods=["GET"])
@token_required
@role_required(["admin"])
def get_pending_access_requests():
    from backend.models import ExamAccess
    try:
        pending_access = ExamAccess.query.filter_by(approved=False).order_by(ExamAccess.requested_at.desc()).all()
        data = [{
            "id": pa.id,
            "exam_id": pa.exam_id,
            "exam_title": pa.exam.title if pa.exam else "Unknown",
            "student_id": pa.student_id,
            "student_email": pa.student.email if pa.student else "Unknown",
            "student_username": pa.student.first_name if pa.student else "Unknown",
            "student_userid": pa.student.last_name if pa.student else "Unknown",
            "requested_at": pa.requested_at.isoformat() + "Z" if pa.requested_at else None
        } for pa in pending_access]
        return jsonify({
            "success": True,
            "pending_access": data,
            "count": len(data)
        }), 200
    except Exception as e:
        logger.error(f"Failed to fetch pending access requests: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "FETCH_PENDING_ACCESS_FAILED",
            "message": "Failed to fetch pending access requests."
        }), 500


@admin_bp.route("/attempts/<int:attempt_id>/reconduct", methods=["POST"])
@token_required
@role_required(["admin"])
def reconduct_attempt(attempt_id):
    from backend.models import ExamAttempt, ExamAccess
    attempt = ExamAttempt.query.get(attempt_id)
    if not attempt:
        return jsonify({
            "success": False,
            "error_code": "ATTEMPT_NOT_FOUND",
            "message": "Examination attempt session not found."
        }), 404

    student_id = attempt.student_id
    exam_id = attempt.exam_id

    try:
        # Delete ALL attempts for this student on this exam (cascades to violations, answers, results)
        all_attempts = ExamAttempt.query.filter_by(student_id=student_id, exam_id=exam_id).all()
        for att in all_attempts:
            db.session.delete(att)
        
        # Clear exam access records so candidate must "Request Access" again
        accesses = ExamAccess.query.filter_by(student_id=student_id, exam_id=exam_id).all()
        for acc in accesses:
            db.session.delete(acc)
            
        db.session.commit()
        logger.info(f"Admin reconducted exam {exam_id} for student {student_id}. Cleared {len(all_attempts)} attempt(s) and reset access to Request Access.")
        return jsonify({
            "success": True,
            "message": "Successfully cleared student attempt and reset exam access. Candidate can now Request Access again."
        }), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to reconduct exam: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "RECONDUCT_EXAM_FAILED",
            "message": "Failed to clear student attempt session."
        }), 500


@admin_bp.route("/attempts/<int:attempt_id>/details", methods=["GET"])
@token_required
@role_required(["admin"])
def get_attempt_details(attempt_id):
    """Returns comprehensive marks, answers audit, questions, and proctoring violations for a student attempt."""
    try:
        from backend.models import ExamAttempt, Result, Question, StudentAnswer, ViolationLog
        attempt = ExamAttempt.query.get(attempt_id)
        if not attempt:
            return jsonify({
                "success": False,
                "error_code": "ATTEMPT_NOT_FOUND",
                "message": "Student attempt session not found."
            }), 404

        exam = attempt.exam
        student = attempt.student

        if attempt.status == "EXPIRED":
            attempt.status = "SUBMITTED"
            if not attempt.ended_at:
                attempt.ended_at = attempt.started_at
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()

        result = Result.query.filter_by(attempt_id=attempt.id).first()
        if not result and attempt.status in ["SUBMITTED", "AUTO_SUBMITTED", "MALPRACTICE_CANCELLED", "EXPIRED"]:
            try:
                from backend.services.evaluation import EvaluationService
                result = EvaluationService.evaluate_attempt(attempt.id)
            except Exception as eval_err:
                logger.error(f"Error evaluating attempt {attempt.id} in get_attempt_details: {str(eval_err)}")

        questions = exam.questions if exam else []
        answers_map = {a.question_id: a for a in attempt.answers}

        total_questions = len(questions)
        correct_count = 0
        wrong_count = 0
        unanswered_count = 0
        total_marks = sum(float(q.marks or 1.0) for q in questions)

        def extract_letter(val):
            if not val:
                return ""
            v = str(val).strip().upper()
            if len(v) >= 2 and v[0].isalpha() and v[1] in [')', '.', '-', ':', ' ']:
                return v[0]
            return v

        questions_detail = []
        for idx, q in enumerate(questions, start=1):
            ans = answers_map.get(q.id)
            has_answered = False
            is_correct = False
            chosen_str = ""

            if q.question_type in ["MCQ", "MULTIPLE_CHOICE", "TF"]:
                selected = [extract_letter(s) for s in (ans.selected_answers or []) if s] if ans else []
                correct_str = q.correct_answer or ""
                correct_list = [extract_letter(c) for c in correct_str.split(",") if c.strip()]
                if selected:
                    has_answered = True
                    chosen_str = ", ".join(selected)
                    if sorted(selected) == sorted(correct_list):
                        is_correct = True
            elif q.question_type == "SHORT_ANSWER":
                candidate_text = (ans.text_answer or "").strip().lower() if ans else ""
                if candidate_text:
                    has_answered = True
                    chosen_str = ans.text_answer or ""
                    correct_text = (q.correct_answer or "").strip().lower()
                    if candidate_text == correct_text:
                        is_correct = True

            if not has_answered:
                unanswered_count += 1
                status = "UNANSWERED"
            elif is_correct:
                correct_count += 1
                status = "CORRECT"
            else:
                wrong_count += 1
                status = "WRONG"

            questions_detail.append({
                "number": idx,
                "question_id": q.id,
                "question_text": q.question_text,
                "question_type": q.question_type,
                "marks": float(q.marks or 1.0),
                "chosen_answer": chosen_str or "No answer recorded",
                "correct_answer": q.correct_answer or "",
                "status": status,
                "is_correct": is_correct
            })

        obtained_marks = float(result.total_score) if result else 0.0
        percentage = float(result.percentage) if result else 0.0
        passed = result.passed if result else (percentage >= 50.0)

        violations_list = []
        for v in attempt.violations:
            evidence_url = f"/api/admin/evidence/{v.evidence.id}" if (v.evidence and v.evidence.file_path) else None
            violations_list.append({
                "id": v.id,
                "event_type": v.event_type,
                "confidence": v.confidence,
                "timestamp": v.timestamp.isoformat() + "Z" if v.timestamp else None,
                "action_taken": v.action_taken,
                "evidence_path": evidence_url,
                "severity": getattr(v, "severity", 1)
            })

        return jsonify({
            "success": True,
            "attempt": {
                "id": attempt.id,
                "student_name": student.first_name if student else "Candidate",
                "candidate_name": student.first_name if student else "Candidate",
                "student_username": student.first_name if student else "Candidate",
                "student_first_name": student.first_name if student else "Candidate",
                "student_userid": student.last_name if (student and student.last_name) else (f"STU{student.id}" if student else "STU1001"),
                "student_id": student.last_name if (student and student.last_name) else (f"STU{student.id}" if student else "STU1001"),
                "user_id": student.last_name if (student and student.last_name) else (f"STU{student.id}" if student else "STU1001"),
                "student_email": student.email if student else "Unknown",
                "exam_title": exam.title if exam else "Examination",
                "exam_id": attempt.exam_id,
                "status": "SUBMITTED" if attempt.status in ["SUBMITTED", "AUTO_SUBMITTED", "EXPIRED"] else attempt.status,
                "started_at": attempt.started_at.isoformat() + "Z" if attempt.started_at else None,
                "ended_at": attempt.ended_at.isoformat() + "Z" if attempt.ended_at else None,
                "total_questions": total_questions,
                "correct_answers": correct_count,
                "wrong_answers": wrong_count,
                "unanswered": unanswered_count,
                "total_marks": total_marks,
                "obtained_marks": obtained_marks,
                "percentage": percentage,
                "result_status": "PASS" if passed else "FAIL",
                "violations_count": len(attempt.violations),
                "violations": violations_list,
                "questions": questions_detail
            }
        }), 200

    except Exception as e:
        logger.error(f"Error fetching attempt details: {str(e)}", exc_info=True)
        return jsonify({
            "success": False,
            "error_code": "FETCH_ATTEMPT_DETAILS_FAILED",
            "message": f"Failed to load attempt details: {str(e)}"
        }), 500


@admin_bp.route("/registrations", methods=["GET"])
@token_required
@role_required(["admin"])
def get_registrations():
    from backend.models.user import User
    from backend.models.attempt import ExamAttempt
    from backend.models.exam import Exam

    try:
        # Get all students
        students = User.query.filter_by(role="student").order_by(User.created_at.desc()).all()
        
        # Get count of active, non-deleted exams
        active_exams_count = Exam.query.filter_by(is_active=True, is_deleted=False).count()
        
        data = []
        for student in students:
            # Count exams completed / written by this student
            written_count = ExamAttempt.query.filter_by(student_id=student.id).filter(
                ExamAttempt.status.in_(["SUBMITTED", "AUTO_SUBMITTED", "EXPIRED"])
            ).count()
            
            not_attempted_count = max(0, active_exams_count - written_count)
            
            data.append({
                "id": student.id,
                "email": student.email,
                "first_name": student.first_name, # Candidate Name
                "last_name": student.last_name,   # User ID
                "course": student.course or "Python",
                "phone": student.phone or "-",
                "registration_status": student.registration_status,
                "registration_date": student.created_at.isoformat() + "Z" if student.created_at else None,
                "exams_written_count": written_count,
                "exams_not_attempted_count": not_attempted_count
            })
            
        return jsonify({
            "success": True,
            "registrations": data
        }), 200
        
    except Exception as e:
        logger.error(f"Failed to fetch student registrations: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "FETCH_REGISTRATIONS_FAILED",
            "message": "Failed to fetch student registration records."
        }), 500


@admin_bp.route("/registrations/approve-all", methods=["POST"])
@token_required
@role_required(["admin"])
def approve_all_registrations():
    from backend.models.user import User
    import random
    import string

    try:
        pending_students = User.query.filter_by(role="student", registration_status="PENDING").all()
        if not pending_students:
            return jsonify({
                "success": True,
                "message": "No pending registrations found to approve.",
                "approved_count": 0
            }), 200

        # Fetch all existing User IDs to avoid collisions
        existing_ids = set(r[0] for r in db.session.query(User.last_name).filter(User.last_name != "Not Assigned").all() if r[0])

        approved_count = 0
        for student in pending_students:
            # Assign unique User ID if not assigned
            if not student.last_name or student.last_name == "Not Assigned":
                candidate_id = None
                for _ in range(100):
                    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
                    potential_id = f"STU{suffix}"
                    if potential_id not in existing_ids:
                        candidate_id = potential_id
                        existing_ids.add(candidate_id)
                        break
                
                if not candidate_id:
                    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=7))
                    candidate_id = f"STU{suffix}"
                    existing_ids.add(candidate_id)

                student.last_name = candidate_id

            student.registration_status = "APPROVED"
            approved_count += 1

        db.session.commit()
        logger.info(f"Admin approved all pending student registrations: {approved_count} candidates approved.")
        return jsonify({
            "success": True,
            "message": f"Successfully approved all {approved_count} pending student registration(s).",
            "approved_count": approved_count
        }), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to approve all student registrations: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "APPROVE_ALL_REGISTRATIONS_FAILED",
            "message": "Failed to approve all student registrations."
        }), 500


@admin_bp.route("/registrations/<int:student_id>/approve", methods=["POST"])
@token_required
@role_required(["admin"])
def approve_registration(student_id):
    from backend.models.user import User

    student = User.query.get(student_id)
    if not student or student.role != "student":
        return jsonify({
            "success": False,
            "error_code": "STUDENT_NOT_FOUND",
            "message": "Student record not found."
        }), 404

    try:
        # Generate random unique User ID if not assigned yet
        if not student.last_name or student.last_name == "Not Assigned":
            import random
            import string
            
            generated_id = None
            for _ in range(100):
                suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
                candidate_id = f"STU{suffix}"
                
                # Check uniqueness
                exists = User.query.filter_by(last_name=candidate_id).first()
                if not exists:
                    generated_id = candidate_id
                    break
            
            if not generated_id:
                # Fallback if somehow 100 collisions happen
                suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=7))
                generated_id = f"STU{suffix}"
                
            student.last_name = generated_id
            
        student.registration_status = "APPROVED"
        db.session.commit()
        logger.info(f"Admin approved student registration globally: {student.email} (User ID assigned: {student.last_name})")
        
        return jsonify({
            "success": True,
            "message": f"Successfully approved registration for candidate {student.first_name}."
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to approve student registration: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "APPROVE_REGISTRATION_FAILED",
            "message": "Failed to approve student registration."
        }), 500


@admin_bp.route("/registrations/<int:student_id>/reject", methods=["POST"])
@token_required
@role_required(["admin"])
def reject_registration(student_id):
    from backend.models.user import User

    student = User.query.get(student_id)
    if not student or student.role != "student":
        return jsonify({
            "success": False,
            "error_code": "STUDENT_NOT_FOUND",
            "message": "Student record not found."
        }), 404

    try:
        student.registration_status = "REJECTED"
        db.session.commit()
        logger.info(f"Admin rejected student registration globally: {student.email}")
        
        return jsonify({
            "success": True,
            "message": f"Successfully rejected registration for candidate {student.first_name}."
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to reject student registration: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "REJECT_REGISTRATION_FAILED",
            "message": "Failed to reject student registration."
        }), 500


@admin_bp.route("/registrations/<int:student_id>/course", methods=["PUT", "PATCH", "POST"])
@admin_bp.route("/registrations/<int:student_id>", methods=["PUT", "PATCH"])
@token_required
@role_required(["admin"])
def update_student_course(student_id):
    from backend.models.user import User
    from backend.models import AuditLog

    student = User.query.filter_by(id=student_id, role="student").first()
    if not student:
        return jsonify({
            "success": False,
            "error_code": "STUDENT_NOT_FOUND",
            "message": "Student record not found."
        }), 404

    data = request.get_json(silent=True) or {}
    new_course = data.get("course")
    if not new_course or not str(new_course).strip():
        return jsonify({
            "success": False,
            "error_code": "INVALID_COURSE",
            "message": "Course selection is required."
        }), 400

    course_clean = str(new_course).strip()
    course_map = {
        "aptitude": "Aptitude",
        "python": "Python",
        "java": "Java",
        "drive": "Aptitude"
    }
    canonical_course = course_map.get(course_clean.lower(), course_clean)
    if canonical_course not in ["Aptitude", "Python", "Java"]:
        return jsonify({
            "success": False,
            "error_code": "INVALID_COURSE",
            "message": f"Invalid course '{new_course}'. Valid courses are: Aptitude, Python, Java."
        }), 400

    old_course = student.course or "Python"
    student.course = canonical_course

    try:
        current_admin = getattr(request, "current_user", None)
        admin_id = current_admin.id if current_admin else None
        audit = AuditLog(
            user_id=student.id,
            action="STUDENT_COURSE_UPDATED",
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string if request.user_agent else None
        )
        audit.details = {
            "admin_user_id": admin_id,
            "student_email": student.email,
            "student_name": student.first_name,
            "old_course": old_course,
            "new_course": canonical_course
        }
        db.session.add(audit)
    except Exception as e:
        logger.warning(f"Could not record course update audit log: {str(e)}")

    try:
        db.session.commit()
        logger.info(f"Admin updated course for student {student.email} (ID: {student.id}) from '{old_course}' to '{canonical_course}'")
        return jsonify({
            "success": True,
            "message": f"Successfully updated course to {canonical_course} for candidate {student.first_name}.",
            "student": {
                "id": student.id,
                "first_name": student.first_name,
                "last_name": student.last_name,
                "email": student.email,
                "course": student.course
            }
        }), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to update student course: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "UPDATE_COURSE_FAILED",
            "message": f"Failed to update student course: {str(e)}"
        }), 500


@admin_bp.route("/registrations/<int:student_id>", methods=["DELETE"])
@token_required
@role_required(["admin"])
def delete_registration(student_id):
    from backend.models.user import User
    from backend.models.attempt import ExamAttempt
    from backend.models.access import ExamAccess
    from backend.models import AuditLog

    student = User.query.filter_by(id=student_id, role="student").first()
    if not student:
        return jsonify({
            "success": False,
            "error_code": "STUDENT_NOT_FOUND",
            "message": "Student not found."
        }), 404

    try:
        deleted_email = student.email
        deleted_name = student.first_name

        # 1. Clean up evidence snapshot photos from disk if present
        from backend.config import Config
        from pathlib import Path
        attempts = ExamAttempt.query.filter_by(student_id=student.id).all()
        for attempt in attempts:
            if hasattr(attempt, 'evidences') and attempt.evidences:
                for ev in attempt.evidences:
                    if ev.file_path:
                        try:
                            p = Path(ev.file_path)
                            if not p.is_absolute():
                                p = Config.PROJECT_ROOT / p
                            if p.exists() and p.is_file():
                                p.unlink()
                        except Exception:
                            pass
            # Cascade deletes answers, violations, evidence records, and result
            db.session.delete(attempt)

        # 2. Delete all access permissions
        accesses = ExamAccess.query.filter_by(student_id=student.id).all()
        for access in accesses:
            db.session.delete(access)

        # 3. Delete password reset tokens if any
        try:
            from backend.models.password_reset import PasswordReset
            PasswordReset.query.filter_by(user_id=student.id).delete()
        except Exception:
            pass

        # 4. Delete audit logs
        AuditLog.query.filter_by(user_id=student.id).delete()

        # 5. Completely delete the student user from users table
        db.session.delete(student)
        db.session.commit()

        logger.info(f"Admin permanently deleted student {deleted_email} ({deleted_name}). Account completely removed for fresh re-registration.")
        return jsonify({
            "success": True,
            "message": f"Candidate {deleted_name} ({deleted_email}) permanently deleted. They can now register again fresh."
        }), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to permanently delete student user: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "DELETE_STUDENT_FAILED",
            "message": f"Failed to permanently delete student: {str(e)}"
        }), 500


@admin_bp.route("/notifications", methods=["GET"])
@token_required
@role_required(["admin"])
def get_notifications():
    from backend.models.user import User
    from backend.models.access import ExamAccess

    try:
        # Fetch pending registrations
        pending_regs = User.query.filter_by(role="student", registration_status="PENDING").all()
        regs_data = [{
            "id": f"reg-{r.id}",
            "raw_id": r.id,
            "type": "registration",
            "title": "New Registration Request",
            "message": f"{r.first_name} ({r.last_name}) requested account approval.",
            "timestamp": r.created_at.isoformat() + "Z" if r.created_at else None,
            "link": "registrations.html?status=PENDING"
        } for r in pending_regs]

        # Fetch pending exam access requests
        pending_access = ExamAccess.query.filter_by(approved=False).all()
        access_data = [{
            "id": f"access-{a.id}",
            "raw_id": a.id,
            "type": "access",
            "title": "New Exam Access Request",
            "message": f"{a.student.first_name} requested access to {a.exam.title}.",
            "timestamp": a.requested_at.isoformat() + "Z" if a.requested_at else None,
            "link": f"results.html?exam_id={a.exam_id}"
        } for a in pending_access]

        # Fetch pending password reset requests
        from backend.models.password_reset import PasswordResetRequest
        pending_resets = PasswordResetRequest.query.filter_by(status="PENDING").all()
        resets_data = [{
            "id": f"reset-{p.id}",
            "raw_id": p.id,
            "type": "password_reset",
            "title": "Password Reset Request",
            "message": f"{p.user.first_name if p.user else 'Student'} requested password reset approval.",
            "timestamp": p.requested_at.isoformat() + "Z" if p.requested_at else None,
            "link": "registrations.html#resets"
        } for p in pending_resets]

        all_notifications = regs_data + access_data + resets_data
        # Sort by timestamp desc
        all_notifications.sort(key=lambda x: x["timestamp"] or "", reverse=True)

        return jsonify({
            "success": True,
            "notifications": all_notifications
        }), 200

    except Exception as e:
        logger.error(f"Failed to fetch admin notifications: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "FETCH_NOTIFICATIONS_FAILED",
            "message": "Failed to load notifications."
        }), 500


@admin_bp.route("/password-resets", methods=["GET"])
@token_required
@role_required(["admin"])
def get_password_resets():
    from backend.models.password_reset import PasswordResetRequest
    try:
        # Order pending first, then by requested_at desc
        resets = PasswordResetRequest.query.order_by(
            PasswordResetRequest.status == "PENDING",
            PasswordResetRequest.requested_at.desc()
        ).all()
        # Sort so PENDING is at the top
        resets.sort(key=lambda r: 0 if r.status == "PENDING" else 1)
        
        return jsonify({
            "success": True,
            "resets": [r.to_dict() for r in resets]
        }), 200
    except Exception as e:
        logger.error(f"Failed to fetch password reset requests: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "FETCH_RESETS_FAILED",
            "message": "Failed to load password reset requests."
        }), 500


@admin_bp.route("/password-resets/<int:reset_id>/approve", methods=["POST"])
@token_required
@role_required(["admin"])
def approve_password_reset(reset_id):
    from backend.models import PasswordResetRequest, AuditLog
    import datetime

    try:
        reset_req = PasswordResetRequest.query.get(reset_id)
        if not reset_req:
            return jsonify({
                "success": False,
                "error_code": "RESET_REQUEST_NOT_FOUND",
                "message": "Password reset request not found."
            }), 404

        reset_req.status = "APPROVED"
        reset_req.approved_at = datetime.datetime.utcnow()

        audit = AuditLog(
            user_id=request.current_user.id,
            action="ADMIN_APPROVED_PASSWORD_RESET",
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent")
        )
        audit.details = {"reset_id": reset_id, "student_id": reset_req.user_id, "student_email": reset_req.user.email if reset_req.user else None}
        db.session.add(audit)
        db.session.commit()

        logger.info(f"Admin approved password reset for student: {reset_req.user.email if reset_req.user else reset_req.user_id}")
        return jsonify({
            "success": True,
            "message": f"Successfully approved password reset for candidate {reset_req.user.first_name if reset_req.user else ''}."
        }), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to approve password reset: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "APPROVE_RESET_FAILED",
            "message": f"Failed to approve password reset request: {str(e)}"
        }), 500


@admin_bp.route("/password-resets/<int:reset_id>/reject", methods=["POST"])
@token_required
@role_required(["admin"])
def reject_password_reset(reset_id):
    from backend.models import PasswordResetRequest, AuditLog

    try:
        reset_req = PasswordResetRequest.query.get(reset_id)
        if not reset_req:
            return jsonify({
                "success": False,
                "error_code": "RESET_REQUEST_NOT_FOUND",
                "message": "Password reset request not found."
            }), 404

        reset_req.status = "REJECTED"

        audit = AuditLog(
            user_id=request.current_user.id,
            action="ADMIN_REJECTED_PASSWORD_RESET",
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent")
        )
        audit.details = {"reset_id": reset_id, "student_id": reset_req.user_id}
        db.session.add(audit)
        db.session.commit()

        logger.info(f"Admin rejected password reset for student: {reset_req.user.email if reset_req.user else reset_req.user_id}")
        return jsonify({
            "success": True,
            "message": f"Password reset request rejected."
        }), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to reject password reset: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "REJECT_RESET_FAILED",
            "message": f"Failed to reject password reset request: {str(e)}"
        }), 500


@admin_bp.route("/system/storage", methods=["GET"])
@token_required
@role_required(["admin"])
def get_storage_metrics():
    from backend.models import db, User, Exam, Question, ExamAttempt, StudentAnswer, ViolationLog, Evidence
    from backend.config import Config
    from sqlalchemy import text
    import os

    try:
        engine_name = db.engine.name
        metrics = {
            "database_type": engine_name,
            "max_free_tier_storage": "512 MB (0.5 GB)",
            "total_db_size": "Unknown",
            "percent_used": "0%",
            "tables": {},
            "evidence_files_count": 0,
            "evidence_disk_size": "0 KB"
        }

        # 1. Database Size & Table Breakdown
        if engine_name == "postgresql":
            # Postgres (Neon) exact size queries
            res = db.session.execute(text("SELECT pg_size_pretty(pg_database_size(current_database())), pg_database_size(current_database())")).fetchone()
            if res:
                metrics["total_db_size"] = res[0]
                bytes_used = res[1]
                metrics["bytes_used"] = bytes_used
                metrics["percent_used"] = f"{(bytes_used / (512 * 1024 * 1024)) * 100:.2f}%"

            table_query = text("""
                SELECT c.relname, pg_size_pretty(pg_total_relation_size(c.oid)), c.reltuples::bigint
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind = 'r'
                ORDER BY pg_total_relation_size(c.oid) DESC
            """)
            table_rows = db.session.execute(table_query).fetchall()
            for row in table_rows:
                metrics["tables"][row[0]] = {
                    "size": row[1],
                    "estimated_rows": row[2]
                }
        else:
            # SQLite local fallback
            db_path = db.engine.url.database
            if db_path and os.path.exists(db_path):
                sz = os.path.getsize(db_path)
                metrics["total_db_size"] = f"{sz / 1024:.1f} KB"
                metrics["bytes_used"] = sz
                metrics["percent_used"] = f"{(sz / (512 * 1024 * 1024)) * 100:.3f}%"

            metrics["tables"] = {
                "users": {"rows": User.query.count()},
                "exams": {"rows": Exam.query.count()},
                "questions": {"rows": Question.query.count()},
                "exam_attempts": {"rows": ExamAttempt.query.count()},
                "student_answers": {"rows": StudentAnswer.query.count()},
                "violation_logs": {"rows": ViolationLog.query.count()},
                "evidence": {"rows": Evidence.query.count()}
            }

        # 2. Evidence Files Storage on Disk
        evidence_dir = Config.EVIDENCE_DIR
        if evidence_dir.exists():
            files = list(evidence_dir.glob("*.jpg"))
            total_bytes = sum(f.stat().st_size for f in files if f.is_file())
            metrics["evidence_files_count"] = len(files)
            if total_bytes > 1024 * 1024:
                metrics["evidence_disk_size"] = f"{total_bytes / (1024 * 1024):.2f} MB"
            else:
                metrics["evidence_disk_size"] = f"{total_bytes / 1024:.1f} KB"

        return jsonify({
            "success": True,
            "metrics": metrics
        }), 200

    except Exception as e:
        logger.error(f"Failed to fetch storage metrics: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "STORAGE_METRICS_FAILED",
            "message": f"Failed to calculate storage metrics: {str(e)}"
        }), 500




