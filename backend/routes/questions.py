import io
import csv
import json
import re
import zipfile
from pathlib import Path
from flask import Blueprint, request, jsonify
from backend.models import db, Exam, Question, QuestionOption, AuditLog
from backend.utils.security import token_required, role_required
from backend.utils.logger import get_logger

logger = get_logger()
questions_bp = Blueprint("questions", __name__)

SUPPORTED_UPLOAD_TYPES = (".csv", ".xlsx", ".xls")


class QuestionFileError(ValueError):
    def __init__(self, message, error_code="QUESTION_FILE_INVALID", details=None):
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def _normalise_header(header):
    """Map common human-readable column names to the import schema."""
    key = re.sub(r"[^a-z0-9]+", "_", str(header or "").strip().lower()).strip("_")
    compact = key.replace("_", "")
    aliases = {
        "question": "question", "questiontext": "question", "prompt": "question", "text": "question",
        "answer": "correct_answer", "correct": "correct_answer", "correctanswer": "correct_answer",
        "correctoption": "correct_answer", "answerkey": "correct_answer", "key": "correct_answer",
        "marks": "marks", "mark": "marks", "points": "marks", "point": "marks", "score": "marks",
        "negativemarks": "negative_marks", "negativemark": "negative_marks", "negativepoints": "negative_marks",
        "questiontype": "question_type", "type": "question_type", "options": "options", "choices": "options"
    }
    if compact in aliases:
        return aliases[compact]
    option_match = re.match(r"^(?:option|opt|choice|answer|ans)_?([a-d1-4])$", key)
    if option_match:
        value = option_match.group(1)
        return f"option_{chr(65 + int(value) - 1) if value.isdigit() else value.upper()}" if value.isdigit() else f"option_{value}"
    return key


def _normalise_row(row):
    return {_normalise_header(key): value for key, value in row.items() if _normalise_header(key)}


def _validate_import_headers(headers, filename):
    headers = set(headers)
    missing = []
    if "question" not in headers:
        missing.append("question/question_text")
    if "correct_answer" not in headers:
        missing.append("correct_answer/answer")
    has_options = "options" in headers or any(f"option_{letter}" in headers for letter in "abcd")
    if missing or not has_options:
        if not has_options:
            missing.append("options or option_a..option_d")
        raise QuestionFileError(
            f"{filename} is missing required columns: {', '.join(missing)}.",
            "INVALID_FILE_HEADERS",
            {"received_headers": sorted(headers), "required_columns": ["question", "correct_answer", "options"]}
        )


def _parse_delimited(raw, filename):
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise QuestionFileError(f"{filename} is not valid UTF-8 CSV data.", "INVALID_FILE_ENCODING") from error
    if not text.strip():
        raise QuestionFileError(f"{filename} is empty.", "EMPTY_FILE")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;|\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.DictReader(io.StringIO(text, newline=""), dialect=dialect))
    if not rows or not rows[0]:
        raise QuestionFileError(f"{filename} does not contain a header row.", "INVALID_FILE_HEADERS")
    normalized_rows = [_normalise_row(row) for row in rows]
    _validate_import_headers(normalized_rows[0].keys(), filename)
    return normalized_rows


