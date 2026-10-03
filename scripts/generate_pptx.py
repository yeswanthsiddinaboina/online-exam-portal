"""
Presentation Generator Script (PowerPoint .pptx)
Run this script to generate a professional 12-slide presentation (.pptx)
matching the exact design and content prepared for the client.

Usage:
    pip install python-pptx
    python scripts/generate_pptx.py
"""

import sys
from pathlib import Path

try:
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN
    from pptx.enum.shapes import MSO_SHAPE
except ImportError:
    print("[!] python-pptx is not installed.")
    print("    Please run: pip install python-pptx")
    sys.exit(1)

def create_presentation():
    prs = Presentation()
    prs.slide_width = Inches(13.333) # 16:9 widescreen
    prs.slide_height = Inches(7.5)

    blank_layout = prs.slide_layouts[6]

    # Brand Colors
    DARK_BG = RGBColor(11, 19, 27)
    FOREST_DARK = RGBColor(6, 44, 37)
    CARD_BG = RGBColor(18, 30, 42)
    EMERALD = RGBColor(16, 185, 129)
    WHITE = RGBColor(248, 250, 252)
    MUTED_TEXT = RGBColor(148, 163, 184)
    RED_ACCENT = RGBColor(239, 68, 68)

    slides_data = [
        {
            "tag": "ENTERPRISE ASSESSMENT ARCHITECTURE",
            "title": "AI-Proctored Secure Examination & Assessment System",
            "subtitle": "Autonomous Academic Integrity, Real-Time Computer Vision & Frictionless Browser Lockdown",
            "bullets": [
                "100% Browser-Based: Zero local software or kernel-level agent downloads required.",
                "Calibrated 75° Yaw Tracking: Eliminates false alarm fatigue while stopping malpractice.",
                "< 0.5s Edge AI Latency: MediaPipe 3D face mesh executes on-device without high server bandwidth.",
                "85% Cost Reduction: Scalable autonomous testing replaces manual human invigilators."
            ],
            "notes": "Welcome everyone. Today, I am proud to introduce our Next-Generation AI-Proctored Secure Examination System. In modern education and corporate hiring, remote assessments are essential, but remote cheating is reaching an all-time high. Our platform eliminates malpractice autonomously using lightweight, edge-based computer vision without requiring candidates to download clunky, intrusive software."
        },
        {
            "tag": "MARKET NEED & INDUSTRY CHALLENGES",
            "title": "The Remote Assessment Integrity Crisis",
            "subtitle": "Fundamental vulnerabilities plaguing modern remote testing",
            "bullets": [
                "Rampant Malpractice: Secondary phones, unauthorized notes, off-screen helpers, and tab jumping.",
                "Exorbitant Proctoring Fees: $8–$15 per candidate hour for human invigilators prone to fatigue.",
                "Invasive Desktop Software: Heavy .exe downloads cause privacy pushback and exam-day dropouts.",
                "Disputed Outcomes & Zero Audit: Lack of forensic snapshot evidence leads to endless appeals."
            ],
            "notes": "Let's look at why remote assessments fail today. First, cheating has evolved: candidates use dual monitors, screen shares, secondary smartphones, or peers in the room. Second, human proctors are expensive and suffer from fatigue. Third, existing software solutions require invasive desktop apps. Our system fixes every single one of these bottlenecks."
        },
        {
            "tag": "AUTONOMOUS SOLUTION",
            "title": "End-to-End Assessment Ecosystem",
            "subtitle": "Six integrated pillars delivering comprehensive exam integrity",
            "bullets": [
                "Real-Time AI Proctor: 3D head pose estimation, facial verification, and multi-face detection.",
                "Environmental Lockdown: Fullscreen enforcement, tab-switch interception, and clipboard blocking.",
                "Course-Based Isolation: Strict domain segregation (Python, Java, Drive) preventing paper leaks.",
                "Instant Auto-Grading: Instant evaluation for MCQs, True/False, and short answers with negative marks.",
                "Forensic Audit PDF: 14-column marks list with direct candidate violation tallies color-coded in red/green.",
                "Admin Command Suite: 1-click bulk approvals, live candidate search, and permanent cascade wipe."
            ],
            "notes": "Here is our complete solution: An end-to-end cloud platform providing real-time AI computer vision proctoring, multi-course candidate isolation, automatic grading, and one-click forensic PDF reports. Candidates take their exam in any standard modern web browser with zero downloads."
        },
        {
            "tag": "TECHNICAL ENGINEERING",
            "title": "System Architecture & Technology Stack",
            "subtitle": "High-concurrency, low-latency, edge-driven design",
            "bullets": [
                "Client-Side Edge AI: MediaPipe Face Mesh (468 3D landmarks) running via WebAssembly in browser.",
                "Backend Framework: Python 3, Flask RESTful API, PBKDF2/Argon2 security, and signed JWT auth.",
                "Cloud Database: Neon Serverless PostgreSQL with auto-scaling connection pooling and self-healing schemas.",
                "Zero-Dependency PDF: Custom pure-Python PDF 1.4 binary stream generator running in < 100ms."
            ],
            "notes": "Let's touch on the technical foundation. On the client side, we use WebRTC and Google's MediaPipe Face Mesh running directly in the browser via WebAssembly. This means the heavy computer vision runs on the candidate's machine, keeping cloud bandwidth and server costs near zero. On the backend, we use Python Flask with SQLAlchemy and Neon Serverless PostgreSQL."
        },
        {
            "tag": "COMPUTER VISION INNOVATION",
            "title": "Calibrated 3D Head Pose & Face Intelligence",
            "subtitle": "Mathematical precision tuned to eliminate false positives",
            "bullets": [
                "468 3D Landmark Mesh: Solves Perspective-n-Point (PnP) pose calculations at 30 fps in real time.",
                "75° Calibrated Yaw Threshold: Natural screen scanning is tolerated; turning to cheat triggers warnings.",
                "Pre-Exam Face Verification: Webcam snapshot matches registered candidate photo to eliminate impersonators.",
                "Continuous Room Integrity: Instantly flags secondary individuals in frame or candidate absence."
            ],
            "notes": "Now let's highlight our star computer vision feature: Calibrated 3D Head Pose Estimation. Most proctoring tools fail because they flag a student the second their eyes dart across a large screen, creating false alarm frustration. We solved this. We calibrated the head-turn warning threshold to 75 degrees. Natural scanning is allowed, but cheating is immediately recorded."
        },
        {
            "tag": "SECURITY & INTEGRITY ENFORCEMENT",
            "title": "Environmental Lockdown & Anti-Tamper",
            "subtitle": "Complete sandbox isolation within standard web browsers",
            "bullets": [
                "Fullscreen Enforcement: Candidate cannot view questions without entering fullscreen mode.",
                "Tab-Switch Interception: Immediate modal lockout upon window blur or application switching.",
                "Automated Strike Termination: Configurable strike limits (e.g. 5 strikes) instantly auto-submits exam.",
                "Anti-Tamper Hardening: Right-click, text selection, copy-paste, and F12 DevTools shortcuts blocked.",
                "Heartbeat & Snapshot Capture: Active 10s cryptographic heartbeats with evidence disk snapshot archiving."
            ],
            "notes": "Beyond vision, how do we prevent digital cheating? Our browser lockdown engine provides multi-layered client security. When the student clicks 'Start Exam', the exam forces strict Fullscreen mode. If they press Esc or switch tabs, the exam screen immediately blurs and freezes, displaying a violation warning."
        },
        {
            "tag": "DOMAIN ISOLATION & ONBOARDING",
            "title": "Course-Based Isolation & Candidate Control",
            "subtitle": "Airtight segregation for specialized recruitment drives and cohorts",
            "bullets": [
                "Streamlined Registration: Candidate details, verified Gmail, 10-digit phone number, and chosen course.",
                "Exam Access Rules: Exams created for 'Drive' are strictly accessible ONLY to Drive registered students.",
                "Tamper-Proof Protection: Direct URL manipulation or API calls rejected with 403 EXAM_COURSE_MISMATCH.",
                "Instant Clean Re-Registration: Full cascade user deletion allows students to re-register fresh immediately."
            ],
            "notes": "Let's look at how candidates and courses are organized. Many organizations run specialized hiring drives or separate batches like Python, Java, or our specialized Drive batch. We engineered Course-Based Isolation. When a student registers, they can ONLY access examinations assigned to their track."
        },
        {
            "tag": "ADMINISTRATIVE EFFICIENCY",
            "title": "Administrative Command & Control Suite",
            "subtitle": "High-velocity batch management and real-time oversight",
            "bullets": [
                "1-Click Bulk Approvals: 'Approve All' buttons for student registrations and exam access requests.",
                "Live Phone & Candidate Search: Instant multi-field search across Name, Gmail, Phone, and Course.",
                "Interactive Scoreboard: Filter candidates by Completed, Active, and Terminated with real-time stats.",
                "Comprehensive Audit Drill-Down: Inspect every question response, correct answer, and violation timestamp."
            ],
            "notes": "Administrators need speed and simplicity. In this system, everything is designed for high efficiency. We built 'Approve All' buttons for both candidate registrations and exam access requests, allowing an admin to clear a batch of 500 candidates in a single click."
        },
        {
            "tag": "FORENSIC REPORTING & COMPLIANCE",
            "title": "Official Marks Report & Violation Audit PDF",
            "subtitle": "Accreditation-grade multi-page assessment documentation",
            "bullets": [
                "14-Column Landscape Layout: S.No, Student ID, Name, Email, Marks, Violations Count, Result, and Status.",
                "Violations Count Replaces Percentage: High-contrast color coding (Bold Green for 0, Bold Red for > 0).",
                "Pure-Python Dependency-Free: In-memory PDF stream generator guarantees zero server environment failures.",
                "Official Verification Seals: Includes institutional metadata, pass rate summaries, and timestamped audit IDs."
            ],
            "notes": "Now look at our official reporting output. At the end of the exam, the administrator can download an official, tamper-proof Student Examination Marks Report PDF. In response to institutional demands, we replaced standard percentages with the exact count of proctoring violations recorded for that student."
        },
        {
            "tag": "BUSINESS VALUE & ROI",
            "title": "Quantifiable Business & Operational Impact",
            "subtitle": "Proven metrics driving institutional efficiency and trust",
            "bullets": [
                "85% Cost Reduction: Eliminates expensive human proctor agency contracts and scheduling overhead.",
                "Zero Second Grading Turnaround: Instant evaluation replaces 5-7 days of manual grading delays.",
                "99.4% Examination Completion: Zero download crashes or firewall blocks on exam day.",
                "High Concurrency Testing: Effortlessly scales from 50 to 5,000+ candidates without server lag."
            ],
            "notes": "Now let's talk about the business numbers and return on investment for your organization. Compared to traditional manual proctoring services, our platform delivers an average 85% cost reduction. Furthermore, results that previously took 5 to 7 days are delivered within seconds."
        },
        {
            "tag": "TRUST & REGULATORY COMPLIANCE",
            "title": "Enterprise Security, Privacy & Compliance",
            "subtitle": "Privacy-by-design safeguarding institutional and student data",
            "bullets": [
                "Privacy-Preserving Edge Vision: Video streams never leave candidate devices; only landmark math is checked.",
                "Encrypted Data & Tokens: TLS 1.3 encryption with HMAC-SHA256 JWT tokens and anti-replay protection.",
                "GDPR Right-to-be-Forgotten: Permanent cascade deletion purges database records and disk snapshots completely.",
                "Flexible Cloud & LMS Integration: Deploy on AWS/Azure/GCP or on-premises; connects to Canvas, Moodle, and HRIS."
            ],
            "notes": "Data privacy and compliance are non-negotiable. Our platform complies with modern privacy standards: We process video locally at the browser edge, so raw webcam feeds are never sent or stored on cloud servers. We only store compressed snapshots when a distinct violation occurs."
        },
        {
            "tag": "NEXT STEPS & DEMONSTRATION",
            "title": "Transform Your Assessment Integrity Today",
            "subtitle": "Immediate deployment pathway and live interactive demo",
            "bullets": [
                "Step 1: Experience the Live Interactive Demo right now (Face calibration, proctoring test, admin dashboard).",
                "Step 2: 48-Hour Pilot Session configured with your institution's custom question bank and policy limits.",
                "Step 3: Seamless Enterprise Rollout with custom branding, LMS webhooks, and administrative training."
            ],
            "notes": "Thank you for your time. In summary, our AI-Proctored Examination System delivers uncompromised academic integrity, calibrated precision vision, and enterprise administration at a fraction of manual costs. We invite you to experience a live demonstration right now, or pilot your upcoming test with our team."
        }
    ]

    for item in slides_data:
        slide = prs.slides.add_slide(blank_layout)

        # Background shape
        bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
        bg.fill.solid()
        bg.fill.fore_color.rgb = DARK_BG
        bg.line.color.rgb = DARK_BG

        # Top Accent Strip
        top_strip = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.8), Inches(0.5), Inches(11.73), Inches(0.06))
        top_strip.fill.solid()
        top_strip.fill.fore_color.rgb = EMERALD
        top_strip.line.color.rgb = EMERALD

        # Tag
        tag_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.7), Inches(11.73), Inches(0.4))
        tf_tag = tag_box.text_frame
        tf_tag.word_wrap = True
        p_tag = tf_tag.paragraphs[0]
        p_tag.text = item["tag"]
        p_tag.font.size = Pt(11)
        p_tag.font.bold = True
        p_tag.font.color.rgb = EMERALD

        # Title
        title_box = slide.shapes.add_textbox(Inches(0.8), Inches(1.1), Inches(11.73), Inches(0.8))
        tf_title = title_box.text_frame
        tf_title.word_wrap = True
        p_title = tf_title.paragraphs[0]
        p_title.text = item["title"]
        p_title.font.size = Pt(26)
        p_title.font.bold = True
        p_title.font.color.rgb = WHITE

        # Subtitle
        sub_box = slide.shapes.add_textbox(Inches(0.8), Inches(1.9), Inches(11.73), Inches(0.5))
        tf_sub = sub_box.text_frame
        tf_sub.word_wrap = True
        p_sub = tf_sub.paragraphs[0]
        p_sub.text = item["subtitle"]
        p_sub.font.size = Pt(14)
        p_sub.font.color.rgb = MUTED_TEXT

        # Content Card / Bullets Box
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(2.6), Inches(11.73), Inches(4.2))
        card.fill.solid()
        card.fill.fore_color.rgb = CARD_BG
        card.line.color.rgb = RGBColor(30, 48, 64)

        tb_bullets = slide.shapes.add_textbox(Inches(1.2), Inches(2.8), Inches(10.9), Inches(3.7))
        tf_bullets = tb_bullets.text_frame
        tf_bullets.word_wrap = True

        for b_idx, bullet in enumerate(item["bullets"]):
            p = tf_bullets.paragraphs[0] if b_idx == 0 else tf_bullets.add_paragraph()
            p.text = "•  " + bullet
            p.font.size = Pt(15)
            p.font.color.rgb = WHITE
            p.space_after = Pt(16)

        # Speaker notes
        notes_slide = slide.notes_slide
        tf_notes = notes_slide.notes_text_frame
        tf_notes.text = item["notes"]

    output_path = Path(__file__).resolve().parent.parent / "client_presentation.pptx"
    prs.save(str(output_path))
    print(f"[✓] Presentation successfully generated: {output_path}")

if __name__ == "__main__":
    create_presentation()
