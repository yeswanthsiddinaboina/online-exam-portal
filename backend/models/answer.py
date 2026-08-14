import datetime
import json
from backend.models import db

class StudentAnswer(db.Model):
    __tablename__ = "student_answers"
    
    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(db.Integer, db.ForeignKey("exam_attempts.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=False)
    
    # Store selected letters as JSON serialized string, e.g. ["A"] or ["A", "B"]
    _selected_answers = db.Column("selected_answers", db.Text, nullable=True)
    text_answer = db.Column(db.Text, nullable=True)
    saved_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    @property
    def selected_answers(self):
        if self._selected_answers:
            try:
                return json.loads(self._selected_answers)
            except Exception:
                return []
        return []

    @selected_answers.setter
    def selected_answers(self, val):
        if val is not None:
            self._selected_answers = json.dumps(val)
        else:
            self._selected_answers = None

    def to_dict(self):
        return {
            "id": self.id,
            "attempt_id": self.attempt_id,
            "question_id": self.question_id,
            "selected_answers": self.selected_answers,
            "text_answer": self.text_answer,
            "saved_at": self.saved_at.isoformat() if self.saved_at else None
        }
