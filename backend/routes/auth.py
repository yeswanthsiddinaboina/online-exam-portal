from flask import Blueprint, request, jsonify
from backend.models import db, User, AuditLog
from backend.utils.security import generate_token, token_required
from backend.utils.logger import get_logger
import datetime

logger = get_logger()
auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    email = data.get("email").strip().lower() if data.get("email") else None
    password = data.get("password")
    first_name = data.get("first_name")
    last_name = data.get("last_name")
    role = data.get("role", "student") # Defaults to student

    if role == "admin":
        return jsonify({
            "success": False,
            "error_code": "ADMIN_REGISTRATION_DISABLED",
            "message": "Administrator registration is disabled on this platform."
        }), 403

    if role not in ["student"]:
        return jsonify({
            "success": False,
            "error_code": "INVALID_ROLE",
            "message": "Invalid user role specified."
        }), 400

    if not all([email, password, first_name, last_name]):
        return jsonify({
            "success": False,
            "error_code": "INVALID_INPUT",
            "message": "All fields (email, password, first_name, last_name) are required."
        }), 400

    # Check if user already exists
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        return jsonify({
            "success": False,
            "error_code": "USER_ALREADY_EXISTS",
            "message": "User with this email is already registered."
        }), 409

    raw_course = data.get("course")
    course = raw_course.strip() if isinstance(raw_course, str) and raw_course.strip() in ["Python", "Java"] else None
    if role == "student" and not course:
        course = "Python"

    try:
        user = User(
            email=email,
            first_name=first_name,
            last_name=last_name,
            role=role,
            course=course
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        # Log audit trail
        audit = AuditLog(
            user_id=user.id,
            action="USER_REGISTERED",
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent")
        )
        audit.details = {"email": email, "role": role, "course": course}
        db.session.add(audit)
        db.session.commit()

        logger.info(f"Registered user: {email} with role: {role} (Course: {course})")
        return jsonify({
            "success": True,
            "message": "User registered successfully."
        }), 201

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error during registration: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "REGISTRATION_FAILED",
            "message": "An error occurred during registration. Please try again."
        }), 500

@auth_bp.route("/register-student", methods=["POST"])
def register_student():
    data = request.get_json() or {}
    email = data.get("email").strip().lower() if data.get("email") else None
    first_name = data.get("first_name") # Candidate Name
    password = data.get("password")
    
    raw_course = data.get("course", "Python")
    course = raw_course.strip() if isinstance(raw_course, str) else "Python"
    if course not in ["Python", "Java"]:
        course = "Python"
    
    if not all([email, first_name, password]):
        return jsonify({
            "success": False,
            "error_code": "INVALID_INPUT",
            "message": "All fields (Full Name, Gmail ID, Course, and Password) are required."
        }), 400
        
    first_name = first_name.strip()
    if len(password) < 4:
        return jsonify({
            "success": False,
            "error_code": "WEAK_PASSWORD",
            "message": "Password must be at least 4 characters long."
        }), 400
    
    # Check if Email already registered
    existing_by_email = User.query.filter_by(email=email).first()
    if existing_by_email:
        if existing_by_email.registration_status == "REJECTED":
            try:
                existing_by_email.first_name = first_name
                existing_by_email.last_name = "Not Assigned"
                existing_by_email.course = course
                existing_by_email.registration_status = "PENDING"
                existing_by_email.first_login_completed = False
                existing_by_email.set_password(password)
                db.session.commit()
                logger.info(f"Rejected student re-registered: {email} (Course: {course})")
                return jsonify({
                    "success": True,
                    "message": "Student registration request submitted successfully. Please wait for administrator approval."
                }), 201
            except Exception as e:
                db.session.rollback()
                logger.error(f"Failed student re-registration: {str(e)}")
                return jsonify({
                    "success": False,
                    "error_code": "REGISTRATION_FAILED",
                    "message": "An error occurred during registration. Please try again."
                }), 500
        else:
            return jsonify({
                "success": False,
                "error_code": "EMAIL_ALREADY_EXISTS",
                "message": f"A registration request with this Email ID already exists (Status: {existing_by_email.registration_status})."
            }), 400
        
    try:
        student = User(
            email=email,
            first_name=first_name,
            last_name="Not Assigned",
            role="student",
            course=course,
            registration_status="PENDING",
            first_login_completed=False
        )
        student.set_password(password)
        db.session.add(student)
        db.session.commit()
        
        logger.info(f"Student registration request submitted: {email} (Course: {course})")
        return jsonify({
            "success": True,
            "message": "Student registration request submitted successfully. Please wait for administrator approval."
        }), 201
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed student registration: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "REGISTRATION_FAILED",
            "message": "An error occurred while submitting your registration."
        }), 500

