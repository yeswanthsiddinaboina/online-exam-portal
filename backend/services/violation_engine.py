import datetime
from backend.models import db, ViolationLog, ExamAttempt
from backend.utils.logger import get_logger

logger = get_logger()


# ==============================================================================
# TEMPORARY CONFIGURATION OVERRIDES (FOR TOMORROW'S EXAM ONLY)
# To undo after tomorrow's exam, set flags to False.
# ==============================================================================
DISABLE_FACE_MISMATCH = True
DISABLE_EXAM_TERMINATION = True
DISABLE_MULTIPLE_PERSON = True
# ==============================================================================


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

        fullscreen_count = db.session.query(db.func.sum(ViolationLog.count_incremented)).filter(
            ViolationLog.attempt_id == attempt_id,
            ViolationLog.event_type == "FULLSCREEN_EXIT",
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
            "fullscreen_count": int(fullscreen_count),
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

        # --- TEMPORARY OVERRIDE FOR TOMORROW'S EXAM: BYPASS FACE MISMATCH & MULTIPLE PERSON ---
        if DISABLE_FACE_MISMATCH and event_type == "FACE_MISMATCH":
            logger.info(f"Face mismatch check bypassed for attempt {attempt_id} (temporary exam mode).")
            return {"action": "LOG", "message": "Face mismatch check is temporarily disabled."}

        if DISABLE_MULTIPLE_PERSON and event_type == "MULTIPLE_PERSON":
            logger.info(f"Multiple person check bypassed for attempt {attempt_id} (temporary exam mode).")
            return {"action": "LOG", "message": "Multiple person check is temporarily disabled."}

        config = attempt.exam.security_config
        if not config:
            class DefaultConfig:
                head_turn_limit = 5
                tab_switch_limit = 3
                multiple_person_limit = 3
                mobile_limit = 2
                fullscreen_exit_limit = 3
                cooldown_seconds = 2
                phone_confidence = 0.25
                person_confidence = 0.25
                face_confidence = 0.35
            config = DefaultConfig()

        # Responsive thresholds for high-security proctoring
        effective_phone_conf = min(getattr(config, 'phone_confidence', 0.7), 0.25)
        effective_person_conf = min(getattr(config, 'person_confidence', 0.6), 0.25)
        effective_face_conf = min(getattr(config, 'face_confidence', 0.5), 0.35)

        if event_type == "PHONE_DETECTED" and confidence < effective_phone_conf:
            return {"action": "LOG", "message": "Below phone confidence threshold."}
        if event_type == "MULTIPLE_PERSON" and confidence < effective_person_conf:
            return {"action": "LOG", "message": "Below person confidence threshold."}
        if event_type in ["HEAD_TURN", "FACE_ABSENT", "FACE_MISMATCH"] and confidence < effective_face_conf:
            return {"action": "LOG", "message": "Below face confidence threshold."}

        now = datetime.datetime.utcnow()
        if event_type in ["TAB_SWITCH", "WINDOW_HIDDEN"]:
            last_log = ViolationLog.query.filter(
                ViolationLog.attempt_id == attempt_id,
                ViolationLog.event_type.in_(["TAB_SWITCH", "WINDOW_HIDDEN"])
            ).order_by(ViolationLog.timestamp.desc()).first()
        else:
            last_log = ViolationLog.query.filter_by(
                attempt_id=attempt_id,
                event_type=event_type
            ).order_by(ViolationLog.timestamp.desc()).first()

        if last_log:
            elapsed = (now - last_log.timestamp).total_seconds()
            configured_cooldown = getattr(config, 'cooldown_seconds', 2)
            if event_type in ["PHONE_DETECTED", "MULTIPLE_PERSON"]:
                effective_cooldown = min(configured_cooldown, 3) if configured_cooldown > 0 else 0
            elif event_type in ["TAB_SWITCH", "WINDOW_HIDDEN"]:
                effective_cooldown = min(configured_cooldown, 3) if configured_cooldown > 0 else 0
            else:
                effective_cooldown = configured_cooldown

            if elapsed < effective_cooldown:
                logger.info(f"Deduplicated event {event_type} for attempt {attempt_id} (elapsed: {elapsed:.1f}s)")
                dup_count = db.session.query(db.func.sum(ViolationLog.count_incremented)).filter(
                    ViolationLog.attempt_id == attempt_id,
                    ViolationLog.event_type.in_(["TAB_SWITCH", "WINDOW_HIDDEN"]) if event_type in ["TAB_SWITCH", "WINDOW_HIDDEN"] else ViolationLog.event_type == event_type
                ).scalar() or 0
                return {
                    "action": last_log.action_taken,
                    "violation_count": int(dup_count),
                    "message": "Duplicate event within cooldown. Action repeated."
                }

        warning_summary = ViolationEngine._get_warning_summary(attempt_id)
        mobile_count = warning_summary["mobile_count"] + (1 if event_type == "PHONE_DETECTED" else 0)
        face_count = warning_summary["face_count"] + (1 if event_type in ["HEAD_TURN", "MULTIPLE_PERSON", "FACE_ABSENT", "FACE_MISMATCH"] else 0)
        tab_count = warning_summary["tab_count"] + (1 if event_type in ["TAB_SWITCH", "WINDOW_HIDDEN"] else 0)
        fullscreen_count = warning_summary["fullscreen_count"] + (1 if event_type == "FULLSCREEN_EXIT" else 0)
        total_warning_count = warning_summary["total_warning_count"] + 1

        mismatch_count = ViolationEngine.get_violation_count(attempt_id, "FACE_MISMATCH") + (1 if event_type == "FACE_MISMATCH" else 0)
        multiple_face_count = ViolationEngine.get_violation_count(attempt_id, "MULTIPLE_PERSON") + (1 if event_type == "MULTIPLE_PERSON" else 0)

        tab_limit = getattr(config, 'tab_switch_limit', 3)
        fullscreen_limit = getattr(config, 'fullscreen_exit_limit', 3)
        mobile_limit = getattr(config, 'mobile_limit', 2)
        multiple_person_limit = getattr(config, 'multiple_person_limit', 3)
        head_turn_limit = getattr(config, 'head_turn_limit', 5)

        if not DISABLE_FACE_MISMATCH and event_type == "FACE_MISMATCH" and mismatch_count >= 2:
            if not DISABLE_EXAM_TERMINATION:
                severity = 3
                action_taken = "TERMINATE"
                message = "Your examination has been terminated: Candidate identity mismatch detected. The person writing the exam does not match the registered candidate."
                attempt.status = "MALPRACTICE_CANCELLED"
                attempt.ended_at = now
            else:
                severity = 2
                action_taken = "WARNING"
                message = f"Security Warning ({mismatch_count}/2): Candidate face mismatch detected. Infraction recorded for proctor review."
        elif not DISABLE_MULTIPLE_PERSON and event_type == "MULTIPLE_PERSON" and multiple_face_count >= multiple_person_limit:
            if not DISABLE_EXAM_TERMINATION:
                severity = 3
                action_taken = "TERMINATE"
                message = f"Your examination has been terminated: Multiple people were detected in front of the camera ({multiple_face_count}/{multiple_person_limit})."
                attempt.status = "MALPRACTICE_CANCELLED"
                attempt.ended_at = now
            else:
                severity = 2
                action_taken = "WARNING"
                message = f"Security Warning ({multiple_face_count}/{multiple_person_limit}): Multiple people detected! Permitted limit reached. Infraction recorded for proctor review."
        elif event_type in ["TAB_SWITCH", "WINDOW_HIDDEN"] and tab_count >= tab_limit:
            if not DISABLE_EXAM_TERMINATION:
                severity = 3
                action_taken = "TERMINATE"
                message = f"Your examination has been terminated: Maximum permitted tab switch limit of {tab_limit} was reached."
                attempt.status = "MALPRACTICE_CANCELLED"
                attempt.ended_at = now
            else:
                severity = 2
                action_taken = "WARNING"
                message = f"Security Warning ({tab_count}/{tab_limit}): Tab switch detected! Permitted limit reached. Infraction recorded for proctor review."
        elif event_type == "FULLSCREEN_EXIT" and fullscreen_count >= fullscreen_limit:
            if not DISABLE_EXAM_TERMINATION:
                severity = 3
                action_taken = "TERMINATE"
                message = f"Your examination has been terminated: Fullscreen mode was exited {fullscreen_count} times, exceeding the permitted limit of {fullscreen_limit}."
                attempt.status = "MALPRACTICE_CANCELLED"
                attempt.ended_at = now
            else:
                severity = 2
                action_taken = "WARNING"
                message = f"Security Warning ({fullscreen_count}/{fullscreen_limit}): Fullscreen mode exited! Permitted limit reached. Infraction recorded for proctor review."
        elif event_type == "PHONE_DETECTED" and mobile_count > mobile_limit:
            if not DISABLE_EXAM_TERMINATION:
                severity = 3
                action_taken = "TERMINATE"
                message = f"Your examination has been terminated: Mobile phone detection limit ({mobile_limit} warnings) was exceeded."
                attempt.status = "MALPRACTICE_CANCELLED"
                attempt.ended_at = now
            else:
                severity = 2
                action_taken = "WARNING"
                message = f"Security Warning ({mobile_count}/{mobile_limit}): Mobile phone detected! Permitted limit reached. Infraction recorded for proctor review."
        elif event_type in ["HEAD_TURN", "FACE_ABSENT"] and face_count > head_turn_limit:
            if not DISABLE_EXAM_TERMINATION:
                severity = 3
                action_taken = "TERMINATE"
                message = f"Your examination has been terminated: Head turn/absence policy threshold ({head_turn_limit} warnings) was exceeded."
                attempt.status = "MALPRACTICE_CANCELLED"
                attempt.ended_at = now
            else:
                severity = 2
                action_taken = "WARNING"
                if event_type == "HEAD_TURN":
                    message = "Head turn detected! Permitted limit reached. Infraction recorded for proctor review."
                else:
                    message = f"Security Warning ({face_count}/{head_turn_limit}): Face absent detected! Permitted limit reached. Infraction recorded for proctor review."
        else:
            severity = 2
            action_taken = "WARNING"
            if event_type == "FACE_MISMATCH":
                message = "Critical Security Alert: Candidate face mismatch detected! The face writing this exam does not match the candidate verified at check-in."
            elif event_type == "MULTIPLE_PERSON":
                remaining = max(0, multiple_person_limit - multiple_face_count)
                if not DISABLE_EXAM_TERMINATION and multiple_face_count == multiple_person_limit - 1:
                    message = f"Security Warning ({multiple_face_count}/{multiple_person_limit}): Multiple faces detected! FINAL WARNING: Only the registered candidate must be visible in the camera frame. Any further detection will terminate your exam immediately!"
                else:
                    message = f"Security Warning ({multiple_face_count}/{multiple_person_limit}): Multiple faces detected! Only the registered candidate must be visible in the camera frame ({remaining} warning(s) remaining)."
            elif event_type in ["TAB_SWITCH", "WINDOW_HIDDEN"]:
                remaining = max(0, tab_limit - tab_count)
                if not DISABLE_EXAM_TERMINATION and tab_count == tab_limit - 1:
                    message = f"Security Warning ({tab_count}/{tab_limit}): Tab switch detected! FINAL WARNING: You have reached {tab_count} of {tab_limit} permitted switches. Any further tab switch will terminate your exam immediately!"
                else:
                    message = f"Security Warning ({tab_count}/{tab_limit}): Tab switch detected! Navigating away from the exam tab is prohibited ({remaining} warning(s) remaining)."
            elif event_type == "FULLSCREEN_EXIT":
                remaining = max(0, fullscreen_limit - fullscreen_count)
                if not DISABLE_EXAM_TERMINATION and fullscreen_count == fullscreen_limit - 1:
                    message = f"Security Warning ({fullscreen_count}/{fullscreen_limit}): Fullscreen exited! FINAL WARNING: Any further exit will terminate your exam immediately!"
                else:
                    message = f"Security Warning ({fullscreen_count}/{fullscreen_limit}): Fullscreen exited! Please remain in fullscreen mode ({remaining} warning(s) remaining)."
            elif event_type == "PHONE_DETECTED":
                remaining = max(0, mobile_limit - mobile_count)
                if not DISABLE_EXAM_TERMINATION and mobile_count == mobile_limit:
                    message = f"Security Warning ({mobile_count}/{mobile_limit}): Mobile phone detected! FINAL WARNING: Maximum permitted warnings reached. Any further phone detection will terminate your exam immediately!"
                else:
                    message = f"Security Warning ({mobile_count}/{mobile_limit}): Mobile phone or unauthorized electronic device detected in camera frame ({remaining} warning(s) remaining)."
            elif event_type in ["HEAD_TURN", "FACE_ABSENT"]:
                if event_type == "HEAD_TURN":
                    message = "Head turn detected! Please face the screen and remain focused on your examination."
                else:
                    remaining = max(0, head_turn_limit - face_count)
                    if not DISABLE_EXAM_TERMINATION and face_count == head_turn_limit:
                        message = f"Security Warning ({face_count}/{head_turn_limit}): Face absent! FINAL WARNING: Maximum permitted warnings reached. Any further infractions will terminate your exam immediately!"
                    else:
                        message = f"Security Warning ({face_count}/{head_turn_limit}): Face absent detected! Please face the camera and remain focused on your examination screen ({remaining} warning(s) remaining)."
            else:
                message = "Warning: Examination policy violation detected. Please adhere to the exam guidelines."

        if event_type in ["TAB_SWITCH", "WINDOW_HIDDEN"]:
            current_count = tab_count
            limit = tab_limit
        elif event_type == "FULLSCREEN_EXIT":
            current_count = fullscreen_count
            limit = fullscreen_limit
        elif event_type == "MULTIPLE_PERSON":
            current_count = multiple_face_count
            limit = multiple_person_limit
        elif event_type == "PHONE_DETECTED":
            current_count = mobile_count
            limit = mobile_limit
        elif event_type in ["HEAD_TURN", "FACE_ABSENT"]:
            current_count = face_count
            limit = head_turn_limit
        else:
            current_count = ViolationEngine.get_violation_count(attempt_id, event_type) + 1
            limit = getattr(config, 'head_turn_limit', 5)

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

            # If examination was terminated due to malpractice, evaluate candidate score immediately
            if action_taken == "TERMINATE":
                try:
                    from backend.services.evaluation import EvaluationService
                    EvaluationService.evaluate_attempt(attempt_id)
                    logger.info(f"Terminated attempt {attempt_id} evaluated successfully.")
                except Exception as eval_err:
                    logger.error(f"Error evaluating terminated attempt {attempt_id}: {str(eval_err)}")

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
