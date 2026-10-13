from flask import Blueprint, request, jsonify
from backend.models import db, ExamAttempt, StudentAnswer, AuditLog
from backend.services.session_manager import SessionManager
from backend.services.evaluation import EvaluationService
from backend.utils.security import token_required
from backend.utils.logger import get_logger
import datetime

logger = get_logger()
attempts_bp = Blueprint("attempts", __name__)

@attempts_bp.route("/exams/<int:exam_id>/start", methods=["POST"])
@token_required
def start_exam(exam_id):
    student = request.current_user
    
    if student.role != "student":
        return jsonify({
            "success": False,
            "error_code": "ADMIN_CANNOT_TAKE_EXAM",
            "message": "Administrator accounts cannot initiate examination attempts."
        }), 403

    try:
        attempt = SessionManager.start_session(student.id, exam_id)
        
        # Log audit trail
        audit = AuditLog(
            user_id=student.id,
            action="EXAM_STARTED",
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent")
        )
        audit.details = {"exam_id": exam_id, "attempt_id": attempt.id}
        db.session.add(audit)
        db.session.commit()
        
        return jsonify({
            "success": True,
            "attempt_id": attempt.id,
            "session_token": attempt.session_token,
            "started_at": attempt.started_at.isoformat(),
            "duration_seconds": attempt.exam.duration_minutes * 60,
            "attempt": attempt.to_dict()
        }), 200

    except PermissionError as pe:
        err_msg = str(pe)
        if err_msg == "EXAM_ALREADY_ATTEMPTED":
            return jsonify({
                "success": False,
                "error_code": "EXAM_ALREADY_ATTEMPTED",
                "message": "You have already attempted this examination. Multiple attempts are prohibited."
            }), 400
        elif err_msg == "EXAM_ACCESS_RESTRICTED":
            return jsonify({
                "success": False,
                "error_code": "EXAM_ACCESS_RESTRICTED",
                "message": "Access restricted. You must request and receive administrator approval to write this exam."
            }), 403
        elif err_msg == "EXAM_COURSE_MISMATCH":
            return jsonify({
                "success": False,
                "error_code": "EXAM_COURSE_MISMATCH",
                "message": "This examination is not assigned to your enrolled course."
            }), 403
        return jsonify({
            "success": False,
            "error_code": err_msg,
            "message": "You already have an active exam session. Multiple simultaneous sessions are prohibited."
        }), 400
    except ValueError as ve:
        return jsonify({
            "success": False,
            "error_code": "INVALID_EXAM",
            "message": str(ve)
        }), 404
    except Exception as e:
        logger.error(f"Error starting exam: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "START_EXAM_FAILED",
            "message": "Failed to initiate examination."
        }), 500

@attempts_bp.route("/attempts/<int:attempt_id>/answer", methods=["POST"])
@token_required
def save_answer(attempt_id):
    student = request.current_user
    data = request.get_json() or {}
    session_token = data.get("session_token")
    question_id = data.get("question_id")
    selected_answers = data.get("selected_answers", [])
    text_answer = data.get("text_answer", "")

    if not session_token or not question_id:
        return jsonify({
            "success": False,
            "error_code": "MISSING_SESSION_CREDENTIALS",
            "message": "Session token and question ID are required parameters."
        }), 400

    # Verify student session and limits on the server
    is_valid, session_or_err = SessionManager.verify_session(attempt_id, student.id, session_token)
    if not is_valid:
        return jsonify({
            "success": False,
            "error_code": session_or_err,
            "message": f"Answer not saved: {session_or_err.replace('_', ' ').title()}"
        }), 403

    attempt = session_or_err

    try:
        # Check if answer record already exists to ensure idempotency
        answer = StudentAnswer.query.filter_by(
            attempt_id=attempt.id,
            question_id=question_id
        ).first()

        if not answer:
            answer = StudentAnswer(
                attempt_id=attempt.id,
                question_id=question_id
            )
            db.session.add(answer)

        # Update values
        answer.selected_answers = selected_answers
        answer.text_answer = text_answer
        answer.saved_at = datetime.datetime.utcnow()
        
        # Update heartbeat last_seen on every answer save
        attempt.last_heartbeat = datetime.datetime.utcnow()
        
        db.session.commit()
        return jsonify({
            "success": True,
            "message": "Answer saved successfully."
        }), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error saving answer for attempt {attempt_id}: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "SAVE_ANSWER_FAILED",
            "message": "An error occurred while saving the response."
        }), 500

