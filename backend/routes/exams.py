from flask import Blueprint, request, jsonify
from backend.models import db, Exam, ExamSecurityConfig, AuditLog
from backend.utils.security import token_required, role_required
from backend.utils.logger import get_logger

logger = get_logger()
exams_bp = Blueprint("exams", __name__)

@exams_bp.route("", methods=["GET"])
@token_required
def get_all_exams():
    user = request.current_user
    
    if user.role == "admin":
        exams = Exam.query.filter_by(is_deleted=False).all()
        return jsonify({
            "success": True,
            "exams": [exam.to_dict(include_config=True) for exam in exams]
        }), 200
    else:
        # Candidates can only see active, non-deleted exams assigned to their course
        student_course = (user.course or "").strip()
        sc_lower = student_course.lower()
        if sc_lower == "drive":
            exams = Exam.query.filter(
                Exam.is_active == True,
                Exam.is_deleted == False,
                db.or_(Exam.course == "Drive", Exam.course == "All Courses")
            ).all()
        elif sc_lower == "python":
            exams = Exam.query.filter(
                Exam.is_active == True,
                Exam.is_deleted == False,
                db.or_(Exam.course == "Python", Exam.course == "Python & Java", Exam.course == "All Courses", Exam.course == None)
            ).all()
        elif sc_lower == "java":
            exams = Exam.query.filter(
                Exam.is_active == True,
                Exam.is_deleted == False,
                db.or_(Exam.course == "Java", Exam.course == "Python & Java", Exam.course == "All Courses", Exam.course == None)
            ).all()
        else:
            # Fallback for legacy students without course set
            exams = Exam.query.filter_by(is_active=True, is_deleted=False).all()

        # Enforce exact access rule
        exams = [exam for exam in exams if exam.is_accessible_by(student_course)]

        from backend.models import ExamAttempt, ExamAccess
        attempts = ExamAttempt.query.filter_by(student_id=user.id).all()
        attempted_exam_ids = {a.exam_id for a in attempts}
        
        accesses = ExamAccess.query.filter_by(student_id=user.id).all()
        access_map = {a.exam_id: a for a in accesses}
        
        exams_data = []
        for exam in exams:
            d = exam.to_dict(include_config=True)
            d["attempted"] = exam.id in attempted_exam_ids
            if d["attempted"]:
                attempt_obj = next((a for a in attempts if a.exam_id == exam.id), None)
                d["attempt_id"] = attempt_obj.id if attempt_obj else None
                d["attempt_status"] = attempt_obj.status if attempt_obj else None
                d["session_token"] = attempt_obj.session_token if attempt_obj else None
                if attempt_obj and attempt_obj.status != "IN_PROGRESS":
                    from backend.models import Result
                    res_obj = Result.query.filter_by(attempt_id=attempt_obj.id).first()
                    if not res_obj and attempt_obj.status in ["SUBMITTED", "AUTO_SUBMITTED", "MALPRACTICE_CANCELLED", "EXPIRED"]:
                        try:
                            from backend.services.evaluation import EvaluationService
                            res_obj = EvaluationService.evaluate_attempt(attempt_obj.id)
                        except Exception:
                            pass
                    if res_obj:
                        d["score_obtained"] = res_obj.total_score
                        d["percentage"] = res_obj.percentage
                        d["passed"] = res_obj.passed
            
            # Access permission check: requires per-exam request and admin approval
            access_obj = access_map.get(exam.id)
            if access_obj:
                d["access_status"] = "APPROVED" if access_obj.approved else "PENDING"
            else:
                d["access_status"] = "UNREQUESTED"
                
            exams_data.append(d)
            
        return jsonify({
            "success": True,
            "exams": exams_data
        }), 200

