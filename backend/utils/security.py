import jwt
import re
from datetime import datetime, timezone, timedelta
from functools import wraps
from flask import request, jsonify
from backend.config import Config
from backend.models.user import User
from backend.utils.logger import get_logger

logger = get_logger()

def generate_token(user_id, role, expires_in_hours=12):
    """Generates a JWT token for the user session."""
    logger.info(f"generate_token call - SECRET_KEY is: '{Config.SECRET_KEY}'")
    try:
        payload = {
            "exp": datetime.now(timezone.utc) + timedelta(hours=expires_in_hours),
            "iat": datetime.now(timezone.utc),
            "sub": str(user_id),
            "role": role
        }
        return jwt.encode(
            payload,
            Config.SECRET_KEY,
            algorithm="HS256"
        )
    except Exception as e:
        logger.error(f"Error generating token: {str(e)}")
        return None

def decode_token(token):
    """Decodes a JWT token."""
    logger.info(f"decode_token call - SECRET_KEY is: '{Config.SECRET_KEY}'")
    try:
        return jwt.decode(token, Config.SECRET_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return {"error": "TOKEN_EXPIRED", "message": "The session token has expired."}
    except jwt.InvalidTokenError as e:
        logger.error(f"JWT decode failed with InvalidTokenError: {str(e)}", exc_info=True)
        return {"error": "INVALID_TOKEN", "message": f"The session token is invalid: {str(e)}"}
    except Exception as e:
        logger.error(f"JWT decode failed with unexpected Exception: {str(e)}", exc_info=True)
        return {"error": "TOKEN_ERROR", "message": str(e)}

def token_required(f):
    """Decorator to require token authentication on endpoints."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        # Check authorization header
        auth_header = request.headers.get("Authorization")
        logger.info(f"token_required check - Authorization Header: {auth_header}")
        if auth_header:
            parts = auth_header.split()
            if len(parts) == 2 and parts[0].lower() == "bearer":
                token = parts[1]
                
        # Fallback to query parameter token (essential for browser <img> tags, media, and direct downloads)
        if not token:
            token = request.args.get("token")

        if not token:
            logger.warning("token_required check failed: token is missing or malformed")
            return jsonify({
                "success": False,
                "error_code": "UNAUTHORIZED",
                "message": "Authorization token is missing."
            }), 401
            
        decoded = decode_token(token)
        logger.info(f"token_required check - Decoded token payload: {decoded}")
        if "error" in decoded:
            return jsonify({
                "success": False,
                "error_code": decoded["error"],
                "message": decoded["message"]
            }), 401
            
        # Fetch current user
        try:
            user_id = int(decoded["sub"])
        except (ValueError, TypeError, KeyError):
            return jsonify({
                "success": False,
                "error_code": "INVALID_TOKEN",
                "message": "Malformed token subject claim."
            }), 401
            
        user = User.query.get(user_id)
        if not user:
            return jsonify({
                "success": False,
                "error_code": "USER_NOT_FOUND",
                "message": "User associated with this token does not exist."
            }), 401
            
        # Attach user to request context
        request.current_user = user
        return f(*args, **kwargs)
        
    return decorated

def role_required(allowed_roles):
    """Decorator to restrict access by roles (e.g. ['admin'])."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not hasattr(request, "current_user"):
                return jsonify({
                    "success": False,
                    "error_code": "UNAUTHORIZED",
                    "message": "Authentication required."
                }), 401
                
            if request.current_user.role not in allowed_roles:
                return jsonify({
                    "success": False,
                    "error_code": "FORBIDDEN",
                    "message": "You do not have permission to access this resource."
                }), 403
                
            return f(*args, **kwargs)
        return decorated
    return decorator


COMMON_WEAK_PASSWORDS = {
    "password123!", "password1234!", "admin123456!", "welcome1234!",
    "qwerty12345!", "student1234!", "p@ssword123!", "p@ssw0rd123!",
    "p@$$w0rd123!", "password@123", "password#123", "changeme123!",
    "secureexam123!", "testing1234!", "summer2026!", "winter2026!",
    "spring2026!", "autumn2026!", "welcome@1234", "admin@123456",
    "administrator1!", "password2026!", "exampass1234!", "letmein12345!",
    "sunshine1234!", "football1234!", "baseball1234!", "princess1234!",
    "dragon123456!", "master123456!", "monkey123456!", "123456789012!",
    "aa1234567890!", "abcdef123456!", "iloveyou1234!", "trustno1123!",
    "qwertzuiop1!", "zaq12wsx3edc!", "1qaz2wsx3edc!",
    "pass@123", "admin@123", "admin!123", "welcome@1", "p@ssword1", "testing@123"
}

SPECIAL_CHARS = set("!@#$%^&*()_+-=[]{};':\"\\|,.<>/?~`")

def validate_password(password):
    """
    Validates a password against the strong password policy:
    - Minimum length: 8 characters.
    - Maximum length: 64 characters (and UTF-8 bytes <= 72 for bcrypt limit).
    - Requires at least one uppercase letter (A-Z).
    - Requires at least one lowercase letter (a-z).
    - Requires at least one digit (0-9).
    - Requires at least one special character (!@#$%^&*...).
    - Rejects leading and trailing whitespace without silent mutation.
    - Rejects known common weak passwords.
    Returns (is_valid, error_message).
    """
    if not isinstance(password, str):
        return False, "Password must be a valid text string."

    if password.startswith(" ") or password.endswith(" "):
        return False, "Password cannot contain leading or trailing spaces."

    if len(password) < 8:
        return False, "Password must be at least 8 characters long."

    if len(password) > 64:
        return False, "Password cannot exceed 64 characters."

    try:
        encoded = password.encode("utf-8")
        if len(encoded) > 72:
            return False, "Password exceeds maximum supported length (72 bytes)."
    except UnicodeEncodeError:
        return False, "Password contains invalid characters."

    if not re.search(r"[A-Z]", password):
        return False, "Password must include at least one uppercase letter (A-Z)."

    if not re.search(r"[a-z]", password):
        return False, "Password must include at least one lowercase letter (a-z)."

    if not re.search(r"[0-9]", password):
        return False, "Password must include at least one digit (0-9)."

    if not any(c in SPECIAL_CHARS for c in password):
        return False, "Password must include at least one special character (!@#$%^&*...)."

    normalized = password.lower().strip()
    if normalized in COMMON_WEAK_PASSWORDS:
        return False, "Password is too common or easily guessed. Please choose a stronger password."

    return True, None

