import datetime
from backend.models import db

class ExamAttempt(db.Model):
    __tablename__ = "exam_attempts"
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    exam_id = db.Column(db.Integer, db.ForeignKey("exams.id"), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="NOT_STARTED") 
    # NOT_STARTED, IN_PROGRESS, SUBMITTED, AUTO_SUBMITTED, MALPRACTICE_CANCELLED, EXPIRED, NETWORK_INTERRUPTED
    
    started_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)
    last_heartbeat = db.Column(db.DateTime, nullable=True)
    session_token = db.Column(db.String(256), nullable=True)
    
    # Relationships
    answers = db.relationship("StudentAnswer", backref="attempt", lazy=True, cascade="all, delete-orphan")
    violations = db.relationship("ViolationLog", backref="attempt", lazy=True, cascade="all, delete-orphan")
    evidences = db.relationship("EvidenceRecord", backref="attempt", lazy=True, cascade="all, delete-orphan")
    result = db.relationship("Result", backref="attempt", uselist=False, lazy=True, cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "student_id": self.student_id,
            "exam_id": self.exam_id,
            "status": self.status,
            "started_at": self.started_at.isoformat() + "Z" if self.started_at else None,
            "ended_at": self.ended_at.isoformat() + "Z" if self.ended_at else None,
            "last_heartbeat": self.last_heartbeat.isoformat() + "Z" if self.last_heartbeat else None,
            "session_token": self.session_token
        }