@exams_bp.route("/<int:exam_id>", methods=["GET"])
@token_required
def get_exam_by_id(exam_id):
    user = request.current_user
    exam = Exam.query.filter_by(id=exam_id, is_deleted=False).first()
    
    if not exam:
        return jsonify({
            "success": False,
            "error_code": "EXAM_NOT_FOUND",
            "message": f"Exam with ID {exam_id} not found."
        }), 404
        
    # Standard students shouldn't access inactive exams
    if user.role != "admin":
        if not exam.is_active:
            return jsonify({
                "success": False,
                "error_code": "EXAM_INACTIVE",
                "message": "This examination is not currently active."
            }), 403

        # Check course assignment
        if not exam.is_accessible_by(user.course):
            return jsonify({
                "success": False,
                "error_code": "EXAM_COURSE_MISMATCH",
                "message": f"This examination is assigned to {exam.course} students only."
            }), 403

    return jsonify({
        "success": True,
        "exam": exam.to_dict(include_config=True)
    }), 200

@exams_bp.route("", methods=["POST"])
@token_required
@role_required(["admin"])
def create_exam():
    user = request.current_user
    data = request.get_json() or {}
    
    title = data.get("title")
    description = data.get("description", "")
    duration_minutes = data.get("duration_minutes", 60)
    sec_cfg = data.get("security_config", {})

    raw_course = data.get("course", "Python & Java")
    course = raw_course.strip() if isinstance(raw_course, str) else "Python & Java"
    if course not in ["Drive", "Python", "Java", "Python & Java", "All Courses"]:
        course = "Python & Java"

    if not title:
        return jsonify({
            "success": False,
            "error_code": "TITLE_REQUIRED",
            "message": "Exam title is required."
        }), 400

    try:
        # Create exam record
        exam = Exam(
            title=title,
            description=description,
            duration_minutes=int(duration_minutes),
            created_by=user.id,
            is_active=data.get("is_active", True),
            course=course
        )
        db.session.add(exam)
        db.session.flush() # Flush to get exam.id for configuration binding

        # Create security configuration record
        security_config = ExamSecurityConfig(
            exam_id=exam.id,
            head_turn_limit=sec_cfg.get("head_turn_limit", 5),
            tab_switch_limit=sec_cfg.get("tab_switch_limit", 3),
            multiple_person_limit=sec_cfg.get("multiple_person_limit", 3),
            mobile_limit=sec_cfg.get("mobile_limit", 2),
            fullscreen_exit_limit=sec_cfg.get("fullscreen_exit_limit", 3),
            cooldown_seconds=sec_cfg.get("cooldown_seconds", 2),
            heartbeat_interval=sec_cfg.get("heartbeat_interval", 5),
            network_grace_period=sec_cfg.get("network_grace_period", 30),
            phone_confidence=sec_cfg.get("phone_confidence", 0.7),
            person_confidence=sec_cfg.get("person_confidence", 0.6),
            face_confidence=sec_cfg.get("face_confidence", 0.5)
        )
        db.session.add(security_config)
        
        # Audit log creation
        audit = AuditLog(
            user_id=user.id,
            action="EXAM_CREATED",
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent")
        )
        audit.details = {"exam_id": exam.id, "title": exam.title, "course": exam.course}
        db.session.add(audit)
        
        db.session.commit()
        logger.info(f"Exam created by admin {user.email}: {title} (ID: {exam.id}, Course: {course})")
        
        return jsonify({
            "success": True,
            "message": "Exam created successfully.",
            "exam": exam.to_dict(include_config=True)
        }), 201

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating exam: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "EXAM_CREATION_FAILED",
            "message": "Failed to create examination."
        }), 500

