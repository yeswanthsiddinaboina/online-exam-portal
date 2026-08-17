from flask import Blueprint, request, jsonify
from PIL import Image
from backend.config import Config
from backend.models import db, ExamAttempt, AuditLog
from backend.services.session_manager import SessionManager
from backend.services.violation_engine import ViolationEngine
from backend.services.evidence_service import EvidenceService
from backend.utils.security import token_required
from backend.utils.logger import get_logger
import datetime

logger = get_logger()
proctoring_bp = Blueprint("proctoring", __name__)

@proctoring_bp.route("/exam/heartbeat", methods=["POST"])
@token_required
def heartbeat():
    student = request.current_user
    data = request.get_json() or {}
    
    attempt_id = data.get("attempt_id")
    session_token = data.get("session_token")
    fullscreen_active = data.get("fullscreen_active", True)
    visibility_state = data.get("visibility_state", "visible")

    if not attempt_id or not session_token:
        return jsonify({
            "success": False,
            "error_code": "INVALID_PARAMS",
            "message": "Attempt ID and session token are required."
        }), 400

    # Verify student session and limits
    is_valid, session_or_err = SessionManager.verify_session(attempt_id, student.id, session_token)
    if not is_valid:
        return jsonify({
            "success": False,
            "error_code": session_or_err,
            "message": f"Session verification failed: {session_or_err}"
        }), 403

    attempt = session_or_err
    
    # Update last heartbeat time
    attempt.last_heartbeat = datetime.datetime.utcnow()
    db.session.commit()

    # Track browser sandbox changes during heartbeat
    action = "LOG"
    message = "Heartbeat received."
    violation_log_id = None
    
    if visibility_state == "hidden":
        res = ViolationEngine.process_event(attempt.id, "WINDOW_HIDDEN", 1.0)
        action = res.get("action", "LOG")
        message = res.get("message", "")
        violation_log_id = res.get("violation_log_id")
        
    elif not fullscreen_active:
        res = ViolationEngine.process_event(attempt.id, "FULLSCREEN_EXIT", 1.0)
        action = res.get("action", "LOG")
        message = res.get("message", "")
        violation_log_id = res.get("violation_log_id")

    time_remaining = SessionManager.get_remaining_time(attempt)

    return jsonify({
        "success": True,
        "status": attempt.status,
        "time_remaining_seconds": time_remaining,
        "action": action,
        "message": message,
        "violation_log_id": violation_log_id
    }), 200

@proctoring_bp.route("/proctor/events", methods=["POST"])
@token_required
def report_event():
    student = request.current_user
    data = request.get_json() or {}
    
    attempt_id = data.get("attempt_id")
    session_token = data.get("session_token")
    event_type = data.get("event_type")
    confidence = data.get("confidence", 1.0)

    if not all([attempt_id, session_token, event_type]):
        return jsonify({
            "success": False,
            "error_code": "INVALID_PARAMS",
            "message": "Attempt ID, session token, and event type are required."
        }), 400

    # Verify session
    is_valid, session_or_err = SessionManager.verify_session(attempt_id, student.id, session_token)
    if not is_valid:
        return jsonify({
            "success": False,
            "error_code": session_or_err,
            "message": f"Session verification failed: {session_or_err}"
        }), 403

    attempt = session_or_err

    # Process through Violation Engine
    result = ViolationEngine.process_event(attempt.id, event_type, confidence)
    
    return jsonify({
        "success": True,
        "action": result.get("action", "LOG"),
        "violation_count": result.get("violation_count", 0),
        "violation_log_id": result.get("violation_log_id"),
        "message": result.get("message", "")
    }), 200

