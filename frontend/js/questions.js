checkAuth("admin");

document.getElementById("user-display").innerText = `Admin: ${currentUser.first_name}`;

const examId = new URLSearchParams(window.location.search).get("exam_id");
let questionsReviewList = [];
let editingIndex = null;

if (!examId) {
    window.location.href = "exams.html";
}

function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>\'"]/g, character => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", "\'": "&#39;", '"': "&quot;"
    }[character]));
}

function toReviewQuestion(question) {
    return {
        id: question.id || null,
        question_text: question.question_text || question.question || "",
        question_type: question.question_type || "MCQ",
        correct_answer: question.correct_answer || question.answer || "",
        marks: Number(question.marks || 1),
        negative_marks: Number(question.negative_marks || 0),
        options: (question.options || []).map((option, index) => ({
            letter: option.letter || option.option_letter || String.fromCharCode(65 + index),
            text: option.text || option.option_text || ""
        }))
    };
}

function renderQuestions() {
    const list = document.getElementById("questions-list");
    document.getElementById("review-status").innerText = `${questionsReviewList.length} question(s) in review. Changes are local until saved.`;
    if (!questionsReviewList.length) {
        list.innerHTML = '<p style="color: var(--text-secondary);">No questions in the review list. Add one manually or parse a file.</p>';
        return;
    }

    list.innerHTML = questionsReviewList.map((question, index) => {
        if (editingIndex === index) {
            return `<form class="glass-panel" style="padding: 1.25rem;" onsubmit="saveInlineQuestion(event, ${index})">
                <strong>Editing Question ${index + 1}</strong>
                <textarea class="form-control" name="question_text" rows="3" required>${escapeHtml(question.question_text)}</textarea>
                <input class="form-control" name="options" value="${escapeHtml(question.options.map(option => `${option.letter}: ${option.text}`).join(" | "))}" placeholder="A: First option | B: Second option">
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem;">
                    <input class="form-control" name="correct_answer" value="${escapeHtml(question.correct_answer)}" placeholder="Correct answer" required>
                    <input class="form-control" name="marks" type="number" min="0" step="0.5" value="${escapeHtml(question.marks)}" required>
                </div>
                <div style="display: flex; gap: 0.5rem; margin-top: 0.75rem;">
                    <button class="btn btn-primary" type="submit">Save Edit</button>
                    <button class="btn btn-secondary" type="button" onclick="cancelInlineEdit()">Cancel</button>
                </div>
            </form>`;
        }

        return `<div class="glass-panel" style="padding: 1.25rem; background: rgba(255, 255, 255, 0.01);">
            <div style="display: flex; justify-content: space-between; margin-bottom: 0.5rem; font-size: 0.85rem; color: var(--text-secondary);">
                <strong>Question ${index + 1} (${escapeHtml(question.question_type)})</strong>
                <span>Marks: ${escapeHtml(question.marks)}</span>
            </div>
            <p style="margin-bottom: 1rem; font-weight: 500;">${escapeHtml(question.question_text)}</p>
            ${question.options.length ? `<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; margin-bottom: 1rem; font-size: 0.85rem;">${question.options.map(option => `<div><strong>${escapeHtml(option.letter)}.</strong> ${escapeHtml(option.text)}</div>`).join("")}</div>` : ""}
            <div style="border-top: 1px solid var(--border-glass); padding-top: 0.75rem; font-size: 0.85rem; display: flex; justify-content: space-between; align-items: center;">
                <span>Correct Answer: <strong style="color: var(--accent-success);">${escapeHtml(question.correct_answer)}</strong></span>
                <span style="display: flex; gap: 0.5rem;"><button class="btn btn-secondary" type="button" onclick="editQuestion(${index})">Edit</button><button class="btn btn-danger" type="button" onclick="deleteQuestion(${index})">Delete</button></span>
            </div>
        </div>`;
    }).join("");
}

function editQuestion(index) {
    editingIndex = index;
    renderQuestions();
}

function cancelInlineEdit() {
    editingIndex = null;
    renderQuestions();
}

function saveInlineQuestion(event, index) {
    event.preventDefault();
    const form = event.target;
    const options = form.elements.options.value.split("|").map((value, optionIndex) => {
        const parts = value.split(":");
        return {
            letter: (parts[0] || String.fromCharCode(65 + optionIndex)).trim().toUpperCase(),
            text: parts.slice(1).join(":").trim() || value.trim()
        };
    }).filter(option => option.text);

    questionsReviewList[index] = {
        ...questionsReviewList[index],
        question_text: form.elements.question_text.value.trim(),
        options,
        correct_answer: form.elements.correct_answer.value.trim().toUpperCase(),
        marks: Number(form.elements.marks.value)
    };
    editingIndex = null;
    renderQuestions();
}

function deleteQuestion(index) {
    if (confirm("Delete this question from the review list?")) {
        questionsReviewList.splice(index, 1);
        editingIndex = null;
        renderQuestions();
    }
}

async function loadExamQuestions() {
    const examResponse = await API.get(`/exams/${examId}`);
    if (examResponse.success) {
        document.getElementById("questions-header").innerText = `Questions: ${examResponse.exam.title}`;
    }

    const response = await API.get(`/exams/${examId}/questions`);
    if (response.success) {
        questionsReviewList = response.questions.map(toReviewQuestion);
        renderQuestions();
    }
}

document.getElementById("question-type").addEventListener("change", function(event) {
    const isMcq = event.target.value === "MCQ";
    document.getElementById("mcq-options-panel").style.display = isMcq ? "block" : "none";
    document.getElementById("correct-answer").placeholder = isMcq ? "A" : event.target.value === "TF" ? "True" : "Exact match text";
    document.getElementById("opt-a").required = isMcq;
    document.getElementById("opt-b").required = isMcq;
});

document.getElementById("manual-question-form").addEventListener("submit", function(event) {
    event.preventDefault();
    const questionType = document.getElementById("question-type").value;
    const options = questionType === "MCQ" ? [
        { letter: "A", text: document.getElementById("opt-a").value },
        { letter: "B", text: document.getElementById("opt-b").value },
        { letter: "C", text: document.getElementById("opt-c").value },
        { letter: "D", text: document.getElementById("opt-d").value }
    ].filter(option => option.text.trim()) : [];

    questionsReviewList.push({
        question_text: document.getElementById("question-text").value.trim(),
        question_type: questionType,
        correct_answer: document.getElementById("correct-answer").value.trim().toUpperCase(),
        marks: Number(document.getElementById("marks").value),
        negative_marks: 0,
        options
    });
    event.target.reset();
    document.getElementById("question-type").dispatchEvent(new Event("change"));
    renderQuestions();
});

document.getElementById("upload-csv-form").addEventListener("submit", async function(event) {
    event.preventDefault();
    const fileInput = document.getElementById("csv-file");
    if (!fileInput.files.length) return;

    const formData = new FormData();
    formData.append("file", fileInput.files[0]);
    const response = await API.upload("/parse-questions-file", formData);
    if (!response.success) {
        alert(response.message || "File parsing failed.");
        return;
    }
    questionsReviewList = questionsReviewList.concat(response.questions.map(toReviewQuestion));
    fileInput.form.reset();
    renderQuestions();
});

document.getElementById("save-reviewed-questions").addEventListener("click", async function() {
    if (!questionsReviewList.length) {
        alert("Add or parse at least one question first.");
        return;
    }
    const response = await API.post(`/exams/${examId}/save-questions`, { questions: questionsReviewList });
    if (!response.success) {
        alert(response.message || "Failed to save questions.");
        return;
    }
    alert(`Saved ${response.question_count} question(s).`);
    window.location.href = "exams.html";
});

loadExamQuestions();
