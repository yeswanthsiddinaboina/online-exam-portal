import datetime
from backend.models import db

class ExamAccess(db.Model):
    __tablename__ = "exam_access"
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    exam_id = db.Column(db.Integer, db.ForeignKey("exams.id"), nullable=False)
    approved = db.Column(db.Boolean, default=False, nullable=False)
    requested_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    # Relationships
    student = db.relationship("User", backref=db.backref("exam_accesses", lazy=True, cascade="all, delete-orphan"))
    exam = db.relationship("Exam", backref=db.backref("exam_accesses", lazy=True, cascade="all, delete-orphan"))

    def to_dict(self):
        return {
            "id": self.id,
            "student_id": self.student_id,
            "student_email": self.student.email if self.student else "Unknown",
            "exam_id": self.exam_id,
            "exam_title": self.exam.title if self.exam else "Unknown",
            "approved": self.approved,
            "requested_at": self.requested_at.isoformat() + "Z" if self.requested_at else None
        }