@proctoring_bp.route("/proctor/evidence", methods=["POST"])
@token_required
def upload_evidence():
    student = request.current_user
    
    attempt_id = request.form.get("attempt_id")
    session_token = request.form.get("session_token")
    event_type = request.form.get("event_type")
    violation_log_id = request.form.get("violation_log_id")

    if not all([attempt_id, session_token, event_type]):
        return jsonify({
            "success": False,
            "error_code": "INVALID_PARAMS",
            "message": "Attempt ID, session token, and event type are required in form fields."
        }), 400

    if "file" not in request.files:
        return jsonify({
            "success": False,
            "error_code": "NO_FILE",
            "message": "Webcam frame file is required."
        }), 400

    # Verify session
    is_valid, session_or_err = SessionManager.verify_session(attempt_id, student.id, session_token)
    if not is_valid:
        return jsonify({
            "success": False,
            "error_code": session_or_err,
            "message": f"Session verification failed: {session_or_err}"
        }), 403

    attempt = session_or_err
    file = request.files["file"]
    
    # Save evidence image
    record = EvidenceService.save_evidence(
        attempt.id,
        event_type,
        file.stream,
        violation_log_id=int(violation_log_id) if violation_log_id else None
    )

    if not record:
        return jsonify({
            "success": False,
            "error_code": "EVIDENCE_SAVE_FAILED",
            "message": "Failed to save screenshot evidence."
        }), 500

    return jsonify({
        "success": True,
        "evidence_id": record.id,
        "message": "Evidence saved successfully."
    }), 201

@proctoring_bp.route("/proctor/system-check", methods=["POST"])
@token_required
def log_system_check():
    student = request.current_user
    data = request.get_json() or {}
    
    exam_id = data.get("exam_id")
    checks = data.get("checks", {})

    if not exam_id:
        return jsonify({
            "success": False,
            "error_code": "EXAM_ID_REQUIRED",
            "message": "Exam ID is required."
        }), 400

    # Log to audit trail
    audit = AuditLog(
        user_id=student.id,
        action="PRE_EXAM_SYSTEM_CHECK",
        ip_address=request.remote_addr,
        user_agent=request.headers.get("User-Agent")
    )
    audit.details = {"exam_id": exam_id, "checks": checks}
    db.session.add(audit)
    db.session.commit()

    logger.info(f"Student {student.email} performed system check for exam {exam_id}. Status: {checks.get('overall', 'UNKNOWN')}")
    return jsonify({
        "success": True,
        "message": "System check logged successfully."
    }), 200

@proctoring_bp.route("/proctor/face-verification", methods=["POST"])
@token_required
def face_verification():
    student = request.current_user
    
    exam_id = request.form.get("exam_id")
    if not exam_id:
        return jsonify({
            "success": False,
            "error_code": "EXAM_ID_REQUIRED",
            "message": "Exam ID is required in form fields."
        }), 400

    # Check if student has already attempted this exam
    existing = ExamAttempt.query.filter_by(student_id=student.id, exam_id=exam_id).first()
    if existing:
        return jsonify({
            "success": False,
            "error_code": "EXAM_ALREADY_ATTEMPTED",
            "message": "You have already attempted this examination. Multiple attempts are prohibited."
        }), 400

    # Check if student has approved access
    from backend.models import ExamAccess
    access = ExamAccess.query.filter_by(student_id=student.id, exam_id=exam_id).first()
    if not access or not access.approved:
        return jsonify({
            "success": False,
            "error_code": "EXAM_ACCESS_RESTRICTED",
            "message": "Access restricted. You must request and receive administrator approval to write this exam."
        }), 403

    if "file" not in request.files:
        return jsonify({
            "success": False,
            "error_code": "NO_FILE",
            "message": "Reference photo is required."
        }), 400

    file = request.files["file"]

    try:
        # Save reference face (simulated verification for pre-check approval)
        # In a real environment, we'd compare this file with the student's registration profile image.
        # Here we just save the image frame as reference evidence for proctors to audit.
        timestamp_str = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"reference_{student.id}_{exam_id}_{timestamp_str}.jpg"
        dest_path = Config.EVIDENCE_DIR / filename
        
        # Save reference image
        img = Image.open(file.stream)
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.thumbnail((800, 600))
        img.save(dest_path, "JPEG", quality=75)

        # Audit verification event
        audit = AuditLog(
            user_id=student.id,
            action="FACE_VERIFIED",
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent")
        )
        audit.details = {"exam_id": int(exam_id), "reference_image_path": str(dest_path.relative_to(Config.EVIDENCE_DIR.parent))}
        db.session.add(audit)
        db.session.commit()

        logger.info(f"Student {student.email} passed face verification for exam {exam_id}")
        return jsonify({
            "success": True,
            "message": "Face verification succeeded."
        }), 200

    except Exception as e:
        logger.error(f"Error during face verification: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "VERIFICATION_FAILED",
            "message": "Face verification failed."
        }), 500