def _normalise_question(data):
    """Convert supported import shapes into the question API shape."""
    options = data.get("options", [])
    if isinstance(options, str):
        try:
            options = json.loads(options)
        except (TypeError, ValueError):
            options = [part.strip() for part in options.replace("|", ";").split(";") if part.strip()]
    if isinstance(options, dict):
        options = [{"letter": key, "text": value} for key, value in options.items()]
    if not isinstance(options, list):
        options = []
    if options and isinstance(options[0], str):
        options = [{"letter": chr(65 + index), "text": value} for index, value in enumerate(options[:4])]

    for index, letter in enumerate(("A", "B", "C", "D")):
        value = data.get(f"option_{letter.lower()}") or data.get(f"option{letter}")
        if value and not any(str(option.get("letter", "")).upper() == letter for option in options if isinstance(option, dict)):
            options.append({"letter": letter, "text": str(value).strip()})

    try:
        marks = float(data.get("marks", data.get("points", 1)) or 1)
        negative_marks = float(data.get("negative_marks", 0) or 0)
    except (TypeError, ValueError) as error:
        raise QuestionFileError(
            "Marks and negative marks must be numeric.",
            "INVALID_MARKS",
            {"marks": data.get("marks"), "negative_marks": data.get("negative_marks")}
        ) from error

    normalized = {
        "id": data.get("id"),
        "question_text": str(data.get("question_text", data.get("question", ""))).strip(),
        "question_type": str(data.get("question_type", "MCQ")).strip().upper(),
        "correct_answer": str(data.get("correct_answer", data.get("answer", ""))).strip().upper(),
        "marks": marks,
        "negative_marks": negative_marks,
        "options": [
            {"letter": str(option.get("letter", option.get("option_letter", ""))).strip().upper(),
             "text": str(option.get("text", option.get("option_text", ""))).strip()}
            for option in options if isinstance(option, dict) and option.get("text", option.get("option_text"))
        ]
    }
    return normalized


def _parse_upload(file):
    filename = Path(file.filename or "").name
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_UPLOAD_TYPES:
        raise QuestionFileError(
            f"Unsupported file type '{extension or 'unknown'}'. Upload a CSV, XLSX, or XLS file.",
            "UNSUPPORTED_FILE_TYPE",
            {"filename": filename, "supported_types": list(SUPPORTED_UPLOAD_TYPES)}
        )
    raw = file.read()
    if extension == ".csv":
        return [_normalise_question(row) for row in _parse_delimited(raw, filename)]
    if extension in (".xlsx", ".xls"):
        try:
            if extension == ".xls":
                import xlrd
                workbook = xlrd.open_workbook(file_contents=raw)
                sheet = workbook.sheet_by_index(0)
                rows = [sheet.row_values(index) for index in range(sheet.nrows)]
            else:
                from openpyxl import load_workbook
                rows = list(load_workbook(io.BytesIO(raw), read_only=True, data_only=True).active.values)
        except ImportError as error:
            package = "xlrd" if extension == ".xls" else "openpyxl"
            raise QuestionFileError(f"Excel uploads require the {package} package.", "MISSING_EXCEL_DEPENDENCY") from error
        except (xlrd.XLRDError if extension == ".xls" else zipfile.BadZipFile) as error:
            raise QuestionFileError(f"{filename} is not a valid {extension[1:].upper()} workbook.", "INVALID_EXCEL_FILE") from error
        except (OSError, ValueError, KeyError, IndexError) as error:
            raise QuestionFileError(f"Could not read {filename}: {error}", "EXCEL_READ_FAILED") from error
        if not rows or not rows[0]:
            raise QuestionFileError(f"{filename} does not contain a header row.", "INVALID_FILE_HEADERS")
        headers = [_normalise_header(value) for value in rows[0]]
        _validate_import_headers(headers, filename)
        return [_normalise_question(_normalise_row(dict(zip(headers, row)))) for row in rows[1:] if any(value not in (None, "") for value in row)]


def _validate_questions(questions):
    if not isinstance(questions, list) or not questions:
        raise ValueError("At least one question is required")
    parsed = [_normalise_question(question) for question in questions]
    for question in parsed:
        if not question["question_text"] or not question["correct_answer"]:
            raise ValueError("Every question needs question text and a correct answer")
        if question["question_type"] == "MCQ" and len(question["options"]) < 2:
            raise ValueError("Every multiple-choice question needs at least two options")
    return parsed


def _add_question_record(exam_id, data):
    question = Question(exam_id=exam_id, question_text=data["question_text"], question_type=data["question_type"],
                        marks=data["marks"], negative_marks=data["negative_marks"], correct_answer=data["correct_answer"])
    db.session.add(question)
    db.session.flush()
    for option in data["options"]:
        db.session.add(QuestionOption(question_id=question.id, option_letter=option["letter"], option_text=option["text"]))
    return question


