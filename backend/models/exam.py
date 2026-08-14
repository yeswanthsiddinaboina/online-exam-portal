import datetime
from backend.models import db

class Exam(db.Model):
    __tablename__ = "exams"
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    duration_minutes = db.Column(db.Integer, nullable=False, default=60)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    # Relationships
    questions = db.relationship("Question", backref="exam", lazy=True, cascade="all, delete-orphan")
    attempts = db.relationship("ExamAttempt", backref="exam", lazy=True, cascade="all, delete-orphan")
    security_config = db.relationship("ExamSecurityConfig", backref="exam", uselist=False, lazy=True, cascade="all, delete-orphan")

    def to_dict(self, include_config=True):
        data = {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "duration_minutes": self.duration_minutes,
            "created_by": self.created_by,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
        if include_config and self.security_config:
            data["security_config"] = self.security_config.to_dict()
        return data
