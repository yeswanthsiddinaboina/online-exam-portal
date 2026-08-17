import datetime
from backend.models import db

class Result(db.Model):
    __tablename__ = "results"
    
    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(db.Integer, db.ForeignKey("exam_attempts.id"), nullable=False, unique=True)
    total_score = db.Column(db.Float, nullable=False, default=0.0)
    percentage = db.Column(db.Float, nullable=False, default=0.0)
    passed = db.Column(db.Boolean, nullable=False, default=False)
    evaluated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "attempt_id": self.attempt_id,
            "total_score": self.total_score,
            "percentage": self.percentage,
            "passed": self.passed,
            "evaluated_at": self.evaluated_at.isoformat() + "Z" if self.evaluated_at else None
        }
