import sys
from pathlib import Path

# Add project root to python path to resolve 'backend' imports when run directly
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from flask import Flask, jsonify
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
from backend.config import Config
from backend.models import db
from backend.utils.logger import get_logger

# Import blueprints
from backend.routes.auth import auth_bp
from backend.routes.exams import exams_bp
from backend.routes.questions import questions_bp
from backend.routes.attempts import attempts_bp
from backend.routes.proctoring import proctoring_bp
from backend.routes.results import results_bp
from backend.routes.admin import admin_bp

logger = get_logger()

def create_app(config_class=Config):
    # Resolve the absolute path of the frontend directory
    project_root = Path(__file__).resolve().parent.parent
    frontend_dir = project_root / "frontend"
    
    app = Flask(__name__, static_folder=str(frontend_dir), static_url_path="")
    app.config.from_object(config_class)

    # Enable Cross-Origin Resource Sharing
    CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

    # Initialize extensions
    db.init_app(app)
    config_class.init_app(app)

    with app.app_context():
        try:
            db.create_all()
            logger.info("Database tables synchronized successfully.")
            
            # Enforce single admin user policy with fixed credentials
            from backend.models.user import User
            admin_user = User.query.filter_by(email="admin@gmail.com").first()
            if not admin_user:
                admin_user = User(
                    email="admin@gmail.com",
                    first_name="Admin",
                    last_name="System",
                    role="admin"
                )
                admin_user.set_password("Admin@123")
                db.session.add(admin_user)
                db.session.flush() # Generate ID for potential reassignments
                logger.info("Pre-seeded the default admin account: admin@gmail.com")
            else:
                # Guarantee the password is reset/forced to Admin@123
                admin_user.set_password("Admin@123")
                logger.info("Aligned existing default admin account password to Admin@123")
            
            # Remove any other admin accounts to enforce single-admin constraint
            other_admins = User.query.filter(User.role == "admin", User.email != "admin@gmail.com").all()
            for oa in other_admins:
                # Reassign any exams created by this redundant admin to the default admin account
                from backend.models.exam import Exam
                exams_created = Exam.query.filter_by(created_by=oa.id).all()
                for exam in exams_created:
                    exam.created_by = admin_user.id
                    logger.info(f"Reassigned exam '{exam.title}' to the default admin account.")
                    
                db.session.delete(oa)
                logger.info(f"Removed redundant admin account: {oa.email}")
                
            db.session.commit()
        except Exception as db_err:
            db.session.rollback()
            logger.error(f"Failed to synchronize database tables: {str(db_err)}")

    # Register blueprints with appropriate URL prefixes
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(exams_bp, url_prefix="/api/exams")
    app.register_blueprint(questions_bp, url_prefix="/api") # questions are nested
    app.register_blueprint(attempts_bp, url_prefix="/api")  # attempts are nested
    app.register_blueprint(proctoring_bp, url_prefix="/api")
    app.register_blueprint(results_bp, url_prefix="/api/results")
    app.register_blueprint(admin_bp, url_prefix="/api/admin")

    # Global HTTP Exception Handler (Structured errors)
    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        logger.warning(f"HTTPException: {e.code} - {e.description}")
        return jsonify({
            "success": False,
            "error_code": f"HTTP_{e.code}",
            "message": e.description
        }), e.code

    # Global Unhandled Exception Handler (Security precaution: prevent traceback leak)
    @app.errorhandler(Exception)
    def handle_unhandled_exception(e):
        logger.error(f"Unhandled Exception: {str(e)}", exc_info=True)
        return jsonify({
            "success": False,
            "error_code": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected error occurred. Please contact the administrator."
        }), 500

    @app.after_request
    def add_header(response):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    @app.route("/", methods=["GET"])
    def index():
        return app.send_static_file("login.html")

    @app.route("/health", methods=["GET"])
    def health_check():
        return jsonify({"status": "healthy", "service": "secure-exam-system-backend"}), 200

    return app

if __name__ == "__main__":
    app = create_app()
    # Run the server
    app.run(host="127.0.0.1", port=5001, debug=True)