@questions_bp.route("/parse-questions-file", methods=["POST"])
@token_required
@role_required(["admin"])
def parse_questions_file():
    uploaded_file = request.files.get("file")
    if not uploaded_file or not uploaded_file.filename:
        return jsonify({"success": False, "error_code": "NO_FILE", "message": "A question file is required."}), 400
    try:
        questions = _validate_questions(_parse_upload(uploaded_file))
        return jsonify({
            "success": True,
            "message": f"Parsed {len(questions)} questions. Review them before saving.",
            "questions": questions
        }), 200
    except QuestionFileError as error:
        return jsonify({
            "success": False,
            "error_code": error.error_code,
            "message": str(error),
            "details": error.details
        }), 400
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        logger.warning("Question file parsing failed: %s", error)
        return jsonify({
            "success": False,
            "error_code": "QUESTION_FILE_INVALID",
            "message": f"Could not parse the uploaded question file: {error}",
            "details": {"exception": type(error).__name__}
        }), 400
    except Exception as error:
        logger.exception("Unexpected question file parsing failure")
        return jsonify({
            "success": False,
            "error_code": "QUESTION_FILE_PROCESSING_FAILED",
            "message": "The question file could not be processed.",
            "details": {"exception": type(error).__name__}
        }), 400


@questions_bp.route("/exams/<int:exam_id>/save-questions", methods=["POST"])
@token_required
@role_required(["admin"])
def save_questions(exam_id):
    user = request.current_user
    if not Exam.query.filter_by(id=exam_id, is_deleted=False).first():
        return jsonify({"success": False, "error_code": "EXAM_NOT_FOUND", "message": "Exam not found."}), 404
    try:
        from backend.models import StudentAnswer
        questions = _validate_questions((request.get_json() or {}).get("questions"))
        
        # Load existing questions in database for this exam
        existing = {question.id: question for question in Question.query.filter_by(exam_id=exam_id).all()}
        retained_ids = set()

        for data in questions:
            question_id = data.get("id")
            question = existing.get(question_id) if question_id else None
            if question:
                # Update existing question in-place
                retained_ids.add(question.id)
                question.question_text = data["question_text"]
                question.question_type = data["question_type"]
                question.marks = data["marks"]
                question.negative_marks = data["negative_marks"]
                question.correct_answer = data["correct_answer"]
                question.options.clear()
                for option in data.get("options", []):
                    question.options.append(QuestionOption(
                        option_letter=option["letter"],
                        option_text=option["text"]
                    ))
            else:
                # Add new question record
                new_q = _add_question_record(exam_id, data)
                retained_ids.add(new_q.id)

        # Safely remove unwanted/deleted questions and their foreign key dependencies
        unwanted_ids = [q_id for q_id in existing.keys() if q_id not in retained_ids]
        if unwanted_ids:
            # 1. Clean up StudentAnswer records referencing unwanted questions
            StudentAnswer.query.filter(StudentAnswer.question_id.in_(unwanted_ids)).delete(synchronize_session=False)
            # 2. Clean up QuestionOption records referencing unwanted questions
            QuestionOption.query.filter(QuestionOption.question_id.in_(unwanted_ids)).delete(synchronize_session=False)
            # 3. Clean up unwanted Question rows
            Question.query.filter(Question.id.in_(unwanted_ids)).delete(synchronize_session=False)

        audit = AuditLog(user_id=user.id, action="QUESTIONS_REVIEWED_AND_SAVED", ip_address=request.remote_addr,
                         user_agent=request.headers.get("User-Agent"))
        audit.details = {"exam_id": exam_id, "questions_count": len(questions)}
        db.session.add(audit)
        db.session.commit()
        
        saved = Question.query.filter_by(exam_id=exam_id).all()
        return jsonify({
            "success": True,
            "message": "Questions saved to the exam.",
            "question_count": len(saved),
            "questions": [question.to_dict(include_correct=True) for question in saved]
        }), 200
    except (ValueError, TypeError) as error:
        db.session.rollback()
        return jsonify({"success": False, "error_code": "INVALID_QUESTIONS", "message": str(error)}), 400
    except Exception as error:
        db.session.rollback()
        logger.error(f"Error saving questions for exam {exam_id}: {error}", exc_info=True)
        return jsonify({"success": False, "error_code": "QUESTION_SAVE_FAILED", "message": f"Failed to save questions: {str(error)}"}), 500

