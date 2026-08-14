import datetime
import json
from backend.models import db

class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True) # Can be null for unauthenticated events
    action = db.Column(db.String(100), nullable=False) # e.g. LOGIN, LOGOUT, EXAM_STARTED, EXAM_SUBMITTED
    ip_address = db.Column(db.String(45), nullable=True) # Supports IPv4/IPv6
    user_agent = db.Column(db.String(256), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    _details = db.Column("details", db.Text, nullable=True)

    @property
    def details(self):
        if self._details:
            try:
                return json.loads(self._details)
            except Exception:
                return {}
        return {}

    @details.setter
    def details(self, val):
        if val is not None:
            self._details = json.dumps(val)
        else:
            self._details = None

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "action": self.action,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "details": self.details
        }
