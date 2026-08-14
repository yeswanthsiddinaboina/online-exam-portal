from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# Import models to ensure they are registered with SQLAlchemy
from .user import User
from .exam import Exam
from .security_config import ExamSecurityConfig
from .question import Question, QuestionOption
from .attempt import ExamAttempt
from .answer import StudentAnswer
from .violation import ViolationLog
from .evidence import EvidenceRecord
from .audit import AuditLog
from .result import Result
from .access import ExamAccess