@questions_bp.route("/exams/<int:exam_id>/questions", methods=["GET"])
@token_required
def get_exam_questions(exam_id):
    user = request.current_user
    exam = Exam.query.filter_by(id=exam_id, is_deleted=False).first()
    
    if not exam:
        return jsonify({
            "success": False,
            "error_code": "EXAM_NOT_FOUND",
            "message": f"Exam with ID {exam_id} not found."
        }), 404

    # Students shouldn't view questions of inactive exams
    if user.role != "admin" and not exam.is_active:
        return jsonify({
            "success": False,
            "error_code": "EXAM_INACTIVE",
            "message": "This examination is not active."
        }), 403

    questions = Question.query.filter_by(exam_id=exam_id).all()
    
    # Crucial security requirement: Redact correct answers for students
    include_correct = (user.role == "admin")
    
    # Shuffle questions stably for student attempts to prevent collusion
    if user.role != "admin":
        from backend.models import ExamAttempt
        import random
        
        attempt = ExamAttempt.query.filter_by(student_id=user.id, exam_id=exam_id).first()
        seed_val = attempt.id if attempt else user.id
        
        questions_list = list(questions)
        random.seed(seed_val)
        random.shuffle(questions_list)
        questions = questions_list
    
    return jsonify({
        "success": True,
        "questions": [q.to_dict(include_correct=include_correct) for q in questions]
    }), 200

@questions_bp.route("/exams/<int:exam_id>/questions", methods=["POST"])
@token_required
@role_required(["admin"])
def add_question(exam_id):
    user = request.current_user
    exam = Exam.query.get(exam_id)
    
    if not exam:
        return jsonify({
            "success": False,
            "error_code": "EXAM_NOT_FOUND",
            "message": f"Exam with ID {exam_id} not found."
        }), 404

    data = request.get_json() or {}
    question_text = data.get("question_text")
    question_type = data.get("question_type", "MCQ")
    correct_answer = data.get("correct_answer")
    marks = data.get("marks", 1.0)
    negative_marks = data.get("negative_marks", 0.0)
    options_list = data.get("options", []) # List of options like [{"letter": "A", "text": "foo"}]

    if not question_text or not correct_answer:
        return jsonify({
            "success": False,
            "error_code": "INVALID_INPUT",
            "message": "Question text and correct answer are required."
        }), 400

    try:
        # Create question
        question = Question(
            exam_id=exam_id,
            question_text=question_text,
            question_type=question_type,
            marks=float(marks),
            negative_marks=float(negative_marks),
            correct_answer=str(correct_answer)
        )
        db.session.add(question)
        db.session.flush() # Fetch question.id

        # If MCQ, process options
        if question_type == "MCQ" and options_list:
            for opt in options_list:
                letter = opt.get("letter")
                text = opt.get("text")
                if letter and text:
                    option = QuestionOption(
                        question_id=question.id,
                        option_letter=letter,
                        option_text=text
                    )
                    db.session.add(option)

        # Audit log creation
        audit = AuditLog(
            user_id=user.id,
            action="QUESTION_ADDED",
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent")
        )
        audit.details = {"exam_id": exam_id, "question_id": question.id}
        db.session.add(audit)
        
        db.session.commit()
        logger.info(f"Question added to exam {exam_id} by admin {user.email}")
        
        return jsonify({
            "success": True,
            "message": "Question added successfully.",
            "question": question.to_dict(include_correct=True)
        }), 201

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error adding question: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "QUESTION_CREATION_FAILED",
            "message": "An error occurred while creating the question."
        }), 500

