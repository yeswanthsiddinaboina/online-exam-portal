import datetime
from backend.models import db

class PasswordResetRequest(db.Model):
    __tablename__ = "password_resets"
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="PENDING") # PENDING, APPROVED, REJECTED, COMPLETED
    requested_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    approved_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    # Relationship
    user = db.relationship("User", backref=db.backref("password_resets", lazy=True, cascade="all, delete-orphan"))

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "student_name": f"{self.user.first_name} ({self.user.last_name})" if self.user else "Unknown",
            "student_email": self.user.email if self.user else "Unknown",
            "student_userid": self.user.last_name if self.user else "Unknown",
            "status": self.status,
            "requested_at": self.requested_at.isoformat() + "Z" if self.requested_at else None,
            "approved_at": self.approved_at.isoformat() + "Z" if self.approved_at else None,
            "completed_at": self.completed_at.isoformat() + "Z" if self.completed_at else None
        }