@exams_bp.route("/<int:exam_id>", methods=["PUT"])
@token_required
@role_required(["admin"])
def update_exam(exam_id):
    user = request.current_user
    exam = Exam.query.filter_by(id=exam_id, is_deleted=False).first()
    
    if not exam:
        return jsonify({
            "success": False,
            "error_code": "EXAM_NOT_FOUND",
            "message": f"Exam with ID {exam_id} not found."
        }), 404

    data = request.get_json() or {}
    
    try:
        # Update details
        if "title" in data:
            exam.title = data["title"]
        if "description" in data:
            exam.description = data["description"]
        if "duration_minutes" in data:
            exam.duration_minutes = int(data["duration_minutes"])
        if "is_active" in data:
            exam.is_active = bool(data["is_active"])
        if "course" in data:
            up_course = data["course"].strip() if isinstance(data["course"], str) else "Python & Java"
            if up_course in ["Drive", "Python", "Java", "Python & Java", "All Courses"]:
                exam.course = up_course

        # Update security configs if specified
        sec_cfg = data.get("security_config")
        if sec_cfg and exam.security_config:
            cfg = exam.security_config
            cfg.head_turn_limit = sec_cfg.get("head_turn_limit", cfg.head_turn_limit)
            cfg.tab_switch_limit = sec_cfg.get("tab_switch_limit", cfg.tab_switch_limit)
            cfg.multiple_person_limit = sec_cfg.get("multiple_person_limit", cfg.multiple_person_limit)
            cfg.mobile_limit = sec_cfg.get("mobile_limit", cfg.mobile_limit)
            cfg.fullscreen_exit_limit = sec_cfg.get("fullscreen_exit_limit", cfg.fullscreen_exit_limit)
            cfg.cooldown_seconds = sec_cfg.get("cooldown_seconds", cfg.cooldown_seconds)
            cfg.heartbeat_interval = sec_cfg.get("heartbeat_interval", cfg.heartbeat_interval)
            cfg.network_grace_period = sec_cfg.get("network_grace_period", cfg.network_grace_period)
            cfg.phone_confidence = sec_cfg.get("phone_confidence", cfg.phone_confidence)
            cfg.person_confidence = sec_cfg.get("person_confidence", cfg.person_confidence)
            cfg.face_confidence = sec_cfg.get("face_confidence", cfg.face_confidence)
        elif sec_cfg and not exam.security_config:
            cfg = ExamSecurityConfig(
                exam_id=exam.id,
                head_turn_limit=sec_cfg.get("head_turn_limit", 5),
                tab_switch_limit=sec_cfg.get("tab_switch_limit", 3),
                multiple_person_limit=sec_cfg.get("multiple_person_limit", 3),
                mobile_limit=sec_cfg.get("mobile_limit", 2),
                fullscreen_exit_limit=sec_cfg.get("fullscreen_exit_limit", 3),
                cooldown_seconds=sec_cfg.get("cooldown_seconds", 2),
                heartbeat_interval=sec_cfg.get("heartbeat_interval", 5),
                network_grace_period=sec_cfg.get("network_grace_period", 30),
                phone_confidence=sec_cfg.get("phone_confidence", 0.7),
                person_confidence=sec_cfg.get("person_confidence", 0.6),
                face_confidence=sec_cfg.get("face_confidence", 0.5)
            )
            db.session.add(cfg)

        # Log audit trail
        audit = AuditLog(
            user_id=user.id,
            action="EXAM_UPDATED",
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent")
        )
        audit.details = {"exam_id": exam.id, "title": exam.title}
        db.session.add(audit)
        
        db.session.commit()
        logger.info(f"Exam updated by admin {user.email}: {exam.title} (ID: {exam.id})")
        
        return jsonify({
            "success": True,
            "message": "Exam updated successfully.",
            "exam": exam.to_dict(include_config=True)
        }), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating exam: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "EXAM_UPDATE_FAILED",
            "message": "Failed to update examination details."
        }), 500

