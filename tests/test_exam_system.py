import unittest
import sys
import os
import json
import io
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
    def test_invalid_external_evidence_dir_falls_back_to_project_local_path(self):
        """Invalid env paths like D:/... should not break startup on machines without that drive."""
        project_root = Path(__file__).resolve().parent.parent
        original = os.environ.get("EVIDENCE_DIR")
        os.environ["EVIDENCE_DIR"] = "D:/secure-exam-system/evidence"

        import importlib
        import backend.config as config_module

        reloaded = importlib.reload(config_module)
        self.assertEqual(reloaded.Config.EVIDENCE_DIR, project_root / "evidence")

        if original is None:
            os.environ.pop("EVIDENCE_DIR", None)
        else:
            os.environ["EVIDENCE_DIR"] = original

        importlib.reload(config_module)

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

    def test_strict_warning_policy_terminates_on_breach(self):
        """Mobile cap is 2 warnings, face cap is 3 warnings, and termination occurs on the breach threshold."""
        self.sec_cfg.cooldown_seconds = 0
        self.sec_cfg.mobile_limit = 2
        self.sec_cfg.head_turn_limit = 3
        self.sec_cfg.multiple_person_limit = 3
        db.session.commit()

        attempt = ExamAttempt(
            student_id=self.student.id,
            exam_id=self.exam.id,
            status="IN_PROGRESS",
            started_at=datetime.datetime.utcnow()
        )
        db.session.add(attempt)
        db.session.commit()

        r1 = ViolationEngine.process_event(attempt.id, "PHONE_DETECTED", 0.99)
        r2 = ViolationEngine.process_event(attempt.id, "PHONE_DETECTED", 0.99)
        r3 = ViolationEngine.process_event(attempt.id, "PHONE_DETECTED", 0.99)
        self.assertEqual(r1["action"], "WARNING")
        self.assertEqual(r2["action"], "WARNING")
        self.assertEqual(r3["action"], "TERMINATE")

        attempt2 = ExamAttempt(
            student_id=self.student.id,
            exam_id=self.exam.id,
            status="IN_PROGRESS",
            started_at=datetime.datetime.utcnow()
        )
        db.session.add(attempt2)
        db.session.commit()

        f1 = ViolationEngine.process_event(attempt2.id, "HEAD_TURN", 0.99)
        f2 = ViolationEngine.process_event(attempt2.id, "HEAD_TURN", 0.99)
        f3 = ViolationEngine.process_event(attempt2.id, "HEAD_TURN", 0.99)
        f4 = ViolationEngine.process_event(attempt2.id, "HEAD_TURN", 0.99)
        self.assertEqual(f1["action"], "WARNING")
        self.assertEqual(f2["action"], "WARNING")
        self.assertEqual(f3["action"], "WARNING")
        self.assertEqual(f4["action"], "TERMINATE")

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

    def test_question_upload_previews_before_save(self):
        login_res = self.client.post("/api/auth/login", data=json.dumps({
            "email": "admin@test.com",
            "password": "AdminPass123!"
        }), content_type="application/json")
        token = json.loads(login_res.data)["token"]
        headers = {"Authorization": f"Bearer {token}"}
        csv_data = "question,option_a,option_b,correct_answer,marks\nWhat is 3 + 3?,5,6,B,2\n"

        preview = self.client.post(
            f"/api/exams/{self.exam.id}/questions/upload",
            data={"file": (io.BytesIO(csv_data.encode()), "questions.csv")},
            headers=headers,
            content_type="multipart/form-data"
        )
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(len(preview.json["questions"]), 1)
        self.assertEqual(Question.query.filter_by(exam_id=self.exam.id).count(), 1)

        reviewed = preview.json["questions"]
        reviewed[0]["question_text"] = "What is 4 + 4?"
        saved = self.client.put(
            f"/api/exams/{self.exam.id}/questions/bulk",
            data=json.dumps({"questions": reviewed}),
            headers={**headers, "Content-Type": "application/json"}
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(Question.query.filter_by(exam_id=self.exam.id).count(), 1)
        self.assertEqual(Question.query.filter_by(exam_id=self.exam.id).first().question_text, "What is 4 + 4?")

    def test_exact_parse_save_endpoints_and_question_count(self):
        login_res = self.client.post("/api/auth/login", data=json.dumps({
            "email": "admin@test.com",
            "password": "AdminPass123!"
        }), content_type="application/json")
        token = json.loads(login_res.data)["token"]
        headers = {"Authorization": f"Bearer {token}"}
        csv_data = "question,option_a,option_b,correct_answer,marks\nWhich is larger?,10,20,B,1\n"

        parsed = self.client.post(
            "/api/parse-questions-file",
            data={"file": (io.BytesIO(csv_data.encode()), "questions.csv")},
            headers=headers,
            content_type="multipart/form-data"
        )
        self.assertEqual(parsed.status_code, 200)
        self.assertEqual(Question.query.filter_by(exam_id=self.exam.id).count(), 1)

        saved = self.client.post(
            f"/api/exams/{self.exam.id}/save-questions",
            data=json.dumps({"questions": parsed.json["questions"]}),
            headers={**headers, "Content-Type": "application/json"}
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json["question_count"], 1)

        exams = self.client.get("/api/exams", headers=headers)
        self.assertEqual(exams.status_code, 200)
        exam_data = next(exam for exam in exams.json["exams"] if exam["id"] == self.exam.id)
        self.assertEqual(exam_data["question_count"], 1)

    def test_question_file_upload_supports_xlsx_and_detailed_errors(self):
        from openpyxl import Workbook

        login_res = self.client.post("/api/auth/login", data=json.dumps({
            "email": "admin@test.com",
            "password": "AdminPass123!"
        }), content_type="application/json")
        token = json.loads(login_res.data)["token"]
        headers = {"Authorization": f"Bearer {token}"}

        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Question Text", "Option A", "Option B", "Correct Answer", "Points"])
        sheet.append(["Pick the larger number", "10", "20", "B", 2])
        workbook_data = io.BytesIO()
        workbook.save(workbook_data)
        workbook_data.seek(0)

        parsed = self.client.post(
            "/api/parse-questions-file",
            data={"file": (workbook_data, "questions.xlsx")},
            headers=headers,
            content_type="multipart/form-data"
        )
        self.assertEqual(parsed.status_code, 200)
        self.assertEqual(parsed.json["questions"][0]["question_text"], "Pick the larger number")
        self.assertEqual(parsed.json["questions"][0]["options"][1]["text"], "20")

        unsupported = self.client.post(
            "/api/parse-questions-file",
            data={"file": (io.BytesIO(b"question"), "questions.txt")},
            headers=headers,
            content_type="multipart/form-data"
        )
        self.assertEqual(unsupported.status_code, 400)
        self.assertEqual(unsupported.json["error_code"], "UNSUPPORTED_FILE_TYPE")
        self.assertIn("supported_types", unsupported.json["details"])

        malformed = self.client.post(
            "/api/parse-questions-file",
            data={"file": (io.BytesIO(b"not an xlsx workbook"), "questions.xlsx")},
            headers=headers,
            content_type="multipart/form-data"
        )
        self.assertEqual(malformed.status_code, 400)
        self.assertIn(malformed.json["error_code"], {"INVALID_EXCEL_FILE", "EXCEL_READ_FAILED"})
        self.assertIn("message", malformed.json)

if __name__ == "__main__":
    unittest.main()