@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    identifier = (data.get("identifier") or data.get("email") or "").strip()
    password = data.get("password")

    if not identifier:
        return jsonify({
            "success": False,
            "error_code": "IDENTIFIER_REQUIRED",
            "message": "Gmail ID or User ID is required."
        }), 400

    if not password:
        return jsonify({
            "success": False,
            "error_code": "PASSWORD_REQUIRED",
            "message": "Password is required."
        }), 400

    # Search for user by email OR last_name (User ID) case-insensitively
    user = User.query.filter(
        db.or_(
            db.func.lower(User.email) == identifier.lower(),
            db.func.lower(User.last_name) == identifier.lower()
        )
    ).first()
    
    if not user:
        return jsonify({
            "success": False,
            "error_code": "ACCOUNT_NOT_FOUND",
            "message": "No registered account found with this Gmail ID or User ID. Please register first."
        }), 404
            
    # For student accounts, verify the registration status
    if user.role == "student":
        if user.registration_status == "PENDING" or user.last_name == "Not Assigned":
            return jsonify({
                "success": False,
                "error_code": "REGISTRATION_PENDING",
                "message": "Your registration is still pending admin approval."
            }), 403
        elif user.registration_status == "REJECTED":
            return jsonify({
                "success": False,
                "error_code": "REGISTRATION_REJECTED",
                "message": "Your registration request has been rejected."
            }), 403
            
    # Verify password for both admin and student
    if not user.check_password(password):
        audit = AuditLog(
            user_id=user.id,
            action="FAILED_LOGIN_ATTEMPT",
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent")
        )
        audit.details = {"attempted_identifier": identifier}
        db.session.add(audit)
        db.session.commit()

        return jsonify({
            "success": False,
            "error_code": "INVALID_CREDENTIALS",
            "message": "Incorrect password. Please verify your password or use Reset Password."
        }), 401

    # Generate token
    token = generate_token(user.id, user.role)
    if not token:
        return jsonify({
            "success": False,
            "error_code": "TOKEN_GENERATION_FAILED",
            "message": "Failed to create authentication session."
        }), 500

    # Log successful login
    audit = AuditLog(
        user_id=user.id,
        action="USER_LOGGED_IN",
        ip_address=request.remote_addr,
        user_agent=request.headers.get("User-Agent")
    )
    db.session.add(audit)
    db.session.commit()

    logger.info(f"User logged in: {user.email} (Role: {user.role})")
    return jsonify({
        "success": True,
        "token": token,
        "role": user.role,
        "user": user.to_dict()
    }), 200

@auth_bp.route("/logout", methods=["POST"])
@token_required
def logout():
    user = request.current_user
    
    # Audit log logout
    audit = AuditLog(
        user_id=user.id,
        action="USER_LOGGED_OUT",
        ip_address=request.remote_addr,
        user_agent=request.headers.get("User-Agent")
    )
    db.session.add(audit)
    db.session.commit()
    
    logger.info(f"User logged out: {user.email}")
    return jsonify({
        "success": True,
        "message": "Logged out successfully."
    }), 200

@auth_bp.route("/complete-first-login", methods=["POST"])
@token_required
def complete_first_login():
    user = request.current_user
    try:
        user.first_login_completed = True
        db.session.commit()
        logger.info(f"First login welcome popup marked as completed for user: {user.email}")
        return jsonify({
            "success": True,
            "message": "First login popup marked as completed."
        }), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to complete first login: {str(e)}")
        return jsonify({
            "success": False,
            "message": "Internal server error."
        }), 500


