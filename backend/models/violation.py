import datetime
from backend.models import db

class ViolationLog(db.Model):
    __tablename__ = "violation_logs"
    
    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(db.Integer, db.ForeignKey("exam_attempts.id"), nullable=False)
    event_type = db.Column(db.String(50), nullable=False) # e.g. HEAD_TURN, PHONE_DETECTED, TAB_SWITCH
    confidence = db.Column(db.Float, nullable=False, default=1.0)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    severity = db.Column(db.Integer, nullable=False, default=1) # 1: log, 2: warn, 3: terminate
    count_incremented = db.Column(db.Integer, nullable=False, default=1)
    action_taken = db.Column(db.String(30), nullable=False, default="LOG") # WARNING, TERMINATE, LOG

    # Relationship to evidence
    evidence = db.relationship("EvidenceRecord", backref="violation_log", uselist=False, lazy=True, cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "attempt_id": self.attempt_id,
            "event_type": self.event_type,
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat() + "Z" if self.timestamp else None,
            "severity": self.severity,
            "count_incremented": self.count_incremented,
            "action_taken": self.action_taken,
            "evidence_id": self.evidence.id if self.evidence else None
        }
