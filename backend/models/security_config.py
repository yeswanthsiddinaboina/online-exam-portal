from backend.models import db

class ExamSecurityConfig(db.Model):
    __tablename__ = "exam_security_configs"
    
    exam_id = db.Column(db.Integer, db.ForeignKey("exams.id"), primary_key=True)
    head_turn_limit = db.Column(db.Integer, nullable=False, default=5)
    tab_switch_limit = db.Column(db.Integer, nullable=False, default=3)
    multiple_person_limit = db.Column(db.Integer, nullable=False, default=3)
    mobile_limit = db.Column(db.Integer, nullable=False, default=2)
    fullscreen_exit_limit = db.Column(db.Integer, nullable=False, default=3)
    
    cooldown_seconds = db.Column(db.Integer, nullable=False, default=10)
    heartbeat_interval = db.Column(db.Integer, nullable=False, default=5)
    network_grace_period = db.Column(db.Integer, nullable=False, default=30)
    
    phone_confidence = db.Column(db.Float, nullable=False, default=0.25)
    person_confidence = db.Column(db.Float, nullable=False, default=0.25)
    face_confidence = db.Column(db.Float, nullable=False, default=0.35)

    def to_dict(self):
        return {
            "exam_id": self.exam_id,
            "head_turn_limit": self.head_turn_limit,
            "tab_switch_limit": self.tab_switch_limit,
            "multiple_person_limit": self.multiple_person_limit,
            "mobile_limit": self.mobile_limit,
            "fullscreen_exit_limit": self.fullscreen_exit_limit,
            "cooldown_seconds": self.cooldown_seconds,
            "heartbeat_interval": self.heartbeat_interval,
            "network_grace_period": self.network_grace_period,
            "phone_confidence": self.phone_confidence,
            "person_confidence": self.person_confidence,
            "face_confidence": self.face_confidence
        }
