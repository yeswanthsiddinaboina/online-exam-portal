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
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    course = db.Column(db.String(50), nullable=True, default="Python & Java") # Options: "Drive", "Python", "Java", "Python & Java", "All Courses"
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    # Relationships
    questions = db.relationship("Question", backref="exam", lazy=True, cascade="all, delete-orphan")
    attempts = db.relationship("ExamAttempt", backref="exam", lazy=True, cascade="all, delete-orphan")
    security_config = db.relationship("ExamSecurityConfig", backref="exam", uselist=False, lazy=True, cascade="all, delete-orphan")

    def is_accessible_by(self, student_course):
        """
        Determines whether a candidate with enrolled student_course can view/attempt this exam.
        - Drive exams are strictly reserved for Drive candidates.
        - Python & Java exams are strictly for Python/Java candidates.
        - All Courses exams are accessible to everyone.
        """
        sc = (student_course or "").strip().lower()
        ec = (self.course or "All Courses").strip().lower()

        # If exam is open to All Courses, any student can access
        if ec in ["all", "all courses", ""]:
            return True

        # If legacy student with no course set, allow
        if not sc:
            return True

        # Aptitude exams are ONLY for Aptitude students
        if ec == "aptitude":
            return sc == "aptitude"

        # Drive exams are for Drive students (and Aptitude students)
        if ec == "drive":
            return sc in ["drive", "aptitude"]

        # Python & Java exams are for Python and Java students (NOT Drive or Aptitude)
        if ec in ["python & java", "python and java"]:
            return sc in ["python", "java"]

        # Python exams are only for Python
        if ec == "python":
            return sc == "python"

        # Java exams are only for Java
        if ec == "java":
            return sc == "java"

        return sc == ec

    def to_dict(self, include_config=True):
        data = {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "duration_minutes": self.duration_minutes,
            "created_by": self.created_by,
            "is_active": self.is_active,
            "course": self.course or "Python & Java",
            "question_count": len(self.questions),
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
        if include_config and self.security_config:
            data["security_config"] = self.security_config.to_dict()
        return data
