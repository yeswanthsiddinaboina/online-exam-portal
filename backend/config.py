import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env in the project root
project_root = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=project_root / ".env")


def _is_valid_path_candidate(candidate: Path) -> bool:
    if not candidate.anchor:
        return True

    try:
        root = candidate.anchor
        return Path(root).exists() if root else True
    except (OSError, RuntimeError):
        return False


def _resolve_project_path(env_value, default_path):
    if env_value is None or str(env_value).strip() == "":
        return default_path

    candidate = Path(str(env_value)).expanduser()
    if not candidate.is_absolute():
        candidate = (project_root / candidate).resolve()

    if candidate.anchor and not _is_valid_path_candidate(candidate):
        return default_path

    try:
        if candidate.suffix:
            candidate.parent.mkdir(parents=True, exist_ok=True)
        else:
            candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    except (OSError, RuntimeError):
        return default_path


def _resolve_sqlite_uri(env_value, default_uri):
    if env_value is None or str(env_value).strip() == "":
        return default_uri

    # Render / Heroku PostgreSQL connection strings use postgres:// which SQLAlchemy 1.4+ rejects
    if env_value.startswith("postgres://"):
        return env_value.replace("postgres://", "postgresql://", 1)

    if not env_value.startswith("sqlite:///"):
        return env_value

    raw_path = env_value.replace("sqlite:///", "", 1)
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = (project_root / candidate).resolve()

    if candidate.anchor and not _is_valid_path_candidate(candidate):
        return default_uri

    try:
        candidate.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{candidate.as_posix()}"
    except (OSError, RuntimeError):
        return default_uri


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "super-secret-default-key")

    default_db_path = project_root / "secure_exam.db"
    SQLALCHEMY_DATABASE_URI = _resolve_sqlite_uri(
        os.environ.get("DATABASE_URL"),
        f"sqlite:///{default_db_path.as_posix()}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Production connection pool optimizations for high concurrent traffic (e.g. Render / PostgreSQL)
    if SQLALCHEMY_DATABASE_URI.startswith("postgresql"):
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_size": 15,
            "max_overflow": 25,
            "pool_recycle": 300,
            "pool_pre_ping": True,
        }
    else:
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_recycle": 300,
            "pool_pre_ping": True,
        }

    EVIDENCE_DIR = _resolve_project_path(
        os.environ.get("EVIDENCE_DIR"),
        project_root / "evidence"
    )

    @classmethod
    def init_app(cls, app):
        # Ensure evidence directory exists
        cls.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
