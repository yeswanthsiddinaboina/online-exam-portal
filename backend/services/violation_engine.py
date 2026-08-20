import datetime
from backend.models import db, ViolationLog, ExamAttempt
from backend.utils.logger import get_logger

logger = get_logger()


class ViolationEngine:
    @staticmethod
    def _get_warning_summary(attempt_id):
        mobile_count = db.session.query(db.func.sum(ViolationLog.count_incremented)).filter(
            ViolationLog.attempt_id == attempt_id,
            ViolationLog.event_type == "PHONE_DETECTED",
            ViolationLog.severity == 2
        ).scalar() or 0

        face_count = db.session.query(db.func.sum(ViolationLog.count_incremented)).filter(
            ViolationLog.attempt_id == attempt_id,
            ViolationLog.event_type.in_(["HEAD_TURN", "MULTIPLE_PERSON", "FACE_ABSENT", "FACE_MISMATCH"]),
            ViolationLog.severity == 2
        ).scalar() or 0

        tab_count = db.session.query(db.func.sum(ViolationLog.count_incremented)).filter(
            ViolationLog.attempt_id == attempt_id,
            ViolationLog.event_type.in_(["TAB_SWITCH", "WINDOW_HIDDEN"]),
            ViolationLog.severity == 2
        ).scalar() or 0

        total_warning_count = db.session.query(db.func.sum(ViolationLog.count_incremented)).filter(
            ViolationLog.attempt_id == attempt_id,
            ViolationLog.severity == 2
        ).scalar() or 0

        latest_warning = ViolationLog.query.filter_by(attempt_id=attempt_id, severity=2).order_by(ViolationLog.timestamp.desc()).first()

        return {
            "mobile_count": int(mobile_count),
            "face_count": int(face_count),
            "tab_count": int(tab_count),
            "total_warning_count": int(total_warning_count),
            "latest_warning": latest_warning
        }

    @staticmethod
    def process_event(attempt_id, event_type, confidence):
        """Processes proctoring alerts, handles thresholds, deduplication, and policy actions."""
        attempt = ExamAttempt.query.get(attempt_id)
        if not attempt:
            logger.error(f"Attempt {attempt_id} not found in ViolationEngine.")
            return {"action": "LOG", "message": "Attempt session not found."}

        if attempt.status != "IN_PROGRESS":
            return {"action": "LOG", "message": f"Attempt is already {attempt.status}."}

        config = attempt.exam.security_config
        if not config:
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

        if event_type == "PHONE_DETECTED" and confidence < config.phone_confidence:
            return {"action": "LOG", "message": "Below phone confidence threshold."}
        if event_type == "MULTIPLE_PERSON" and confidence < config.person_confidence:
            return {"action": "LOG", "message": "Below person confidence threshold."}
        if event_type in ["HEAD_TURN", "FACE_ABSENT", "FACE_MISMATCH"] and confidence < config.face_confidence:
            return {"action": "LOG", "message": "Below face confidence threshold."}

        now = datetime.datetime.utcnow()
        last_log = ViolationLog.query.filter_by(
            attempt_id=attempt_id,
            event_type=event_type
        ).order_by(ViolationLog.timestamp.desc()).first()

        if last_log:
            elapsed = (now - last_log.timestamp).total_seconds()
            if elapsed < config.cooldown_seconds:
                logger.info(f"Deduplicated event {event_type} for attempt {attempt_id} (elapsed: {elapsed:.1f}s)")
                return {
                    "action": last_log.action_taken,
                    "violation_count": ViolationEngine.get_violation_count(attempt_id, event_type),
                    "message": "Duplicate event within cooldown. Action repeated."
                }

        warning_summary = ViolationEngine._get_warning_summary(attempt_id)
        mobile_count = warning_summary["mobile_count"] + (1 if event_type == "PHONE_DETECTED" else 0)
        face_count = warning_summary["face_count"] + (1 if event_type in ["HEAD_TURN", "MULTIPLE_PERSON", "FACE_ABSENT", "FACE_MISMATCH"] else 0)
        tab_count = warning_summary["tab_count"] + (1 if event_type in ["TAB_SWITCH", "WINDOW_HIDDEN"] else 0)
        total_warning_count = warning_summary["total_warning_count"] + 1

        if event_type in ["TAB_SWITCH", "WINDOW_HIDDEN"]:
            if tab_count >= 2:
                severity = 3
                action_taken = "TERMINATE"
                message = "Your examination has been terminated because the tab-switch violation threshold was exceeded."
                attempt.status = "MALPRACTICE_CANCELLED"
                attempt.ended_at = now
            else:
                severity = 2
                action_taken = "WARNING"
                message = "Warning: A tab or window change was detected. The system is automatically continuing analysis."
        elif mobile_count >= 3 or face_count >= 4 or total_warning_count > 5:
            severity = 3
            action_taken = "TERMINATE"
            message = "Your examination has been terminated because the warning policy threshold was exceeded."
            attempt.status = "MALPRACTICE_CANCELLED"
            attempt.ended_at = now
        elif warning_summary["latest_warning"] and (now - warning_summary["latest_warning"].timestamp).total_seconds() >= 120:
            severity = 3
            action_taken = "TERMINATE"
            message = "Your examination has been automatically terminated because the warning was not resolved within 2 minutes."
            attempt.status = "MALPRACTICE_CANCELLED"
            attempt.ended_at = now
        elif mobile_count >= 2 or face_count >= 3 or total_warning_count >= 5:
            severity = 2
            action_taken = "WARNING"
            message = "Warning: Maximum permitted warning limit reached. The system is auto-processing this alert and continuing analysis."
        else:
            severity = 2
            action_taken = "WARNING"
            message = "Warning: Examination policy violation detected. The system is automatically reviewing this alert and continuing analysis."

        current_count = ViolationEngine.get_violation_count(attempt_id, event_type) + 1
        limit = 5
        if event_type == "HEAD_TURN":
            limit = config.head_turn_limit
        elif event_type in ["TAB_SWITCH", "WINDOW_HIDDEN"]:
            limit = config.tab_switch_limit
        elif event_type == "MULTIPLE_PERSON":
            limit = config.multiple_person_limit
        elif event_type == "PHONE_DETECTED":
            limit = config.mobile_limit
        elif event_type == "FULLSCREEN_EXIT":
            limit = config.fullscreen_exit_limit

        try:
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

            logger.info(f"Violation logged: Attempt {attempt_id}, Event: {event_type}, Count: {current_count}/{limit}, Action: {action_taken}, Warnings={total_warning_count}")

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
