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

    def test_drive_course_registration_and_access_isolation(self):
        """Tests that students can register with course='Drive' and exams created for Drive are accessible only to them."""
        # 1. Register student with Drive course
        res = self.client.post("/api/auth/register-student", json={
            "first_name": "Drive Candidate",
            "email": "drive_student@test.com",
            "course": "Drive",
            "password": "Password123"
        })
        self.assertEqual(res.status_code, 201)
        
        drive_user = User.query.filter_by(email="drive_student@test.com").first()
        self.assertIsNotNone(drive_user)
        self.assertEqual(drive_user.course, "Drive")
        drive_user.registration_status = "APPROVED"
        db.session.commit()

        # 2. Login admin to create Drive exam
        login_res = self.client.post("/api/auth/login", json={
            "email": "admin@test.com",
            "password": "AdminPass123!"
        })
        admin_token = login_res.json["token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # Create Drive exam
        res_exam = self.client.post("/api/exams", json={
            "title": "Campus Drive Assessment",
            "course": "Drive",
            "duration_minutes": 45
        }, headers=admin_headers)
        self.assertEqual(res_exam.status_code, 201)
        drive_exam_id = res_exam.json["exam"]["id"]

        # Create Python exam
        res_py_exam = self.client.post("/api/exams", json={
            "title": "Python Core Exam",
            "course": "Python",
            "duration_minutes": 60
        }, headers=admin_headers)
        self.assertEqual(res_py_exam.status_code, 201)
        py_exam_id = res_py_exam.json["exam"]["id"]

        # 3. Login as Drive student and verify exam accessibility
        drive_login = self.client.post("/api/auth/login", json={
            "email": "drive_student@test.com",
            "password": "Password123"
        })
        drive_token = drive_login.json["token"]
        drive_headers = {"Authorization": f"Bearer {drive_token}"}

        # Drive student fetching all exams - should only see Drive exam, not Python exam
        exams_res = self.client.get("/api/exams", headers=drive_headers)
        self.assertEqual(exams_res.status_code, 200)
        accessible_ids = [e["id"] for e in exams_res.json["exams"]]
        self.assertIn(drive_exam_id, accessible_ids)
        self.assertNotIn(py_exam_id, accessible_ids)

        # Drive student trying to access Python exam directly by ID -> 403
        py_detail = self.client.get(f"/api/exams/{py_exam_id}", headers=drive_headers)
        self.assertEqual(py_detail.status_code, 403)
        self.assertEqual(py_detail.json["error_code"], "EXAM_COURSE_MISMATCH")

        # Drive student accessing Drive exam -> 200
        drive_detail = self.client.get(f"/api/exams/{drive_exam_id}", headers=drive_headers)
        self.assertEqual(drive_detail.status_code, 200)

        # 4. Standard Python student attempting to access Drive exam -> 403
        self.student.course = "Python"
        self.student.registration_status = "APPROVED"
        db.session.commit()

        py_login = self.client.post("/api/auth/login", json={
            "email": "student@test.com",
            "password": "StudentPass123!"
        })
        py_token = py_login.json["token"]
        py_headers = {"Authorization": f"Bearer {py_token}"}

        # Python student fetching exams - should NOT see Drive exam
        py_exams = self.client.get("/api/exams", headers=py_headers)
        py_accessible_ids = [e["id"] for e in py_exams.json["exams"]]
        self.assertNotIn(drive_exam_id, py_accessible_ids)

        # Python student attempting to fetch Drive exam directly -> 403
        forbidden_drive = self.client.get(f"/api/exams/{drive_exam_id}", headers=py_headers)
        self.assertEqual(forbidden_drive.status_code, 403)
        self.assertEqual(forbidden_drive.json["error_code"], "EXAM_COURSE_MISMATCH")

    def test_delete_student_and_allow_re_registration(self):
        """Tests that deleting a student permanently removes their record and allows re-registration."""
        # 1. Register a student
        reg_res = self.client.post("/api/auth/register-student", json={
            "first_name": "Temporary Student",
            "email": "temp_student@test.com",
            "course": "Python",
            "password": "Password123"
        })
        self.assertEqual(reg_res.status_code, 201)
        temp_user = User.query.filter_by(email="temp_student@test.com").first()
        self.assertIsNotNone(temp_user)
        user_id = temp_user.id

        # 2. Login admin to delete the student
        login_res = self.client.post("/api/auth/login", json={
            "email": "admin@test.com",
            "password": "AdminPass123!"
        })
        admin_token = login_res.json["token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        del_res = self.client.delete(f"/api/admin/registrations/{user_id}", headers=admin_headers)
        self.assertEqual(del_res.status_code, 200)

        # 3. Verify user is completely removed from DB
        deleted_user = User.query.filter_by(email="temp_student@test.com").first()
        self.assertIsNone(deleted_user)

        # 4. Verify candidate can register again with the same email
        rereg_res = self.client.post("/api/auth/register-student", json={
            "first_name": "Re-registered Student",
            "email": "temp_student@test.com",
            "course": "Drive",
            "password": "NewPassword456"
        })
        self.assertEqual(rereg_res.status_code, 201)
        fresh_user = User.query.filter_by(email="temp_student@test.com").first()
        self.assertIsNotNone(fresh_user)
        self.assertEqual(fresh_user.first_name, "Re-registered Student")
        self.assertEqual(fresh_user.course, "Drive")

    def test_student_phone_registration_and_admin_view(self):
        """Tests that phone number is recorded during registration and displayed in admin registrations."""
        # 1. Register candidate with phone number
        reg_res = self.client.post("/api/auth/register-student", json={
            "first_name": "Phone Test Student",
            "email": "phone_test@test.com",
            "phone": "9876543210",
            "course": "Python",
            "password": "Password123"
        })
        self.assertEqual(reg_res.status_code, 201)
        user = User.query.filter_by(email="phone_test@test.com").first()
        self.assertIsNotNone(user)
        self.assertEqual(user.phone, "9876543210")

        # 2. Login admin and fetch registrations list
        login_res = self.client.post("/api/auth/login", json={
            "email": "admin@test.com",
            "password": "AdminPass123!"
        })
        admin_token = login_res.json["token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        admin_res = self.client.get("/api/admin/registrations", headers=admin_headers)
        self.assertEqual(admin_res.status_code, 200)
        found = next((r for r in admin_res.json["registrations"] if r["email"] == "phone_test@test.com"), None)
        self.assertIsNotNone(found)
        self.assertEqual(found["phone"], "9876543210")

    def test_export_marks_pdf_replaces_percentage_with_violations_count(self):
        """Tests that the exported Marks List PDF includes the candidate's violation count instead of percentage."""
        from backend.services.pdf_generator import StudentExamMarksPDFService
        
        # 1. Create completed attempt with violations and candidate phone
        self.student.phone = "9876543210"
        db.session.commit()

        attempt = ExamAttempt(
            student_id=self.student.id,
            exam_id=self.exam.id,
            status="SUBMITTED"
        )
        db.session.add(attempt)
        db.session.commit()

        v1 = ViolationLog(
            attempt_id=attempt.id,
            violation_type="HEAD_POSE_RIGHT",
            severity="MEDIUM"
        )
        v2 = ViolationLog(
            attempt_id=attempt.id,
            violation_type="TAB_SWITCH",
            severity="HIGH"
        )
        db.session.add_all([v1, v2])
        db.session.commit()

        # 2. Test PDF service generation directly
        pdf_bytes = StudentExamMarksPDFService.generate_exam_marks_pdf(self.exam.id)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertIn(b"Violations", pdf_bytes)
        self.assertIn(b"Phone", pdf_bytes)
        self.assertIn(b"9876543210", pdf_bytes)

        # 3. Test HTTP export endpoint
        login_res = self.client.post("/api/auth/login", json={
            "email": "admin@test.com",
            "password": "AdminPass123!"
        })
        admin_token = login_res.json["token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        resp = self.client.get(f"/api/admin/reports/export-pdf?exam_id={self.exam.id}", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content_type, "application/pdf")
        self.assertTrue(resp.data.startswith(b"%PDF-"))

    def test_student_aptitude_course_registration(self):
        """Tests that students can register for Aptitude course and are stored correctly."""
        reg_res = self.client.post("/api/auth/register-student", json={
            "first_name": "Aptitude Candidate",
            "email": "aptitude_candidate@test.com",
            "phone": "9123456780",
            "course": "Aptitude",
            "password": "Password123"
        })
        self.assertEqual(reg_res.status_code, 201)
        user = User.query.filter_by(email="aptitude_candidate@test.com").first()
        self.assertIsNotNone(user)
        self.assertEqual(user.course, "Aptitude")
        self.assertEqual(user.phone, "9123456780")

    def test_presentation_download_endpoints(self):
        """Tests that the presentation download endpoints (PDF, PPTX, HTML) stream files successfully."""
        # 1. Download Presentation PDF
        pdf_res = self.client.get("/api/admin/presentation/download-pdf")
        self.assertEqual(pdf_res.status_code, 200)
        self.assertEqual(pdf_res.content_type, "application/pdf")
        self.assertTrue(pdf_res.data.startswith(b"%PDF-"))
        self.assertIn(b"AI-Proctored Secure Examination System", pdf_res.data)

        # 2. Download Presentation HTML
        html_res = self.client.get("/api/admin/presentation/download-html")
        self.assertEqual(html_res.status_code, 200)
        self.assertIn("text/html", html_res.content_type)
        self.assertIn(b"SecureExam", html_res.data)

        # 3. Download Presentation PPTX (returns PPTX or PDF fallback)
        pptx_res = self.client.get("/api/admin/presentation/download-pptx")
        self.assertEqual(pptx_res.status_code, 200)
        self.assertTrue(len(pptx_res.data) > 0)

    def test_delete_exam_cascades_exam_data_while_preserving_student_registrations(self):
        """
        Tests that deleting an exam:
        1. Cascades and deletes all attempts, student answers, violation logs, results, and access requests for that exam.
        2. Removes the exam from the admin reports 'exams' dropdown list.
        3. Preserves the student User record in the registrations/students section completely intact.
        """
        # 1. Admin Login
        login_res = self.client.post("/api/auth/login", json={
            "email": "admin@test.com",
            "password": "AdminPass123!"
        })
        admin_token = login_res.json["token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # 2. Create student attempt, answer, violation, result, and access request
        from backend.models import ExamAccess, StudentAnswer, EvidenceRecord
        access = ExamAccess(student_id=self.student.id, exam_id=self.exam.id, approved=True)
        db.session.add(access)

        attempt = ExamAttempt(student_id=self.student.id, exam_id=self.exam.id, status="SUBMITTED")
        db.session.add(attempt)
        db.session.commit()

        ans = StudentAnswer(attempt_id=attempt.id, question_id=self.q1.id, chosen_option="B", is_correct=True, marks_awarded=2.0)
        viol = ViolationLog(attempt_id=attempt.id, violation_type="TAB_SWITCH", severity="HIGH")
        res_obj = Result(attempt_id=attempt.id, total_score=2.0, percentage=100.0, passed=True)
        db.session.add_all([ans, viol, res_obj])
        db.session.commit()

        # Verify reports initially contains the exam and attempt
        reports_before = self.client.get(f"/api/admin/reports?exam_id={self.exam.id}", headers=admin_headers)
        self.assertEqual(reports_before.status_code, 200)
        exam_ids_before = [e["id"] for e in reports_before.json["exams"]]
        self.assertIn(self.exam.id, exam_ids_before)
        self.assertEqual(len(reports_before.json["attempts"]), 1)

        # 3. Delete the exam
        del_res = self.client.delete(f"/api/exams/{self.exam.id}", headers=admin_headers)
        self.assertEqual(del_res.status_code, 200)
        self.assertTrue(del_res.json["success"])

        # 4. Verify all student exam-related data for this exam is deleted
        self.assertIsNone(Exam.query.get(self.exam.id))
        self.assertEqual(ExamAttempt.query.filter_by(exam_id=self.exam.id).count(), 0)
        self.assertEqual(StudentAnswer.query.filter_by(attempt_id=attempt.id).count(), 0)
        self.assertEqual(ViolationLog.query.filter_by(attempt_id=attempt.id).count(), 0)
        self.assertEqual(Result.query.filter_by(attempt_id=attempt.id).count(), 0)
        self.assertEqual(ExamAccess.query.filter_by(exam_id=self.exam.id).count(), 0)

        # 5. Verify the deleted exam is NOT present in /api/admin/reports exam selector
        reports_after = self.client.get("/api/admin/reports", headers=admin_headers)
        self.assertEqual(reports_after.status_code, 200)
        exam_ids_after = [e["id"] for e in reports_after.json["exams"]]
        self.assertNotIn(self.exam.id, exam_ids_after)

        # 6. Verify export PDF for deleted exam fails
        pdf_res = self.client.get(f"/api/admin/reports/export-pdf?exam_id={self.exam.id}", headers=admin_headers)
        self.assertEqual(pdf_res.status_code, 404)

        # 7. CRITICAL: Verify student registration record in users table is STILL INTACT
        student_user = User.query.get(self.student.id)
        self.assertIsNotNone(student_user)
        self.assertEqual(student_user.email, "student@test.com")
        self.assertEqual(student_user.role, "student")

        # Verify student still appears in registrations endpoint
        reg_res = self.client.get("/api/admin/registrations", headers=admin_headers)
        self.assertEqual(reg_res.status_code, 200)
        student_emails = [s["email"] for s in reg_res.json["registrations"]]
        self.assertIn("student@test.com", student_emails)

    def test_create_exam_aptitude_course_replaces_drive(self):
        """Tests that exams can be created with Aptitude course, and Drive is cleanly mapped to Aptitude."""
        login_res = self.client.post("/api/auth/login", json={
            "email": "admin@test.com",
            "password": "AdminPass123!"
        })
        admin_token = login_res.json["token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # 1. Create exam with Aptitude
        res1 = self.client.post("/api/exams", json={
            "title": "Aptitude Assessment",
            "description": "General quantitative & logical aptitude",
            "duration_minutes": 45,
            "course": "Aptitude"
        }, headers=admin_headers)
        self.assertEqual(res1.status_code, 201)
        self.assertEqual(res1.json["exam"]["course"], "Aptitude")

        # 2. Create exam with legacy Drive -> auto mapped to Aptitude
        res2 = self.client.post("/api/exams", json={
            "title": "Drive Assessment",
            "description": "Legacy drive test",
            "duration_minutes": 45,
            "course": "Drive"
        }, headers=admin_headers)
        self.assertEqual(res2.status_code, 201)
        self.assertEqual(res2.json["exam"]["course"], "Aptitude")

    def test_delete_unwanted_questions_and_save_exam_foreign_key_safe(self):
        """
        Tests deleting unwanted questions from an existing exam and saving it.
        Verifies that PostgreSQL foreign key constraints on question_options and student_answers
        do not cause 'Failed to save questions'.
        """
        login_res = self.client.post("/api/auth/login", json={
            "email": "admin@test.com",
            "password": "AdminPass123!"
        })
        admin_token = login_res.json["token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # 1. Fetch current questions (self.q1 exists from seed data)
        get_res = self.client.get(f"/api/exams/{self.exam.id}/questions", headers=admin_headers)
        self.assertEqual(get_res.status_code, 200)
        current_qs = get_res.json["questions"]
        self.assertGreater(len(current_qs), 0)

        # 2. Add a second question with options
        from backend.models import Question, QuestionOption, StudentAnswer, ExamAttempt
        q2 = Question(
            exam_id=self.exam.id,
            question_text="Unwanted question to be deleted?",
            question_type="MCQ",
            marks=1.0,
            correct_answer="A"
        )
        db.session.add(q2)
        db.session.flush()
        db.session.add(QuestionOption(question_id=q2.id, option_letter="A", option_text="Option A"))
        db.session.add(QuestionOption(question_id=q2.id, option_letter="B", option_text="Option B"))
        db.session.commit()

        # Add a student answer referencing q2 to test foreign key safety
        att = ExamAttempt.query.filter_by(exam_id=self.exam.id).first()
        if not att:
            att = ExamAttempt(student_id=self.student.id, exam_id=self.exam.id, status="IN_PROGRESS")
            db.session.add(att)
            db.session.commit()
        ans = StudentAnswer(attempt_id=att.id, question_id=q2.id, chosen_option="A")
        db.session.add(ans)
        db.session.commit()

        # 3. Simulate the user deleting q2 from the review list and sending only q1 to save-questions
        save_payload = {
            "questions": [
                {
                    "id": self.q1.id,
                    "question_text": self.q1.question_text,
                    "question_type": self.q1.question_type,
                    "correct_answer": self.q1.correct_answer,
                    "marks": self.q1.marks,
                    "negative_marks": self.q1.negative_marks,
                    "options": [{"letter": opt.option_letter, "text": opt.option_text} for opt in self.q1.options]
                }
            ]
        }

        # 4. Save reviewed questions
        save_res = self.client.post(f"/api/exams/{self.exam.id}/save-questions", json=save_payload, headers=admin_headers)
        self.assertEqual(save_res.status_code, 200)
        self.assertTrue(save_res.json["success"])
        self.assertEqual(save_res.json["question_count"], 1)

        # 5. Verify q2, its options, and answers were cleanly removed
        self.assertIsNone(Question.query.get(q2.id))
        self.assertEqual(QuestionOption.query.filter_by(question_id=q2.id).count(), 0)
        self.assertEqual(StudentAnswer.query.filter_by(question_id=q2.id).count(), 0)
        # Verify q1 is still present and valid
        self.assertIsNotNone(Question.query.get(self.q1.id))

    def test_admin_update_student_course(self):
        """Tests that an admin can update a student's course (e.g. if they mistakenly enrolled in the wrong course)."""
        from backend.models import AuditLog

        # Admin login
        login_res = self.client.post("/api/auth/login", json={
            "email": "admin@test.com",
            "password": "AdminPass123!"
        })
        admin_token = login_res.json["token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # Student login token (for unauthorized check)
        stu_login_res = self.client.post("/api/auth/login", json={
            "email": "student@test.com",
            "password": "StudentPass123!"
        })
        student_token = stu_login_res.json["token"]
        student_headers = {"Authorization": f"Bearer {student_token}"}

        # Ensure student initially has Python
        self.student.course = "Python"
        db.session.commit()

        # 1. Admin updates student course to Aptitude
        res1 = self.client.put(f"/api/admin/registrations/{self.student.id}/course", json={"course": "Aptitude"}, headers=admin_headers)
        self.assertEqual(res1.status_code, 200)
        self.assertTrue(res1.json["success"])
        self.assertEqual(res1.json["student"]["course"], "Aptitude")

        # Verify DB updated
        stu_db = User.query.get(self.student.id)
        self.assertEqual(stu_db.course, "Aptitude")

        # Verify AuditLog logged
        log = AuditLog.query.filter_by(user_id=self.student.id, action="STUDENT_COURSE_UPDATED").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.details["old_course"], "Python")
        self.assertEqual(log.details["new_course"], "Aptitude")

        # 2. Admin updates student course to Java via PATCH
        res2 = self.client.patch(f"/api/admin/registrations/{self.student.id}/course", json={"course": "Java"}, headers=admin_headers)
        self.assertEqual(res2.status_code, 200)
        self.assertTrue(res2.json["success"])
        self.assertEqual(User.query.get(self.student.id).course, "Java")

        # 3. Invalid course returns 400
        res_inv = self.client.put(f"/api/admin/registrations/{self.student.id}/course", json={"course": "InvalidCourse123"}, headers=admin_headers)
        self.assertEqual(res_inv.status_code, 400)
        self.assertFalse(res_inv.json["success"])

        # 4. Student role is forbidden (403)
        res_forbidden = self.client.put(f"/api/admin/registrations/{self.student.id}/course", json={"course": "Python"}, headers=student_headers)
        self.assertEqual(res_forbidden.status_code, 403)

        # 5. Non-existent student ID returns 404
        res_404 = self.client.put("/api/admin/registrations/99999/course", json={"course": "Python"}, headers=admin_headers)
        self.assertEqual(res_404.status_code, 404)

    def test_auto_submit_on_timer_completion_marks_submitted_not_expired(self):
        """Tests that when an exam timer completes, the attempt is marked as SUBMITTED (not EXPIRED) and auto-evaluated."""
        from backend.models import ExamAttempt, StudentAnswer, Result
        from backend.services.session_manager import SessionManager

        # Admin login
        admin_login = self.client.post("/api/auth/login", json={
            "email": "admin@test.com",
            "password": "AdminPass123!"
        })
        admin_headers = {"Authorization": f"Bearer {admin_login.json['token']}"}

        # Student login
        stu_login = self.client.post("/api/auth/login", json={
            "email": "student@test.com",
            "password": "StudentPass123!"
        })
        student_headers = {"Authorization": f"Bearer {stu_login.json['token']}"}

        # Create student attempt
        attempt = SessionManager.start_session(self.student.id, self.exam.id)
        self.assertEqual(attempt.status, "IN_PROGRESS")

        # Simulate student answering q1
        ans = StudentAnswer(attempt_id=attempt.id, question_id=self.q1.id, chosen_option="B")
        db.session.add(ans)
        db.session.commit()

        # Simulate timer expiry on server: start time 40 minutes ago (duration is 30 mins)
        attempt.started_at = datetime.datetime.utcnow() - datetime.timedelta(minutes=40)
        db.session.commit()

        # 1. Verification of session triggers auto-submit with status SUBMITTED (not EXPIRED)
        is_valid, msg = SessionManager.verify_session(attempt.id, self.student.id, attempt.session_token)
        self.assertFalse(is_valid)
        self.assertEqual(msg, "SESSION_EXPIRED")
        
        # Verify DB attempt status is now SUBMITTED
        att_db = ExamAttempt.query.get(attempt.id)
        self.assertEqual(att_db.status, "SUBMITTED")
        self.assertIsNotNone(att_db.ended_at)

        # 2. Client submit endpoint call returns 200 with SUBMITTED status
        submit_res = self.client.post(f"/api/attempts/{attempt.id}/submit", json={
            "session_token": attempt.session_token
        }, headers=student_headers)
        self.assertEqual(submit_res.status_code, 200)
        self.assertTrue(submit_res.json["success"])
        self.assertEqual(submit_res.json["status"], "SUBMITTED")

        # 3. Status endpoint returns SUBMITTED
        status_res = self.client.get(f"/api/attempts/{attempt.id}/status", headers=student_headers)
        self.assertEqual(status_res.status_code, 200)
        self.assertEqual(status_res.json["status"], "SUBMITTED")

        # 4. In Admin reports, status is SUBMITTED and counted under submitted_count
        reports_res = self.client.get(f"/api/admin/reports?exam_id={self.exam.id}", headers=admin_headers)
        self.assertEqual(reports_res.status_code, 200)
        self.assertEqual(reports_res.json["statistics"]["submitted_count"], 1)
        self.assertEqual(reports_res.json["attempts"][0]["status"], "SUBMITTED")

        # 5. Verify auto-heal: if an attempt had legacy status 'EXPIRED', it auto-heals to 'SUBMITTED'
        att_db.status = "EXPIRED"
        db.session.commit()
        reports_heal_res = self.client.get(f"/api/admin/reports?exam_id={self.exam.id}", headers=admin_headers)
        self.assertEqual(reports_heal_res.json["statistics"]["submitted_count"], 1)
        self.assertEqual(reports_heal_res.json["attempts"][0]["status"], "SUBMITTED")
        # Verify persisted in database
        self.assertEqual(ExamAttempt.query.get(attempt.id).status, "SUBMITTED")

if __name__ == "__main__":
    unittest.main()
