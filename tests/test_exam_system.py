import unittest
import sys
import os
import json
from pathlib import Path
import datetime

# Add root folder to pythonpath
sys.path.append(str(Path(__file__).resolve().parent.parent))

from backend.app import create_app
from backend.models import db, User, Exam, Question, QuestionOption, ExamAttempt, ViolationLog, Result
from backend.services.evaluation import EvaluationService
from backend.services.violation_engine import ViolationEngine
from backend.services.session_manager import SessionManager

class TestingConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "test-secret"
    EVIDENCE_DIR = Path(__file__).resolve().parent / "test_evidence"
    
    @classmethod
    def init_app(cls, app):
        pass

class SecureExamSystemTests(unittest.TestCase):
    def setUp(self):
        # Configure app for testing with an in-memory SQLite database
        self.app = create_app(TestingConfig)
        self.client = self.app.test_client()

        self.ctx = self.app.app_context()
        self.ctx.push()

        db.create_all()
        self.seed_test_data()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def seed_test_data(self):
        # Create test users
        self.admin = User(email="admin@test.com", first_name="Admin", last_name="User", role="admin")
        self.admin.set_password("AdminPass123!")
        
        self.student = User(email="student@test.com", first_name="Student", last_name="One", role="student")
        self.student.set_password("StudentPass123!")

        db.session.add(self.admin)
        db.session.add(self.student)
        db.session.commit()

        # Create exam
        self.exam = Exam(title="Math Midterm", description="Basic algebra", duration_minutes=30, created_by=self.admin.id)
        db.session.add(self.exam)
        db.session.commit()

        # Create security policy configuration
        from backend.models.security_config import ExamSecurityConfig
        self.sec_cfg = ExamSecurityConfig(
            exam_id=self.exam.id,
            head_turn_limit=3,
            tab_switch_limit=2,
            cooldown_seconds=5
        )
        db.session.add(self.sec_cfg)
        db.session.commit()

        # Add questions
        self.q1 = Question(
            exam_id=self.exam.id,
            question_text="What is 2 + 2?",
            question_type="MCQ",
            marks=2.0,
            negative_marks=0.5,
            correct_answer="B"
        )
        db.session.add(self.q1)
        db.session.flush()

        self.o1 = QuestionOption(question_id=self.q1.id, option_letter="A", option_text="3")
        self.o2 = QuestionOption(question_id=self.q1.id, option_letter="B", option_text="4")
        self.o3 = QuestionOption(question_id=self.q1.id, option_letter="C", option_text="5")
        db.session.add_all([self.o1, self.o2, self.o3])
        db.session.commit()

    # --- UNIT TESTS ---
    def test_evaluation_scoring(self):
        """Tests that server-side evaluation calculates scores, percentages, and status correctly."""
        # Create attempt
        attempt = ExamAttempt(
            student_id=self.student.id,
            exam_id=self.exam.id,
            status="IN_PROGRESS",
            started_at=datetime.datetime.utcnow()
        )
        db.session.add(attempt)
        db.session.commit()

        # Submit answer (correct)
        from backend.models.answer import StudentAnswer
        ans = StudentAnswer(attempt_id=attempt.id, question_id=self.q1.id)
        ans.selected_answers = ["B"]
        db.session.add(ans)
        db.session.commit()

        # Run evaluation
        res = EvaluationService.evaluate_attempt(attempt.id)
        self.assertIsNotNone(res)
        self.assertEqual(res.total_score, 2.0)
        self.assertEqual(res.percentage, 100.0)
        self.assertTrue(res.passed)

        # Update answer to incorrect A, evaluate negative markings
        ans.selected_answers = ["A"]
        db.session.commit()
        res = EvaluationService.evaluate_attempt(attempt.id)
        self.assertEqual(res.total_score, 0.0) # Floored at 0.0, because obtained score -0.5 is negative but capped
        self.assertEqual(res.percentage, 0.0)
        self.assertFalse(res.passed)

    def test_violation_engine_cooldown_and_limits(self):
        """Tests that violation engine enforces limits, respects cooldowns, and triggers termination."""
        self.sec_cfg.cooldown_seconds = 0
        db.session.commit()

        attempt = ExamAttempt(
            student_id=self.student.id,
            exam_id=self.exam.id,
            status="IN_PROGRESS",
            started_at=datetime.datetime.utcnow()
        )
        db.session.add(attempt)
        db.session.commit()

        # 1st violation (TAB_SWITCH)
        res1 = ViolationEngine.process_event(attempt.id, "TAB_SWITCH", 1.0)
        self.assertEqual(res1["action"], "WARNING")
        self.assertEqual(res1["violation_count"], 1)

        # 2nd violation (TAB_SWITCH) - limit is 2. This should trigger termination!
        res2 = ViolationEngine.process_event(attempt.id, "TAB_SWITCH", 1.0)
        self.assertEqual(res2["action"], "TERMINATE")
        self.assertEqual(res2["violation_count"], 2)

        # Attempt should now be flagged malpractice
        db.session.refresh(attempt)
        self.assertEqual(attempt.status, "MALPRACTICE_CANCELLED")

    def test_violation_cooldown_deduplication(self):
        """Tests that events triggered within the cooldown interval do not increment counts."""
        attempt = ExamAttempt(
            student_id=self.student.id,
            exam_id=self.exam.id,
            status="IN_PROGRESS",
            started_at=datetime.datetime.utcnow()
        )
        db.session.add(attempt)
        db.session.commit()

        # Trigger head turn (limit is 3)
        res1 = ViolationEngine.process_event(attempt.id, "HEAD_TURN", 1.0)
        self.assertEqual(res1["violation_count"], 1)
        
        # Trigger head turn immediately again (within cooldown of 5s)
        res2 = ViolationEngine.process_event(attempt.id, "HEAD_TURN", 1.0)
        self.assertEqual(res2["violation_count"], 1) # count remains 1
        self.assertEqual(res2["message"], "Duplicate event within cooldown. Action repeated.")

    # --- INTEGRATION & SECURITY TESTS ---
    def test_unauthorized_api_access(self):
        """Verifies that endpoints block requests without valid JWT authorization headers."""
        # Query exam list without token
        response = self.client.get("/api/exams")
        self.assertEqual(response.status_code, 401)
        
        data = json.loads(response.data)
        self.assertFalse(data["success"])
        self.assertEqual(data["error_code"], "UNAUTHORIZED")

    def test_role_escalation_security(self):
        """Verifies that students cannot access admin dashboard endpoints."""
        # 1. Login as student to get token
        login_res = self.client.post("/api/auth/login", data=json.dumps({
            "email": "student@test.com",
            "password": "StudentPass123!"
        }), content_type="application/json")
        token = json.loads(login_res.data)["token"]

        # 2. Call admin dashboard using student token
        response = self.client.get("/api/admin/dashboard", headers={
            "Authorization": f"Bearer {token}"
        })
        self.assertEqual(response.status_code, 403)
        
        data = json.loads(response.data)
        self.assertEqual(data["error_code"], "FORBIDDEN")

if __name__ == "__main__":
    unittest.main()
