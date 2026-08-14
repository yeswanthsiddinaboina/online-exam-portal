from flask import Blueprint, request, jsonify
from backend.models import db, ExamAttempt, Result, Question, StudentAnswer
from backend.utils.security import token_required
from backend.utils.logger import get_logger
from datetime import datetime, timedelta

logger = get_logger()
results_bp = Blueprint("results", __name__)

@results_bp.route("", methods=["GET"])
@token_required
def get_results():
    user = request.current_user
    
    if user.role == "admin":
        # Admins can query all finished results
        results = Result.query.join(ExamAttempt).all()
    else:
        # Candidates can only query their own results
        results = Result.query.join(ExamAttempt).filter(ExamAttempt.student_id == user.id).all()

    response_data = []
    for r in results:
        attempt = r.attempt
        response_data.append({
            "result_id": r.id,
            "attempt_id": attempt.id,
            "exam_title": attempt.exam.title,
            "student_name": f"{attempt.student.first_name} {attempt.student.last_name}",
            "student_email": attempt.student.email,
            "total_score": r.total_score,
            "percentage": r.percentage,
            "passed": r.passed,
            "status": attempt.status,
            "evaluated_at": r.evaluated_at.isoformat() if r.evaluated_at else None
        })

    return jsonify({
        "success": True,
        "results": response_data
    }), 200

@results_bp.route("/<int:attempt_id>", methods=["GET"])
@token_required
def get_result_details(attempt_id):
    user = request.current_user
    attempt = ExamAttempt.query.get(attempt_id)
    
    if not attempt:
        return jsonify({
            "success": False,
            "error_code": "ATTEMPT_NOT_FOUND",
            "message": "Examination attempt session not found."
        }), 404
        
    if user.role != "admin" and attempt.student_id != user.id:
        return jsonify({
            "success": False,
            "error_code": "UNAUTHORIZED_ACCESS",
            "message": "You do not have permission to view these results."
        }), 403

    # Check if evaluated
    result = Result.query.filter_by(attempt_id=attempt_id).first()
    
    # Check if candidate has completed their allotted duration
    answers_visible = True
    if user.role != "admin" and attempt.started_at:
        exam_end_time = attempt.started_at + timedelta(minutes=attempt.exam.duration_minutes)
        if datetime.utcnow() < exam_end_time:
            answers_visible = False

    questions = Question.query.filter_by(exam_id=attempt.exam_id).all()
    answers = {ans.question_id: ans for ans in attempt.answers}
    
    questions_data = []
    for q in questions:
        ans = answers.get(q.id)
        
        q_info = {
            "id": q.id,
            "question_text": q.question_text,
            "question_type": q.question_type,
            "marks": q.marks,
            "options": [opt.to_dict() for opt in q.options],
            "correct_answer": q.correct_answer if answers_visible else None,
            "student_answer": {
                "selected_answers": ans.selected_answers if ans else [],
                "text_answer": ans.text_answer if ans else ""
            }
        }
        questions_data.append(q_info)

    # Compile violation summaries for audit
    violations_summary = [v.to_dict() for v in attempt.violations]

    # Return result block
    result_data = {
        "attempt_id": attempt.id,
        "exam_title": attempt.exam.title,
        "duration_minutes": attempt.exam.duration_minutes,
        "started_at": attempt.started_at.isoformat() if attempt.started_at else None,
        "ended_at": attempt.ended_at.isoformat() if attempt.ended_at else None,
        "status": attempt.status,
        "score_obtained": result.total_score if result and answers_visible else 0.0,
        "percentage": result.percentage if result and answers_visible else 0.0,
        "passed": result.passed if result and answers_visible else False,
        "answers_visible": answers_visible,
        "questions": questions_data,
        "violations": violations_summary
    }

    return jsonify({
        "success": True,
        "result": result_data
    }), 200
