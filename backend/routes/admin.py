from flask import Blueprint, request, jsonify, send_file
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
        total_exams = Exam.query.count()
        active_exams = Exam.query.filter_by(is_active=True).count()
        
        # Candidate counts
        total_candidates = User.query.filter_by(role="student").count()
        
        # Exam attempts counts
        completed_attempts = ExamAttempt.query.filter(
            ExamAttempt.status.in_(["SUBMITTED", "AUTO_SUBMITTED"])
        ).count()
        
        malpractice_cases = ExamAttempt.query.filter_by(
            status="MALPRACTICE_CANCELLED"
        ).count()
        
        # Active sessions
        active_sessions = ExamAttempt.query.filter_by(status="IN_PROGRESS").count()

        # Average Score
        avg_score_query = db.session.query(db.func.avg(Result.percentage)).scalar()
        average_score = round(float(avg_score_query), 2) if avg_score_query else 0.0

        # Recent violations
        recent_violation_records = ViolationLog.query.order_by(
            ViolationLog.timestamp.desc()
        ).limit(10).all()

        recent_violations = []
        for v in recent_violation_records:
            attempt = v.attempt
            recent_violations.append({
                "id": v.id,
                "attempt_id": attempt.id,
                "exam_title": attempt.exam.title,
                "student_name": f"{attempt.student.first_name} {attempt.student.last_name}",
                "event_type": v.event_type,
                "confidence": v.confidence,
                "timestamp": v.timestamp.isoformat() if v.timestamp else None,
                "action_taken": v.action_taken
            })

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
        
        data = []
        for v in violations:
            attempt = v.attempt
            data.append({
                "id": v.id,
                "attempt_id": attempt.id,
                "student_name": f"{attempt.student.first_name} {attempt.student.last_name}",
                "student_email": attempt.student.email,
                "exam_title": attempt.exam.title,
                "event_type": v.event_type,
                "confidence": v.confidence,
                "timestamp": v.timestamp.isoformat() if v.timestamp else None,
                "severity": v.severity,
                "action_taken": v.action_taken,
                "evidence_path": f"/api/admin/evidence/{v.evidence.id}" if v.evidence else None
            })
            
        return jsonify({
            "success": True,
            "violations": data
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
        # Get exam list for selection
        exams = Exam.query.all()
        exams_data = [{"id": e.id, "title": e.title} for e in exams]

        exam_id = request.args.get("exam_id", type=int)
        
        # If no exam selected, use the first one if any exist
        if not exam_id and exams:
            exam_id = exams[0].id

        if not exam_id:
            return jsonify({
                "success": True,
                "exams": [],
                "statistics": {},
                "attempts": [],
                "pending_access": []
            }), 200

        # Fetch attempts for selected exam (ordered by newest started first)
        attempts = ExamAttempt.query.filter_by(exam_id=exam_id).order_by(ExamAttempt.started_at.desc()).all()
        
        # Calculate overall stats
        total_students = len(attempts)
        submitted_attempts = [a for a in attempts if a.status in ["SUBMITTED", "AUTO_SUBMITTED"]]
        cancelled_attempts = [a for a in attempts if a.status == "MALPRACTICE_CANCELLED"]
        attending_attempts = [a for a in attempts if a.status == "IN_PROGRESS"]
        
        scores = []
        passed_count = 0
        attempts_data = []
        
        for a in attempts:
            result = Result.query.filter_by(attempt_id=a.id).first()
            score = result.total_score if result else 0.0
            percentage = result.percentage if result else 0.0
            passed = result.passed if result else False
            
            if result:
                scores.append(percentage)
                if passed:
                    passed_count += 1
            
            # Count violations
            violations_count = len(a.violations)

            attempts_data.append({
                "attempt_id": a.id,
                "student_email": a.student.email if a.student else "Unknown",
                "status": a.status,
                "score_obtained": score,
                "percentage": percentage,
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

        # Fetch pending access requests for the selected exam
        from backend.models import ExamAccess
        pending_access = ExamAccess.query.filter_by(exam_id=exam_id, approved=False).all()
        pending_data = [{
            "id": pa.id,
            "student_email": pa.student.email if pa.student else "Unknown",
            "requested_at": pa.requested_at.isoformat() + "Z" if pa.requested_at else None
        } for pa in pending_access]

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
        # Delete attempt (cascades database deletions to violations, answers, results)
        db.session.delete(attempt)
        
        # Ensure access is granted for re-take
        access = ExamAccess.query.filter_by(student_id=student_id, exam_id=exam_id).first()
        if access:
            access.approved = True
        else:
            new_access = ExamAccess(student_id=student_id, exam_id=exam_id, approved=True)
            db.session.add(new_access)
            
        db.session.commit()
        logger.info(f"Admin reset attempt {attempt_id} for student {student_id}. Permitted reconduct of exam {exam_id}.")
        return jsonify({
            "success": True,
            "message": "Successfully cleared student attempt session. Candidate is authorized to reconduct the exam."
        }), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to reconduct exam: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "RECONDUCT_EXAM_FAILED",
            "message": "Failed to clear student attempt session."
        }), 500


