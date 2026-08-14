# Secure AI-Proctored Online Examination System
## Multi-Layer Online Examination Platform with Real-Time Malpractice Detection and Automated Evaluation

This repository contains the complete implementation of a production-quality, multi-layer secure online examination system. The platform employs browser sandbox constraints, server-side temporal audits, and lightweight client-side AI computer vision models to significantly reduce exam malpractice while maintaining strict user privacy.

---

## 🛡️ Primary Security Architecture & Enforcement

To mitigate the architectural boundaries of web-based sandboxing, this system separates security enforcements into distinct layers:

### Layer 1: Client Browser Sandbox (Detection & Warnings)
* **Fullscreen Lock**: Locks the candidate screen using the Fullscreen API. Detects escape events (`fullscreenchange`) and registers security warning violations.
* **Window Visibility & Focus Tracking**: Monitors candidate tab shifts and window blur status via `document.visibilityState` and the `blur` event.
* **Input Blocking**: Captures and cancels copy/paste operations, right-click context menus, page refresh commands (`F5`), and debugger inspect tools (`F12`).

### Layer 2: Client Real-Time AI Proctoring (Local CV Inference)
* **Face Mesh Tracking**: Loads MediaPipe Face Mesh model via CDN to continuously run local inference in the client thread.
* **Absence Detection**: Flags if the candidate leaves the camera field of view.
* **Deduplicated Head Turn Estimation**: Estimates pitch and yaw. If the candidate turns their head left, right, up, or down past thresholds for over a persistent duration, a warning is logged. Multiple frames are deduplicated to register exactly **one** incident log.
* **Additional Person & Mobile Checks**: Integrates YOLOv8 object configurations (available in high-security mode) checking for multiple faces or phone devices.
* **Temporal Cooldown Filtering**: Ensures warnings and evidence uploads occur with minimum cooldown periods (e.g. 10 seconds) to avoid CPU thread block and server evidence upload bottlenecking.

### Layer 3: Server-Side Exam Security (Authority of Truth)
* **Server-Controlled Timer**: Evaluates deadline durations comparing server start time with submission timestamp. Client system clock alterations have zero effect.
* **Heartbeat Keep-Alive**: Requires client heartbeat checkpoints every 5 seconds. If heartbeats stop, a grace period is initiated. If sandbox violations (e.g., blur/escape) occur during heartbeats, severity warnings are sent back.
* **Idempotent Autosave**: Student answers sync to the database periodically. Synchronizations prevent duplicate answers.
* **Centralized Violation Engine**: Evaluates proctoring flags, checks confidence thresholds, increments violation counters, triggers warnings, and automatically cancels attempts (Status: `MALPRACTICE_CANCELLED`) when configured thresholds are exceeded.

---

## 📂 Project Structure