@questions_bp.route("/exams/<int:exam_id>/questions/legacy-upload", methods=["POST"])
@token_required
@role_required(["admin"])
def upload_questions_csv(exam_id):
    user = request.current_user
    exam = Exam.query.get(exam_id)
    
    if not exam:
        return jsonify({
            "success": False,
            "error_code": "EXAM_NOT_FOUND",
            "message": f"Exam with ID {exam_id} not found."
        }), 404

    # Validate file presence
    if "file" not in request.files:
        return jsonify({
            "success": False,
            "error_code": "NO_FILE",
            "message": "CSV file upload is required."
        }), 400
        
    file = request.files["file"]
    if file.filename == "":
        return jsonify({
            "success": False,
            "error_code": "EMPTY_FILE",
            "message": "Selected file is empty."
        }), 400

    # Validate file extension
    if not file.filename.endswith(".csv"):
        return jsonify({
            "success": False,
            "error_code": "INVALID_FILE_TYPE",
            "message": "Only CSV files are allowed."
        }), 400

    try:
        # Read and parse CSV safely (utf-8-sig strips potential BOM signatures)
        stream = io.StringIO(file.stream.read().decode("utf-8-sig"), newline="")
        csv_reader = csv.DictReader(stream)
        
        # Normalize and clean CSV headers (strip spaces, lowercase, replace symbols, resolve aliases)
        if csv_reader.fieldnames:
            normalized_fieldnames = []
            for name in csv_reader.fieldnames:
                if not name:
                    normalized_fieldnames.append("")
                    continue
                # Lowercase, strip, and replace spaces or hyphens with underscores
                clean_name = name.strip().lower().replace(" ", "_").replace("-", "_")
                
                # Check for explicit priority columns first
                if clean_name in ["answer", "correct", "correct_ans", "key", "correct_answer"]:
                    clean_name = "correct_answer"
                elif clean_name in ["mark", "point", "points", "marks"]:
                    clean_name = "marks"
                elif clean_name in ["neg_mark", "negative_mark", "neg_marks", "negative_marks"]:
                    clean_name = "negative_marks"
                elif "question" in clean_name:
                    clean_name = "question"
                else:
                    # Resolve options using substring and suffix matching
                    # Strip dots and underscores to compare letters/numbers cleanly
                    norm = clean_name.replace(".", "").replace("_", "").strip()
                    if any(x in norm for x in ["option", "opt", "choice", "ans", "op"]):
                        if norm.endswith("a") or norm.endswith("1"):
                            clean_name = "option_a"
                        elif norm.endswith("b") or norm.endswith("2"):
                            clean_name = "option_b"
                        elif norm.endswith("c") or norm.endswith("3"):
                            clean_name = "option_c"
                        elif norm.endswith("d") or norm.endswith("4"):
                            clean_name = "option_d"
                    
                normalized_fieldnames.append(clean_name)
            csv_reader.fieldnames = normalized_fieldnames
            
        # Verify required headers
        headers = csv_reader.fieldnames or []
        
        if "question" not in headers:
            logger.error(f"CSV import failed: Missing 'question' header. Received headers: {headers}")
            return jsonify({
                "success": False,
                "error_code": "INVALID_CSV_HEADERS",
                "message": f"Missing required column header: 'question'. Parsed headers: {headers}"
            }), 400
            
        if "correct_answer" not in headers:
            logger.error(f"CSV import failed: Missing 'correct_answer' header. Received headers: {headers}")
            return jsonify({
                "success": False,
                "error_code": "INVALID_CSV_HEADERS",
                "message": f"Missing required column header: 'correct_answer'. Parsed headers: {headers}"
            }), 400

        # Check if we have either individual option columns or a single "options" column
        has_individual_options = all(opt in headers for opt in ["option_a", "option_b", "option_c", "option_d"])
        has_single_options_col = "options" in headers
        
        if not has_individual_options and not has_single_options_col:
            logger.error(f"CSV import failed: Missing options columns. Received headers: {headers}")
            return jsonify({
                "success": False,
                "error_code": "INVALID_CSV_HEADERS",
                "message": f"Missing options columns. Please provide either 'option_a', 'option_b', 'option_c', 'option_d' or a single 'options' column. Parsed headers: {headers}"
            }), 400

        added_count = 0
        for row in csv_reader:
            question_text = row.get("question")
            correct_ans = row.get("correct_answer")
            
            # Safe parsing for marks (default to 1.0 if missing or invalid)
            marks_val = row.get("marks")
            try:
                marks = float(marks_val) if marks_val is not None else 1.0
            except ValueError:
                marks = 1.0
                
            neg_val = row.get("negative_marks")
            try:
                neg_marks = float(neg_val) if neg_val is not None else 0.0
            except ValueError:
                neg_marks = 0.0
            
            if not question_text or not correct_ans:
                continue # Skip row if invalid
                
            # Create question record
            question = Question(
                exam_id=exam_id,
                question_text=question_text,
                question_type="MCQ",
                marks=marks,
                negative_marks=neg_marks,
                correct_answer=str(correct_ans).strip().upper()
            )
            db.session.add(question)
            db.session.flush() # Fetch question ID
            
            # Populate options
            options_list = []
            if has_individual_options:
                for letter in ["A", "B", "C", "D"]:
                    opt_val = row.get(f"option_{letter.lower()}")
                    if opt_val:
                        options_list.append((letter, opt_val))
            elif has_single_options_col:
                opts_str = row.get("options") or ""
                raw_opts = []
                
                # Check for JSON list
                opts_str_stripped = opts_str.strip()
                if opts_str_stripped.startswith("[") and opts_str_stripped.endswith("]"):
                    try:
                        import json as json_lib
                        raw_opts = json_lib.loads(opts_str_stripped)
                    except Exception:
                        raw_opts = []
                
                if not raw_opts:
                    # Try splitting by semicolon, vertical bar, newline, or comma
                    for splitter in [";", "|", "\n", ","]:
                        if splitter in opts_str:
                            raw_opts = [o.strip() for o in opts_str.split(splitter) if o.strip()]
                            break
                    else:
                        if opts_str.strip():
                            raw_opts = [opts_str.strip()]
                            
                # Map up to 4 options to letters A, B, C, D
                letters = ["A", "B", "C", "D"]
                for i, opt_val in enumerate(raw_opts[:4]):
                    options_list.append((letters[i], opt_val))
                    
            for letter, opt_text in options_list:
                option = QuestionOption(
                    question_id=question.id,
                    option_letter=letter,
                    option_text=opt_text
                )
                db.session.add(option)
            
            added_count += 1

        # Audit log creation
        audit = AuditLog(
            user_id=user.id,
            action="QUESTIONS_UPLOADED",
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent")
        )
        audit.details = {"exam_id": exam_id, "questions_count": added_count}
        db.session.add(audit)
        
        db.session.commit()
        logger.info(f"Admin {user.email} uploaded {added_count} questions to exam {exam_id}")
        
        return jsonify({
            "success": True,
            "message": f"Successfully uploaded {added_count} questions."
        }), 201

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error parsing CSV upload: {str(e)}")
        return jsonify({
            "success": False,
            "error_code": "CSV_PARSING_FAILED",
            "message": "An error occurred while parsing and saving the questions from the CSV file."
        }), 500