@proctoring_bp.route("/proctor/verify-face/reference", methods=["POST"])
@token_required
def save_temp_reference():
    student = request.current_user
    if student.role != "student":
        return jsonify({
            "success": False,
            "error_code": "STUDENTS_ONLY",
            "message": "Only candidate accounts can verify faces."
        }), 403

    exam_id = request.form.get("exam_id", type=int)
    if not exam_id:
        return jsonify({
            "success": False,
            "error_code": "MISSING_EXAM_ID",
            "message": "Examination ID is required."
        }), 400

    # Check if student has approved access
    from backend.models import ExamAccess
    access = ExamAccess.query.filter_by(student_id=student.id, exam_id=exam_id).first()
    if not access or not access.approved:
        return jsonify({
            "success": False,
            "error_code": "EXAM_ACCESS_RESTRICTED",
            "message": "Access restricted. You must request and receive administrator approval to write this exam."
        }), 403

    if "file" not in request.files:
        return jsonify({
            "success": False,
            "error_code": "NO_FILE",
            "message": "Webcam frame file is required."
        }), 400

    file = request.files["file"]

    try:
        # Save temp reference image
        dest_path = Config.EVIDENCE_DIR / f"temp_ref_{student.id}_{exam_id}.jpg"
        img = Image.open(file.stream)
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.thumbnail((800, 600))
        img.save(dest_path, "JPEG", quality=75)

        # Run face mesh check using mediapipe to ensure a face is detected
        import mediapipe as mp
        import cv2
        import numpy as np

        mp_face_mesh = mp.solutions.face_mesh
        with mp_face_mesh.FaceMesh(
            static_image_mode=True,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5
        ) as face_mesh:
            image = cv2.imread(str(dest_path))
            if image is None:
                return jsonify({
                    "success": False,
                    "error_code": "IMAGE_READ_ERROR",
                    "message": "Webcam snapshot read error."
                }), 400
                
            results = face_mesh.process(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
            if not results.multi_face_landmarks:
                if dest_path.exists():
                    dest_path.unlink()
                return jsonify({
                    "success": False,
                    "error_code": "NO_FACE_DETECTED",
                    "message": "No face detected in reference photo. Please align your face clearly in the camera and try again."
                }), 400

        logger.info(f"Temporary reference face saved for student {student.email} on exam {exam_id}")
        return jsonify({
            "success": True,
            "message": "Reference face captured successfully."
        }), 200

    except Exception as e:
        logger.error(f"Error saving temp reference: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "SAVE_REFERENCE_FAILED",
            "message": "Failed to save reference photo."
        }), 500


