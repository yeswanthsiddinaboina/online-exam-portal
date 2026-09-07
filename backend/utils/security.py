import jwt
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