@exams_bp.route("/<int:exam_id>/toggle-status", methods=["POST", "PATCH"])
@token_required
@role_required(["admin"])
def toggle_exam_status(exam_id):
    user = request.current_user
    exam = Exam.query.filter_by(id=exam_id, is_deleted=False).first()
    if not exam:
        return jsonify({
            "success": False,
            "error_code": "EXAM_NOT_FOUND",
            "message": f"Exam with ID {exam_id} not found."
        }), 404

    data = request.get_json() or {}
    new_status = data.get("is_active")
    if new_status is None:
        exam.is_active = not exam.is_active
    else:
        exam.is_active = bool(new_status)

    try:
        audit = AuditLog(
            user_id=user.id,
            action="EXAM_STATUS_TOGGLED",
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent")
        )
        audit.details = {"exam_id": exam.id, "title": exam.title, "is_active": exam.is_active}
        db.session.add(audit)
        db.session.commit()

        status_str = "Active" if exam.is_active else "Inactive"
        logger.info(f"Exam {exam.title} (ID: {exam.id}) status toggled to {status_str} by admin {user.email}")
        return jsonify({
            "success": True,
            "message": f"Exam '{exam.title}' is now {status_str}.",
            "is_active": exam.is_active
        }), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error toggling exam status: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "TOGGLE_STATUS_FAILED",
            "message": "Failed to update exam status."
        }), 500

@exams_bp.route("/<int:exam_id>", methods=["DELETE"])
@token_required
@role_required(["admin"])
def delete_exam(exam_id):
    user = request.current_user
    exam = Exam.query.filter_by(id=exam_id, is_deleted=False).first()
    
    if not exam:
        return jsonify({
            "success": False,
            "error_code": "EXAM_NOT_FOUND",
            "message": f"Exam with ID {exam_id} not found."
        }), 404

    try:
        # Perform soft delete
        title = exam.title
        exam.is_deleted = True
        exam.is_active = False
        
        # Log audit trail
        audit = AuditLog(
            user_id=user.id,
            action="EXAM_DELETED",
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent")
        )
        audit.details = {"exam_id": exam_id, "title": title}
        db.session.add(audit)
        
        db.session.commit()
        logger.info(f"Exam soft-deleted by admin {user.email}: {title} (ID: {exam_id})")
        
        return jsonify({
            "success": True,
            "message": "Exam deleted successfully."
        }), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting exam: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "EXAM_DELETION_FAILED",
            "message": "Failed to delete examination."
        }), 500


@exams_bp.route("/<int:exam_id>/request-access", methods=["POST"])
@token_required
def request_exam_access(exam_id):
    user = request.current_user
    if user.role != "student":
        return jsonify({
            "success": False,
            "error_code": "STUDENTS_ONLY",
            "message": "Only candidate accounts can request exam access."
        }), 403

    from backend.models import ExamAccess, Exam
    exam = Exam.query.get(exam_id)
    if not exam or not exam.is_active:
        return jsonify({
            "success": False,
            "error_code": "EXAM_NOT_FOUND",
            "message": "Exam not found or inactive."
        }), 404

    # Enforce course match
    if not exam.is_accessible_by(user.course):
        return jsonify({
            "success": False,
            "error_code": "EXAM_COURSE_MISMATCH",
            "message": f"This examination is assigned to {exam.course} students only."
        }), 403

    # Check if access record already exists
    existing = ExamAccess.query.filter_by(student_id=user.id, exam_id=exam_id).first()
    if existing:
        return jsonify({
            "success": True,
            "message": "Access request already submitted.",
            "access_status": "APPROVED" if existing.approved else "PENDING"
        }), 200

    try:
        access_req = ExamAccess(
            student_id=user.id,
            exam_id=exam_id,
            approved=False
        )
        db.session.add(access_req)
        db.session.commit()
        
        logger.info(f"Student {user.email} requested access for exam {exam.title}")
        return jsonify({
            "success": True,
            "message": "Exam access request submitted successfully. Please wait for admin approval.",
            "access_status": "PENDING"
        }), 201
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to submit exam access request: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "REQUEST_ACCESS_FAILED",
            "message": "Failed to submit access request."
        }), 500

