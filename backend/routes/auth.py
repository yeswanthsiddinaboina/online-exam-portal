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

    try:
        user = User(
            email=email,
            first_name=first_name,
            last_name=last_name,
            role=role
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
        audit.details = {"email": email, "role": role}
        db.session.add(audit)
        db.session.commit()

        logger.info(f"Registered user: {email} with role: {role}")
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
    
    if not all([email, first_name]):
        return jsonify({
            "success": False,
            "error_code": "INVALID_INPUT",
            "message": "All fields (email, Name) are required."
        }), 400
        
    first_name = first_name.strip()
    
    # Check if Email already registered
    existing_by_email = User.query.filter_by(email=email).first()
    if existing_by_email:
        if existing_by_email.registration_status == "REJECTED":
            try:
                existing_by_email.first_name = first_name
                existing_by_email.last_name = "Not Assigned"
                existing_by_email.registration_status = "PENDING"
                existing_by_email.first_login_completed = False
                db.session.commit()
                logger.info(f"Rejected student re-registered: {email}")
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
            registration_status="PENDING",
            first_login_completed=False
        )
        student.set_password("student-passwordless")
        db.session.add(student)
        db.session.commit()
        
        logger.info(f"Student registration request submitted: {email}")
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
    email = data.get("email").strip() if data.get("email") else None
    password = data.get("password")

    if not email:
        return jsonify({
            "success": False,
            "error_code": "EMAIL_REQUIRED",
            "message": "Email is required."
        }), 400

    # Search for user by email case-insensitively
    user = User.query.filter(db.func.lower(User.email) == email.lower()).first()
    
    if not user:
        return jsonify({
            "success": False,
            "error_code": "ACCOUNT_NOT_FOUND",
            "message": "No registered account found with this email. Please register first."
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
            
    # For admin accounts, verify password
    if user.role == "admin":
        if not password or not user.check_password(password):
            audit = AuditLog(
                user_id=user.id,
                action="FAILED_LOGIN_ATTEMPT",
                ip_address=request.remote_addr,
                user_agent=request.headers.get("User-Agent")
            )
            audit.details = {"attempted_email": email}
            db.session.add(audit)
            db.session.commit()

            return jsonify({
                "success": False,
                "error_code": "INVALID_CREDENTIALS",
                "message": "Incorrect password for administrator account."
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
