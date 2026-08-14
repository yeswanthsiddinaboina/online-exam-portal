import datetime
from backend.models import db

class EvidenceRecord(db.Model):
    __tablename__ = "evidence_records"
    
    id = db.Column(db.Integer, primary_key=True)
    violation_log_id = db.Column(db.Integer, db.ForeignKey("violation_logs.id"), nullable=True)
    attempt_id = db.Column(db.Integer, db.ForeignKey("exam_attempts.id"), nullable=False)
    file_path = db.Column(db.String(256), nullable=False)
    file_hash = db.Column(db.String(64), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    content_type = db.Column(db.String(50), nullable=False, default="image/jpeg")
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "violation_log_id": self.violation_log_id,
            "attempt_id": self.attempt_id,
            "file_path": self.file_path,
            "file_size": self.file_size,
            "content_type": self.content_type,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
