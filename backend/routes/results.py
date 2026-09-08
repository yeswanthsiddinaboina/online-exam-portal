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
    
    # Auto-evaluate any finished or terminated attempts missing a Result record
    try:
        from backend.services.evaluation import EvaluationService
        unevaluated = ExamAttempt.query.filter(
            ExamAttempt.status.in_(["SUBMITTED", "AUTO_SUBMITTED", "EXPIRED", "MALPRACTICE_CANCELLED"])
        ).filter(~ExamAttempt.id.in_(db.session.query(Result.attempt_id))).all()
        for att in unevaluated:
            EvaluationService.evaluate_attempt(att.id)
    except Exception as e:
        logger.error(f"Error auto-evaluating pending attempts in get_results: {str(e)}")

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

    # Check if evaluated; if not yet evaluated but finished/terminated, evaluate now
    result = Result.query.filter_by(attempt_id=attempt_id).first()
    if not result and attempt.status in ["SUBMITTED", "AUTO_SUBMITTED", "EXPIRED", "MALPRACTICE_CANCELLED"]:
        try:
            from backend.services.evaluation import EvaluationService
            result = EvaluationService.evaluate_attempt(attempt_id)
        except Exception as e:
            logger.error(f"Error auto-evaluating attempt {attempt_id}: {str(e)}")
    
    # Check if candidate has completed their allotted duration (answers hidden until timer ends)
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

    # Return result block - Score is always visible; answers_visible controls question solutions
    result_data = {
        "attempt_id": attempt.id,
        "exam_title": attempt.exam.title,
        "student_email": attempt.student.email,
        "student_username": attempt.student.first_name,
        "student_userid": attempt.student.last_name,
        "duration_minutes": attempt.exam.duration_minutes,
        "started_at": attempt.started_at.isoformat() + "Z" if attempt.started_at else None,
        "ended_at": attempt.ended_at.isoformat() + "Z" if attempt.ended_at else None,
        "status": attempt.status,
        "score_obtained": result.total_score if result else 0.0,
        "percentage": result.percentage if result else 0.0,
        "passed": result.passed if result else False,
        "answers_visible": answers_visible,
        "questions": questions_data,
        "violations": violations_summary
    }

    return jsonify({
        "success": True,
        "result": result_data
    }), 200