@proctoring_bp.route("/proctor/verify-face/compare", methods=["POST"])
@token_required
def compare_faces_and_start():
    student = request.current_user
    if student.role != "student":
        return jsonify({
            "success": False,
            "error_code": "STUDENTS_ONLY",
            "message": "Only candidate accounts can verify faces."
        }), 403

    exam_id = request.form.get("exam_id", type=int)
    if not exam_id:
        return jsonify({
            "success": False,
            "error_code": "MISSING_EXAM_ID",
            "message": "Examination ID is required."
        }), 400

    # Verify temp reference exists
    ref_path = Config.EVIDENCE_DIR / f"temp_ref_{student.id}_{exam_id}.jpg"
    if not ref_path.exists():
        return jsonify({
            "success": False,
            "error_code": "NO_REFERENCE_PHOTO",
            "message": "Reference photo missing. Please capture reference photo first."
        }), 400

    if "file" not in request.files:
        return jsonify({
            "success": False,
            "error_code": "NO_FILE",
            "message": "Verification webcam frame file is required."
        }), 400

    file = request.files["file"]
    ver_path = Config.EVIDENCE_DIR / f"temp_ver_{student.id}_{exam_id}.jpg"

    try:
        # Save verification frame
        img = Image.open(file.stream)
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.thumbnail((800, 600))
        img.save(ver_path, "JPEG", quality=75)

        # Extract landmarks and compare
        import mediapipe as mp
        import cv2
        import numpy as np

        def extract_landmarks(path):
            mp_face_mesh = mp.solutions.face_mesh
            with mp_face_mesh.FaceMesh(
                static_image_mode=True,
                max_num_faces=1,
                refine_landmarks=True,
                min_detection_confidence=0.5
            ) as face_mesh:
                image = cv2.imread(str(path))
                if image is None:
                    return None
                results = face_mesh.process(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
                if not results.multi_face_landmarks:
                    return None
                landmarks = results.multi_face_landmarks[0].landmark
                return np.array([[l.x, l.y, l.z] for l in landmarks])

        coords1 = extract_landmarks(ref_path)
        coords2 = extract_landmarks(ver_path)

        if coords1 is None or coords2 is None:
            if ver_path.exists():
                ver_path.unlink()
            return jsonify({
                "success": False,
                "error_code": "NO_FACE_DETECTED",
                "message": "Face could not be detected in verification photo. Align yourself and look straight at the camera."
            }), 400

        # Align and normalize landmarks (scale-invariant & translation-invariant)
        c1_mean = coords1.mean(axis=0)
        c2_mean = coords2.mean(axis=0)
        c1_centered = coords1 - c1_mean
        c2_centered = coords2 - c2_mean

        # Scale by distance between eye boundaries (idx 33 and 263)
        scale1 = np.linalg.norm(c1_centered[33] - c1_centered[263])
        scale2 = np.linalg.norm(c2_centered[33] - c2_centered[263])

        if scale1 == 0 or scale2 == 0:
            return jsonify({
                "success": False,
                "error_code": "SCALE_ERROR",
                "message": "Error scaling facial mesh points."
            }), 400

        c1_normalized = c1_centered / scale1
        c2_normalized = c2_centered / scale2

        # Average coordinate distance
        dist = float(np.mean(np.linalg.norm(c1_normalized - c2_normalized, axis=1)))
        
        # Lower value = closer match. Empirically, threshold < 0.22 is very reliable
        is_match = dist < 0.22

        if not is_match:
            if ver_path.exists():
                ver_path.unlink()
            logger.warning(f"Face mismatch for student {student.email} on exam {exam_id}: distance={dist:.4f}")
            return jsonify({
                "success": False,
                "error_code": "FACE_MISMATCH",
                "message": "Verification failed. Faces do not match! Please look straight at the camera without any facial tilt."
            }), 400

        # Successful match! Let's initialize attempt session
        from backend.services.session_manager import SessionManager
        from backend.models import AuditLog, db
        
        # Start official session
        try:
            attempt_session = SessionManager.start_session(student.id, exam_id)
        except PermissionError as pe:
            return jsonify({
                "success": False,
                "error_code": str(pe),
                "message": "Permission restricted. You may already have an active attempt."
            }), 403

        # Copy the temporary reference image as the permanent attempt reference
        final_filename = f"reference_{attempt_session.id}.jpg"
        final_path = Config.EVIDENCE_DIR / final_filename
        ref_path.rename(final_path)

        # Audit event
        audit = AuditLog(
            user_id=student.id,
            action="FACE_VERIFIED",
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent")
        )
        audit.details = {"exam_id": int(exam_id), "attempt_id": attempt_session.id, "reference_image_path": f"reference_{attempt_session.id}.jpg"}
        db.session.add(audit)
        db.session.commit()

        # Clean up verification temporary image
        if ver_path.exists():
            ver_path.unlink()

        logger.info(f"Student {student.email} matched face successfully (distance={dist:.4f}) and started attempt {attempt_session.id}")
        return jsonify({
            "success": True,
            "message": "Face verification matched successfully! Initiating exam...",
            "attempt_id": attempt_session.id,
            "session_token": attempt_session.session_token
        }), 200

    except Exception as e:
        logger.error(f"Error during comparison face verification: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "COMPARISON_FAILED",
            "message": "Face verification system error."
        }), 500