@questions_bp.route("/exams/<int:exam_id>/questions/upload", methods=["POST"])
@token_required
@role_required(["admin"])
def preview_questions_upload(exam_id):
    if not Exam.query.filter_by(id=exam_id, is_deleted=False).first():
        return jsonify({"success": False, "error_code": "EXAM_NOT_FOUND", "message": "Exam not found."}), 404
    uploaded_file = request.files.get("file")
    if not uploaded_file or not uploaded_file.filename:
        return jsonify({"success": False, "error_code": "NO_FILE", "message": "A question file is required."}), 400
    try:
        questions = _validate_questions(_parse_upload(uploaded_file))
        return jsonify({"success": True, "message": f"Parsed {len(questions)} questions. Review before saving.", "questions": questions}), 200
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return jsonify({"success": False, "error_code": "QUESTION_FILE_INVALID", "message": str(error)}), 400


@questions_bp.route("/exams/<int:exam_id>/questions/bulk", methods=["PUT"])
@token_required
@role_required(["admin"])
def save_questions_bulk(exam_id):
    user = request.current_user
    exam = Exam.query.filter_by(id=exam_id, is_deleted=False).first()
    if not exam:
        return jsonify({"success": False, "error_code": "EXAM_NOT_FOUND", "message": "Exam not found."}), 404
    try:
        questions = _validate_questions((request.get_json() or {}).get("questions"))
        existing = {question.id: question for question in Question.query.filter_by(exam_id=exam_id).all()}
        retained_ids = set()
        for data in questions:
            question_id = data.get("id")
            question = existing.get(question_id) if question_id else None
            if question:
                retained_ids.add(question.id)
                question.question_text = data["question_text"]
                question.question_type = data["question_type"]
                question.marks = data["marks"]
                question.negative_marks = data["negative_marks"]
                question.correct_answer = data["correct_answer"]
                question.options.clear()
            else:
                question = _add_question_record(exam_id, data)
                retained_ids.add(question.id)
                continue
            for option in data["options"]:
                db.session.add(QuestionOption(question_id=question.id, option_letter=option["letter"], option_text=option["text"]))
        unwanted_ids = [question_id for question_id in existing.keys() if question_id not in retained_ids]
        if unwanted_ids:
            from backend.models import StudentAnswer
            StudentAnswer.query.filter(StudentAnswer.question_id.in_(unwanted_ids)).delete(synchronize_session=False)
            QuestionOption.query.filter(QuestionOption.question_id.in_(unwanted_ids)).delete(synchronize_session=False)
            Question.query.filter(Question.id.in_(unwanted_ids)).delete(synchronize_session=False)
        audit = AuditLog(user_id=user.id, action="QUESTIONS_REVIEWED_AND_SAVED", ip_address=request.remote_addr,
                         user_agent=request.headers.get("User-Agent"))
        audit.details = {"exam_id": exam_id, "questions_count": len(questions)}
        db.session.add(audit)
        db.session.commit()
        saved = Question.query.filter_by(exam_id=exam_id).all()
        return jsonify({"success": True, "message": "Questions saved to the exam.", "questions": [q.to_dict(True) for q in saved]}), 200
    except (ValueError, TypeError) as error:
        db.session.rollback()
        return jsonify({"success": False, "error_code": "INVALID_QUESTIONS", "message": str(error)}), 400
    except Exception as error:
        db.session.rollback()
        logger.error(f"Error saving reviewed questions: {error}")
        return jsonify({"success": False, "error_code": "QUESTION_SAVE_FAILED", "message": "Failed to save reviewed questions."}), 500


