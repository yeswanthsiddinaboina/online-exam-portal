import sys
from pathlib import Path

# Add project root to python path to avoid import errors
sys.path.append(str(Path(__file__).resolve().parent.parent))

from flask import Flask
from backend.config import Config
from backend.models import db, User

def initialize_database():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # Initialize the app with db and execute configuration setup
    db.init_app(app)
    Config.init_app(app)
    
    with app.app_context():
        print("Creating database tables...")
        db.create_all()
        print("Database tables created successfully!")
        
        # Check if default admin exists, if not, create one
        admin = User.query.filter_by(role="admin").first()
        if not admin:
            print("Creating default admin account...")
            default_admin = User(
                email="admin@secureexam.com",
                first_name="System",
                last_name="Administrator",
                role="admin"
            )
            default_admin.set_password("AdminSecurePass123!")
            db.session.add(default_admin)
            db.session.commit()
            print("Default admin created successfully:")
            print("Email: admin@secureexam.com")
            print("Password: AdminSecurePass123!")
        else:
            print("Admin account already exists.")

if __name__ == "__main__":
    initialize_database()