@attempts_bp.route("/attempts/<int:attempt_id>/submit", methods=["POST"])
@token_required
def submit_exam(attempt_id):
    student = request.current_user
    data = request.get_json() or {}
    session_token = data.get("session_token")
    submission_reason = data.get("submission_reason", "MANUAL")

    if not session_token:
        return jsonify({
            "success": False,
            "error_code": "TOKEN_REQUIRED",
            "message": "Session token is required to submit."
        }), 400

    attempt = ExamAttempt.query.get(attempt_id)
    if not attempt:
        return jsonify({
            "success": False,
            "error_code": "ATTEMPT_NOT_FOUND",
            "message": "Attempt not found."
        }), 404

    if attempt.student_id != student.id and student.role != "admin":
        return jsonify({
            "success": False,
            "error_code": "UNAUTHORIZED_ATTEMPT",
            "message": "You do not have permission to submit this attempt."
        }), 403

    # Idempotent: If attempt was ALREADY submitted or auto-submitted, return success 200!
    if attempt.status in ["SUBMITTED", "AUTO_SUBMITTED"]:
        return jsonify({
            "success": True,
            "status": attempt.status,
            "message": "Examination submitted successfully."
        }), 200

    # Verify session token matches
    if attempt.session_token != session_token and student.role != "admin":
        return jsonify({
            "success": False,
            "error_code": "INVALID_SESSION_TOKEN",
            "message": "Session credentials invalid."
        }), 403

    # Check if attempt was cancelled for malpractice
    if attempt.status == "MALPRACTICE_CANCELLED":
        return jsonify({
            "success": False,
            "error_code": "MALPRACTICE_CANCELLED",
            "message": "This attempt was terminated due to policy violations."
        }), 403

    try:
        now = datetime.datetime.utcnow()
        max_duration = datetime.timedelta(minutes=attempt.exam.duration_minutes)
        is_time_up = (attempt.started_at is not None and (now - attempt.started_at) >= max_duration) or submission_reason == "TIME_COMPLETED" or attempt.status == "EXPIRED"

        if is_time_up:
            target_status = "AUTO_SUBMITTED"
            action = "EXAM_AUTO_SUBMITTED"
            message = "Time completed. Your exam has been automatically submitted successfully."
        else:
            target_status = "SUBMITTED"
            action = "EXAM_SUBMITTED"
            message = "Examination submitted successfully."

        attempt.status = target_status
        if not attempt.ended_at:
            attempt.ended_at = now
        db.session.commit()

        # Log audit trail
        audit = AuditLog(
            user_id=student.id,
            action=action,
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent")
        )
        audit.details = {
            "attempt_id": attempt.id,
            "exam_id": attempt.exam_id,
            "submission_reason": submission_reason,
            "status": target_status
        }
        db.session.add(audit)
        db.session.commit()

        # Perform server-side evaluation immediately from saved answers
        EvaluationService.evaluate_attempt(attempt.id)

        return jsonify({
            "success": True,
            "status": target_status,
            "message": message
        }), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error submitting exam attempt {attempt_id}: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "SUBMISSION_FAILED",
            "message": "An error occurred while submitting your examination."
        }), 500


@attempts_bp.route("/attempts/<int:attempt_id>/status", methods=["GET"])
@token_required
def get_attempt_status(attempt_id):
    student = request.current_user
    attempt = ExamAttempt.query.get(attempt_id)

    if not attempt:
        return jsonify({
            "success": False,
            "error_code": "ATTEMPT_NOT_FOUND",
            "message": "Attempt not found."
        }), 404

    if attempt.student_id != student.id and student.role != "admin":
        return jsonify({
            "success": False,
            "error_code": "UNAUTHORIZED_ACCESS",
            "message": "You do not have permission to view this attempt."
        }), 403

    now = datetime.datetime.utcnow()
    duration_mins = attempt.exam.duration_minutes if (attempt.exam and attempt.exam.duration_minutes and attempt.exam.duration_minutes > 0) else 60
    duration_seconds = duration_mins * 60
    max_duration = datetime.timedelta(seconds=duration_seconds)
    grace_period = datetime.timedelta(seconds=attempt.exam.security_config.network_grace_period if attempt.exam.security_config else 30)

    if not attempt.started_at:
        attempt.started_at = now
        db.session.commit()

    time_remaining = duration_seconds
    deadline_dt = attempt.started_at + max_duration
    deadline = deadline_dt.isoformat() + "Z"

    if attempt.status == "IN_PROGRESS":
        time_elapsed = now - attempt.started_at
        if time_elapsed > (max_duration + grace_period) and time_elapsed.total_seconds() > 60:
            # Auto-submit if deadline and grace period have fully passed and at least 60s elapsed
            attempt.status = "AUTO_SUBMITTED"
            attempt.ended_at = deadline_dt
            db.session.commit()
            EvaluationService.evaluate_attempt(attempt_id)
            time_remaining = 0
        else:
            remaining_sec = (deadline_dt - now).total_seconds()
            time_remaining = max(1, int(remaining_sec))
    elif attempt.status in ["SUBMITTED", "AUTO_SUBMITTED", "EXPIRED", "MALPRACTICE_CANCELLED"]:
        time_remaining = 0

    return jsonify({
        "success": True,
        "attempt_id": attempt.id,
        "status": attempt.status,
        "exam_id": attempt.exam_id,
        "exam_title": attempt.exam.title,
        "duration_seconds": duration_seconds,
        "time_remaining_seconds": time_remaining,
        "deadline": deadline,
        "started_at": (attempt.started_at.isoformat() + "Z") if attempt.started_at else None,
        "ended_at": (attempt.ended_at.isoformat() + "Z") if attempt.ended_at else None,
        "server_time": now.isoformat() + "Z"
    }), 200