```text
secure-exam-system/
├── backend/
│   ├── app.py                  # Flask App bootstrap, CORS & Global JSON error handlers
│   ├── config.py               # Environment configuration loader
│   ├── init_db.py              # Database schema builder and admin account seed
│   ├── routes/
│   │   ├── auth.py             # User Register, Login, and Session logout
│   │   ├── exams.py            # Exams CRUD and custom security policy configs
│   │   ├── questions.py        # Questions manually added, and CSV bulk importer
│   │   ├── attempts.py         # Start attempt, student answer save, and submission APIs
│   │   ├── proctoring.py       # Heartbeat processing, event logs, and evidence uploads
│   │   ├── results.py          # Detailed graded results, answers review, and violation audits
│   │   └── admin.py            # Overview metrics and secure audit logs serving
│   ├── models/
│   │   ├── __init__.py         # DB connection bootstrap
│   │   ├── user.py             # User model with bcrypt password hashing
│   │   ├── exam.py             # Exam Metadata model
│   │   ├── security_config.py  # Security limits config model
│   │   ├── question.py         # Questions & MCQ Options model
│   │   ├── attempt.py          # Attempt state tracker
│   │   ├── answer.py           # Selected answers JSON serializer model
│   │   ├── violation.py        # Proctoring Violation log model
│   │   ├── evidence.py         # Evidence screenshots pointer model
│   │   ├── audit.py            # AuditLog append-only logs model
│   │   └── result.py           # Total score & pass/fail results model
│   ├── services/
│   │   ├── session_manager.py  # Attempt session verification and timer enforcer
│   │   ├── evaluation.py       # Server-side automatic grading service
│   │   ├── violation_engine.py # Violation log checks, cooldowns, and actions handler
│   │   └── evidence_service.py # Pillow-based frame compressor and file hashing
│   ├── utils/
│   │   ├── security.py         # JWT generation, token_required & role_required decorators
│   │   └── logger.py           # Logging module (console and file logs)
│   └── secure_exam.db          # Local SQLite development database (automatically generated)
├── frontend/
│   ├── login.html              # Candidate & Admin Sign In
│   ├── register.html           # Account Sign Up
│   ├── dashboard.html          # Candidate Exam Selection & precheck modal
│   ├── exam.html               # Candidate Exam player, heartbeat, and local AI CV
│   ├── result.html             # Graded result and security log audit
│   ├── admin/
│   │   ├── dashboard.html      # Admin summary panels, active status, recent warnings
│   │   ├── exams.html          # Admin Exams CRUD & custom security setup
│   │   ├── questions.html      # Question creation & bulk CSV uploading
│   │   └── violations.html     # Violation log evidence screenshots audit reviewer
│   ├── css/
│   │   └── style.css           # Premium dark theme and glassmorphic designs
│   └── js/
│       └── app.js              # Client HTTP API wrappers, camera utils, sandbox, local CV
├── tests/
│   └── test_exam_system.py     # Automated testing suite
├── evidence/                   # Local evidence folder for violation screenshots (generated)
├── requirements.txt            # Python requirements
└── .env                        # Local configurations
```

---

## 🚀 Environment Setup & Run Guide

### 1. Install System Dependencies
Ensure you have Python 3.11+ installed. Run the command below in the project root directory:
```bash
pip install -r requirements.txt
```

### 2. Initialize Database & Seed Administrator
Initialize the schema and create the default admin account:
```bash
python backend/init_db.py
```
This seeds the database with the default administrative credentials:
* **Admin Email**: `admin@secureexam.com`
* **Admin Password**: `AdminSecurePass123!`

### 3. Run Backend REST API Server
Start the Flask development API server:
```bash
python backend/app.py
```
The server will run on `http://127.0.0.1:5000`.

### 4. Run Frontend Client App
Since the frontend is built using standard HTML5 and JavaScript without complex node dependencies, you can serve the pages using any static server or directly open `frontend/login.html` in a web browser.
To host locally, you can run:
```powershell
# Python built-in server
python -m http.server 8000
```
Then navigate to `http://localhost:8000/frontend/login.html`.

---

## 🧪 Running Automated Tests

Run the test suite using unittest:
```bash
python -m unittest tests/test_exam_system.py
```
This evaluates scoring, verification limits, cooldown deduplications, authentication headers, and role access restrictions.

---

## 🔒 Known Technical Limitations & Mitigations

1. **Physical Monitors**: standard browser APIs cannot detect physical splitters or HDMI grabbers. *Mitigation*: Require high-security deployments to run within Safe Exam Browser (SEB) which reads monitor connections directly from the OS.
2. **Webcam Blindspots**: A candidate may place physical notes or secondary displays out of camera view. *Mitigation*: Instruct candidates on webcam positioning before exams, require workspace panning check, and enforce strict screen focus policies.
3. **Hardware Latencies**: Running face mesh structures inside a browser can cause lagging on low-end processors. *Mitigation*: Inference frames are sampled at 2 FPS rather than 30 FPS. If CPU load remains high, the system disables local landmarks drawing.

---

## 📋 Privacy & Data Retention Policy

This system implements Privacy by Design. Continuous audio/video streams are never recorded or stored on the server.
* **Registration**: Only stores name, email, and password hashes.
* **Pre-Check Face Verification**: The reference face captured during precheck is stored securely on the server and is deleted immediately upon exam grading/release.
* **Evidence Management**: Image screenshots are captured and uploaded *only* when a confirmed security violation log is recorded.
* **Retention Schedule**: All evidence files are configured to auto-purge 30 days post-examination unless flagged for manual committee review.
