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
    email = data.get("email")
    password = data.get("password")
    first_name = data.get("first_name")
    last_name = data.get("last_name")
    role = data.get("role", "student") # Defaults to student

    if not all([email, password, first_name, last_name]):
        return jsonify({
            "success": False,
            "error_code": "INVALID_INPUT",
            "message": "All fields (email, password, first_name, last_name) are required."
        }), 400

    if role not in ["student", "admin"]:
        return jsonify({
            "success": False,
            "error_code": "INVALID_ROLE",
            "message": "Invalid user role specified."
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

@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    email = data.get("email")
    password = data.get("password")
    username = data.get("username")
    student_id = data.get("student_id")

    if not email:
        return jsonify({
            "success": False,
            "error_code": "EMAIL_REQUIRED",
            "message": "Email is required."
        }), 400

    user = User.query.filter_by(email=email).first()
    
    # If student, allow login or register automatically
    if not user:
        # Require username and student_id for initial registration
        if not username or not student_id:
            return jsonify({
                "success": False,
                "error_code": "REGISTRATION_FIELDS_REQUIRED",
                "message": "User Name and User ID are required to register your student account."
            }), 400
        try:
            user = User(
                email=email,
                first_name=username,
                last_name=student_id,
                role="student"
            )
            user.set_password("dummy_password")
            db.session.add(user)
            db.session.commit()
            logger.info(f"Automatically registered student user: {email} ({username} - {student_id})")
        except Exception as ex:
            db.session.rollback()
            logger.error(f"Failed to auto-register student user: {str(ex)}")
            return jsonify({
                "success": False,
                "error_code": "AUTO_REGISTRATION_FAILED",
                "message": "Failed to initialize student account."
            }), 500
            
    # For existing student users, update username/userid if provided to keep records fresh
    elif user.role == "student":
        try:
            modified = False
            if username and user.first_name != username:
                user.first_name = username
                modified = True
            if student_id and user.last_name != student_id:
                user.last_name = student_id
                modified = True
            if modified:
                db.session.commit()
                logger.info(f"Updated registration details for student: {email}")
        except Exception as ex:
            db.session.rollback()
            logger.error(f"Failed to update student details: {str(ex)}")
            
    # For existing users, if they are admin, we MUST require and verify password
    if user.role == "admin":
        if not password or not user.check_password(password):
            # Register a failed login audit log
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

    logger.info(f"User logged in: {email}")
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
