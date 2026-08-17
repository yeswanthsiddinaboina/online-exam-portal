from backend.models import db, Question, StudentAnswer, Result, ExamAttempt
from backend.utils.logger import get_logger
import datetime

logger = get_logger()

class EvaluationService:
    @staticmethod
    def evaluate_attempt(attempt_id):
        """Calculates total score, marks, percentage and updates attempt result."""
        attempt = ExamAttempt.query.get(attempt_id)
        if not attempt:
            logger.error(f"Cannot evaluate: Attempt {attempt_id} not found")
            return None

        # Fetch questions and candidate answers
        questions = Question.query.filter_by(exam_id=attempt.exam_id).all()
        answers = {ans.question_id: ans for ans in attempt.answers}
        
        total_max_marks = sum(q.marks for q in questions)
        obtained_score = 0.0

        for question in questions:
            ans = answers.get(question.id)
            if not ans:
                # Unanswered question gets zero marks
                continue

            is_correct = False
            
            if question.question_type == "MCQ" or question.question_type == "TF":
                def extract_letter(val):
                    val_strip = val.strip().upper()
                    if len(val_strip) >= 2 and val_strip[0].isalpha() and val_strip[1] in [')', '.', '-', ':', ' ']:
                        return val_strip[0]
                    return val_strip

                selected = [extract_letter(s) for s in (ans.selected_answers or [])]
                correct_str = question.correct_answer or ""
                correct_list = [extract_letter(c) for c in correct_str.split(",") if c.strip()]
                
                if len(selected) > 0 and sorted(selected) == sorted(correct_list):
                    is_correct = True
            
            elif question.question_type == "SHORT_ANSWER":
                # Text matching
                candidate_text = (ans.text_answer or "").strip().lower()
                correct_text = question.correct_answer.strip().lower()
                if candidate_text == correct_text:
                    is_correct = True
            
            if is_correct:
                obtained_score += question.marks
            else:
                # Deduct negative marks if applicable
                obtained_score -= question.negative_marks

        # Ensure score does not fall below zero
        obtained_score = max(0.0, obtained_score)
        
        percentage = (obtained_score / total_max_marks * 100) if total_max_marks > 0 else 0.0
        passed = percentage >= 50.0  # Default passing threshold is 50%

        try:
            # Check if result already exists to ensure idempotency
            result = Result.query.filter_by(attempt_id=attempt_id).first()
            if not result:
                result = Result(attempt_id=attempt_id)
                db.session.add(result)
            
            result.total_score = obtained_score
            result.percentage = percentage
            result.passed = passed
            result.evaluated_at = datetime.datetime.utcnow()
            
            db.session.commit()
            logger.info(f"Evaluated attempt {attempt_id}: Score={obtained_score}/{total_max_marks} ({percentage:.2f}%) Pass={passed}")
            return result
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error evaluating exam attempt {attempt_id}: {str(e)}")
            return None
