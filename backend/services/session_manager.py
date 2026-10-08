import datetime
import secrets
from backend.models import db, ExamAttempt, Exam
from backend.utils.logger import get_logger

logger = get_logger()

class SessionManager:
    @staticmethod
    def get_active_attempt(student_id, exam_id):
        """Retrieves any active/in-progress attempt for this student and exam."""
        return ExamAttempt.query.filter(
            ExamAttempt.student_id == student_id,
            ExamAttempt.exam_id == exam_id,
            ExamAttempt.status == "IN_PROGRESS"
        ).first()

    @staticmethod
    def has_any_active_attempt(student_id):
        """Checks if a student has ANY in-progress attempt across any exam."""
        return ExamAttempt.query.filter(
            ExamAttempt.student_id == student_id,
            ExamAttempt.status == "IN_PROGRESS"
        ).first() is not None

    @classmethod
    def start_session(cls, student_id, exam_id):
        """Starts a new exam session for a student."""
        exam = Exam.query.filter_by(id=exam_id, is_deleted=False).first()
        if not exam or not exam.is_active:
            raise ValueError("Exam not found or inactive.")

        # Enforce single attempt per exam rule
        existing = ExamAttempt.query.filter_by(student_id=student_id, exam_id=exam_id).first()
        if existing:
            raise PermissionError("EXAM_ALREADY_ATTEMPTED")

        # Enforce course match
        from backend.models import ExamAccess, User
        student = User.query.get(student_id)
        if student:
            if not exam.is_accessible_by(student.course):
                raise PermissionError("EXAM_COURSE_MISMATCH")

        # Enforce exam access approval rule
        access = ExamAccess.query.filter_by(student_id=student_id, exam_id=exam_id).first()
        if not access or not access.approved:
            if student and student.registration_status == "APPROVED":
                if not access:
                    access = ExamAccess(student_id=student_id, exam_id=exam_id, approved=True)
                    db.session.add(access)
                    db.session.commit()
                else:
                    access.approved = True
                    db.session.commit()
            else:
                raise PermissionError("EXAM_ACCESS_RESTRICTED")

        # Enforce single active session rule
        if cls.has_any_active_attempt(student_id):
            raise PermissionError("STUDENT_HAS_ACTIVE_ATTEMPT")

        # Generate a secure session token
        session_token = secrets.token_hex(32)
        
        now = datetime.datetime.utcnow()
        attempt = ExamAttempt(
            student_id=student_id,
            exam_id=exam_id,
            status="IN_PROGRESS",
            started_at=now,
            last_heartbeat=now,
            session_token=session_token
        )
        db.session.add(attempt)
        db.session.commit()
        
        logger.info(f"Started attempt session {attempt.id} for student {student_id} on exam {exam_id}")
        return attempt

    @staticmethod
    def verify_session(attempt_id, student_id, token):
        """Verifies if the attempt ID and session token are valid and matching."""
        attempt = ExamAttempt.query.get(attempt_id)
        if not attempt:
            return False, "ATTEMPT_NOT_FOUND"
        if attempt.student_id != student_id:
            return False, "UNAUTHORIZED_ATTEMPT"
        if attempt.session_token != token:
            return False, "INVALID_SESSION_TOKEN"
        if attempt.status != "IN_PROGRESS":
            return False, f"EXAM_ALREADY_{attempt.status.upper()}"
            
        # Check if duration exceeded (server-side timer enforcement)
        now = datetime.datetime.utcnow()
        time_elapsed = now - attempt.started_at
        max_duration = datetime.timedelta(minutes=attempt.exam.duration_minutes)
        
        # Add small grace period for network delays (e.g. 30 seconds)
        grace_period = datetime.timedelta(seconds=attempt.exam.security_config.network_grace_period if attempt.exam.security_config else 30)
        
        if time_elapsed > (max_duration + grace_period):
            attempt.status = "SUBMITTED"
            attempt.ended_at = now
            db.session.commit()
            try:
                from backend.services.evaluation import EvaluationService
                EvaluationService.evaluate_attempt(attempt.id)
            except Exception as e:
                logger.error(f"Error evaluating auto-submitted attempt {attempt.id}: {str(e)}")
            return False, "SESSION_EXPIRED"

        return True, attempt

    @staticmethod
    def get_remaining_time(attempt):
        """Calculates remaining seconds for an attempt on the server side."""
        now = datetime.datetime.utcnow()
        time_elapsed = now - attempt.started_at
        max_duration = datetime.timedelta(minutes=attempt.exam.duration_minutes)
        remaining = max_duration - time_elapsed
        return max(0, int(remaining.total_seconds()))
