import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env in the project root
project_root = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=project_root / ".env")

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "super-secret-default-key")
    
    # Database configuration
    # Fallback to sqlite if DATABASE_URL is not set
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{project_root}/secure_exam.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Evidence storage
    EVIDENCE_DIR = Path(os.environ.get(
        "EVIDENCE_DIR",
        project_root / "evidence"
    ))
    
    @classmethod
    def init_app(cls, app):
        # Ensure evidence directory exists
        cls.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