@questions_bp.route("/exams/<int:exam_id>/questions/<int:question_id>", methods=["PUT", "DELETE"])
@token_required
@role_required(["admin"])
def manage_question(exam_id, question_id):
    question = Question.query.filter_by(id=question_id, exam_id=exam_id).first()
    if not question:
        return jsonify({"success": False, "error_code": "QUESTION_NOT_FOUND", "message": "Question not found."}), 404
    if request.method == "DELETE":
        from backend.models import StudentAnswer
        StudentAnswer.query.filter_by(question_id=question.id).delete(synchronize_session=False)
        QuestionOption.query.filter_by(question_id=question.id).delete(synchronize_session=False)
        db.session.delete(question)
        db.session.commit()
        return jsonify({"success": True, "message": "Question deleted."}), 200
    try:
        data = _validate_questions([request.get_json() or {}])[0]
        question.question_text = data["question_text"]
        question.question_type = data["question_type"]
        question.marks = data["marks"]
        question.negative_marks = data["negative_marks"]
        question.correct_answer = data["correct_answer"]
        question.options.clear()
        for option in data["options"]:
            db.session.add(QuestionOption(question_id=question.id, option_letter=option["letter"], option_text=option["text"]))
        db.session.commit()
        return jsonify({"success": True, "question": question.to_dict(True)}), 200
    except (ValueError, TypeError) as error:
        db.session.rollback()
        return jsonify({"success": False, "error_code": "INVALID_QUESTION", "message": str(error)}), 400