@auth_bp.route("/reset-password/request", methods=["POST"])
def request_password_reset():
    from backend.models.password_reset import PasswordResetRequest
    data = request.get_json() or {}
    identifier = (data.get("identifier") or data.get("email") or "").strip()
    
    if not identifier:
        return jsonify({
            "success": False,
            "error_code": "IDENTIFIER_REQUIRED",
            "message": "Gmail ID or User ID is required."
        }), 400

    user = User.query.filter(
        db.or_(
            db.func.lower(User.email) == identifier.lower(),
            db.func.lower(User.last_name) == identifier.lower()
        )
    ).first()

    if not user or user.role != "student":
        return jsonify({
            "success": False,
            "error_code": "STUDENT_NOT_FOUND",
            "message": "No registered student account found matching this Gmail ID or User ID."
        }), 404

    # Check if there is an existing PENDING request
    pending_req = PasswordResetRequest.query.filter_by(
        user_id=user.id, status="PENDING"
    ).first()
    if pending_req:
        return jsonify({
            "success": True,
            "message": "You already have a pending password reset request. Please wait for administrator approval.",
            "status": "PENDING"
        }), 200

    # Check if there is an existing APPROVED request
    approved_req = PasswordResetRequest.query.filter_by(
        user_id=user.id, status="APPROVED"
    ).first()
    if approved_req:
        return jsonify({
            "success": True,
            "message": "Your password reset request has already been approved! You can now set your new password.",
            "status": "APPROVED"
        }), 200

    try:
        reset_req = PasswordResetRequest(
            user_id=user.id,
            status="PENDING"
        )
        db.session.add(reset_req)
        
        audit = AuditLog(
            user_id=user.id,
            action="PASSWORD_RESET_REQUESTED",
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent")
        )
        audit.details = {"identifier": identifier, "email": user.email}
        db.session.add(audit)
        db.session.commit()

        logger.info(f"Password reset requested for student: {user.email}")
        return jsonify({
            "success": True,
            "message": "Password reset request submitted successfully. Please wait for administrator approval before resetting your password.",
            "status": "PENDING"
        }), 201

    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to submit password reset request: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "RESET_REQUEST_FAILED",
            "message": "Failed to submit password reset request."
        }), 500


@auth_bp.route("/reset-password/confirm", methods=["POST"])
def confirm_password_reset():
    from backend.models.password_reset import PasswordResetRequest
    data = request.get_json() or {}
    identifier = (data.get("identifier") or data.get("email") or "").strip()
    new_password = data.get("new_password")

    if not identifier or not new_password:
        return jsonify({
            "success": False,
            "error_code": "INVALID_INPUT",
            "message": "Gmail ID / User ID and new password are required."
        }), 400

    if len(new_password) < 4:
        return jsonify({
            "success": False,
            "error_code": "WEAK_PASSWORD",
            "message": "New password must be at least 4 characters long."
        }), 400

    user = User.query.filter(
        db.or_(
            db.func.lower(User.email) == identifier.lower(),
            db.func.lower(User.last_name) == identifier.lower()
        )
    ).first()

    if not user or user.role != "student":
        return jsonify({
            "success": False,
            "error_code": "STUDENT_NOT_FOUND",
            "message": "No registered student account found matching this Gmail ID or User ID."
        }), 404

    # Search for an APPROVED reset request
    approved_req = PasswordResetRequest.query.filter_by(
        user_id=user.id, status="APPROVED"
    ).order_by(PasswordResetRequest.requested_at.desc()).first()

    if not approved_req:
        # Check if there is a pending request
        pending_req = PasswordResetRequest.query.filter_by(
            user_id=user.id, status="PENDING"
        ).first()
        if pending_req:
            return jsonify({
                "success": False,
                "error_code": "RESET_PENDING_APPROVAL",
                "message": "Your password reset request is still pending administrator approval. Please wait for approval before resetting your password."
            }), 403
        else:
            return jsonify({
                "success": False,
                "error_code": "NO_APPROVED_RESET",
                "message": "No approved password reset request found. Please request a password reset first."
            }), 400

    try:
        user.set_password(new_password)
        approved_req.status = "COMPLETED"
        approved_req.completed_at = datetime.datetime.utcnow()

        audit = AuditLog(
            user_id=user.id,
            action="PASSWORD_RESET_COMPLETED",
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent")
        )
        audit.details = {"email": user.email}
        db.session.add(audit)
        db.session.commit()

        logger.info(f"Password reset completed for student: {user.email}")
        return jsonify({
            "success": True,
            "message": "Password reset successfully! You can now sign in with your new password."
        }), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to reset password: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "PASSWORD_RESET_FAILED",
            "message": "Failed to update password. Please try again."
        }), 500

