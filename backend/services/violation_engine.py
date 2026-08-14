import datetime
from backend.models import db, ViolationLog, ExamAttempt
from backend.utils.logger import get_logger

logger = get_logger()

class ViolationEngine:
    @staticmethod
    def process_event(attempt_id, event_type, confidence):
        """Processes proctoring alerts, handles thresholds, deduplication, and policy actions."""
        attempt = ExamAttempt.query.get(attempt_id)
        if not attempt:
            logger.error(f"Attempt {attempt_id} not found in ViolationEngine.")
            return {"action": "LOG", "message": "Attempt session not found."}

        # Check if the attempt is active
        if attempt.status != "IN_PROGRESS":
            return {"action": "LOG", "message": f"Attempt is already {attempt.status}."}

        # Fetch exam security configuration
        config = attempt.exam.security_config
        if not config:
            # Fallback default values
            class DefaultConfig:
                head_turn_limit = 5
                tab_switch_limit = 3
                multiple_person_limit = 3
                mobile_limit = 2
                fullscreen_exit_limit = 3
                cooldown_seconds = 2
                phone_confidence = 0.7
                person_confidence = 0.6
                face_confidence = 0.5
            config = DefaultConfig()

        # 1. Confidence validation based on event types
        if event_type == "PHONE_DETECTED" and confidence < config.phone_confidence:
            return {"action": "LOG", "message": "Below phone confidence threshold."}
        if event_type == "MULTIPLE_PERSON" and confidence < config.person_confidence:
            return {"action": "LOG", "message": "Below person confidence threshold."}
        if event_type in ["HEAD_TURN", "FACE_ABSENT", "FACE_MISMATCH"] and confidence < config.face_confidence:
            return {"action": "LOG", "message": "Below face confidence threshold."}

        # 2. Cooldown check / Deduplication
        # Query last violation log of this type to see if it occurred within cooldown window
        now = datetime.datetime.utcnow()
        last_log = ViolationLog.query.filter_by(
            attempt_id=attempt_id,
            event_type=event_type
        ).order_by(ViolationLog.timestamp.desc()).first()

        if last_log:
            elapsed = (now - last_log.timestamp).total_seconds()
            if elapsed < config.cooldown_seconds:
                # Deduplicated: Log but do not increment count, warn again using same action
                logger.info(f"Deduplicated event {event_type} for attempt {attempt_id} (elapsed: {elapsed:.1f}s)")
                return {
                    "action": last_log.action_taken,
                    "violation_count": ViolationEngine.get_violation_count(attempt_id, event_type),
                    "message": "Duplicate event within cooldown. Action repeated."
                }

        # 3. Calculate current count and define specific policy boundaries
        current_count = ViolationEngine.get_violation_count(attempt_id, event_type) + 1
        limit = 5 # default

        # Assign limits according to type
        if event_type == "HEAD_TURN":
            limit = config.head_turn_limit
        elif event_type == "TAB_SWITCH" or event_type == "WINDOW_HIDDEN":
            limit = config.tab_switch_limit
        elif event_type == "MULTIPLE_PERSON":
            limit = config.multiple_person_limit
        elif event_type == "PHONE_DETECTED":
            limit = config.mobile_limit
        elif event_type == "FULLSCREEN_EXIT":
            limit = config.fullscreen_exit_limit

        severity = 1 # 1: log, 2: warn, 3: terminate
        action_taken = "LOG"
        message = "Activity logged."

        if event_type in ["TAB_SWITCH", "WINDOW_HIDDEN"]:
            severity = 3
            action_taken = "TERMINATE"
            message = "Your examination has been terminated immediately due to tab switching or leaving the exam screen."
            attempt.status = "MALPRACTICE_CANCELLED"
            attempt.ended_at = now
        elif current_count >= limit:
            severity = 3
            action_taken = "TERMINATE"
            message = "Your examination has been terminated because the permitted violation threshold was exceeded."
            # Set attempt status to MALPRACTICE_CANCELLED on server
            attempt.status = "MALPRACTICE_CANCELLED"
            attempt.ended_at = now
        elif current_count == limit - 1:
            severity = 2
            action_taken = "WARNING"
            message = "FINAL WARNING: Examination policy violation detected. Please remain focused on the examination environment."
        else:
            severity = 2
            action_taken = "WARNING"
            message = f"Warning: Examination policy violation detected. Please remain focused on the examination environment. (Violation {current_count}/{limit})"

        try:
            # Create ViolationLog entry
            violation = ViolationLog(
                attempt_id=attempt_id,
                event_type=event_type,
                confidence=confidence,
                timestamp=now,
                severity=severity,
                count_incremented=1,
                action_taken=action_taken
            )
            db.session.add(violation)
            db.session.commit()
            
            logger.info(f"Violation logged: Attempt {attempt_id}, Event: {event_type}, Count: {current_count}/{limit}, Action: {action_taken}")
            
            return {
                "action": action_taken,
                "violation_count": current_count,
                "violation_log_id": violation.id,
                "message": message
            }
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error logging violation in database: {str(e)}")
            return {"action": "LOG", "message": "Failed to log violation state."}

    @staticmethod
    def get_violation_count(attempt_id, event_type):
        """Sums the unique increments for a specific event type on this attempt."""
        return db.session.query(db.func.sum(ViolationLog.count_incremented)).filter(
            ViolationLog.attempt_id == attempt_id,
            ViolationLog.event_type == event_type
        ).scalar() or 0
