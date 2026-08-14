import datetime
from backend.models import db

class Question(db.Model):
    __tablename__ = "questions"
    
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("exams.id"), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    question_type = db.Column(db.String(30), nullable=False, default="MCQ") # MCQ, TF, SHORT_ANSWER
    marks = db.Column(db.Float, nullable=False, default=1.0)
    negative_marks = db.Column(db.Float, nullable=False, default=0.0)
    correct_answer = db.Column(db.String(200), nullable=False) # e.g. "A" for MCQ, "True" for TF, or text for SHORT_ANSWER
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    # Relationships
    options = db.relationship("QuestionOption", backref="question", lazy=True, cascade="all, delete-orphan")
    answers = db.relationship("StudentAnswer", backref="question", lazy=True, cascade="all, delete-orphan")

    def to_dict(self, include_correct=False):
        data = {
            "id": self.id,
            "exam_id": self.exam_id,
            "question_text": self.question_text,
            "question_type": self.question_type,
            "marks": self.marks,
            "negative_marks": self.negative_marks,
            "options": [opt.to_dict() for opt in self.options],
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
        if include_correct:
            data["correct_answer"] = self.correct_answer
        return data

class QuestionOption(db.Model):
    __tablename__ = "question_options"
    
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=False)
    option_letter = db.Column(db.String(10), nullable=False) # A, B, C, D
    option_text = db.Column(db.Text, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "question_id": self.question_id,
            "option_letter": self.option_letter,
            "option_text": self.option_text
        }
