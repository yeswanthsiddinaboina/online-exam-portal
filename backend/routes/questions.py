import io
import csv
from flask import Blueprint, request, jsonify
from backend.models import db, Exam, Question, QuestionOption, AuditLog
from backend.utils.security import token_required, role_required
from backend.utils.logger import get_logger

logger = get_logger()
questions_bp = Blueprint("questions", __name__)

@questions_bp.route("/exams/<int:exam_id>/questions", methods=["GET"])
@token_required
def get_exam_questions(exam_id):
    user = request.current_user
    exam = Exam.query.get(exam_id)
    
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

@questions_bp.route("/exams/<int:exam_id>/questions/upload", methods=["POST"])
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
