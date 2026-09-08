import io
import zlib
import datetime
from backend.models import Exam, ExamAttempt, Question, StudentAnswer, Result
from backend.utils.logger import get_logger

logger = get_logger()

class PDFWriter:
    """
    Lightweight, dependency-free pure-Python PDF 1.4 generator.
    Produces high-fidelity, standards-compliant PDF documents with
    vector graphics, text rendering, borders, and compressed streams.
    """
    def __init__(self, page_width=842, page_height=595):
        # Default: A4 Landscape (842 x 595 points)
        self.width = page_width
        self.height = page_height
        self.pages = []
        self.current_stream = []

    def start_page(self):
        if self.current_stream:
            self.pages.append("".join(self.current_stream))
        self.current_stream = []

    def finish_page(self):
        if self.current_stream:
            self.pages.append("".join(self.current_stream))
            self.current_stream = []

    def set_fill_color(self, r, g, b):
        self.current_stream.append(f"{r:.3f} {g:.3f} {b:.3f} rg\n")

    def set_stroke_color(self, r, g, b):
        self.current_stream.append(f"{r:.3f} {g:.3f} {b:.3f} RG\n")

    def set_line_width(self, width):
        self.current_stream.append(f"{width:.2f} w\n")

    def rect(self, x, y, w, h, fill=True, stroke=True):
        mode = "B" if (fill and stroke) else ("f" if fill else "S")
        self.current_stream.append(f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re {mode}\n")

    def line(self, x1, y1, x2, y2):
        self.current_stream.append(f"{x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S\n")

    def draw_text(self, text, x, y, font_name="F1", font_size=10, r=0, g=0, b=0, align="left", max_width=None):
        if text is None:
            text = ""
        text = str(text).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        
        # Approximate font width calculation for Helvetica (avg char width ~0.52 of font_size)
        char_w = font_size * 0.52
        if font_name == "F2": # Bold
            char_w = font_size * 0.58
            
        text_w = len(text) * char_w
        
        # Truncate if exceeding max_width
        if max_width and text_w > max_width and len(text) > 4:
            avail_chars = max(3, int((max_width - (char_w * 3)) / char_w))
            text = text[:avail_chars] + "..."
            text_w = len(text) * char_w

        if align == "center":
            adjusted_x = x - (text_w / 2)
        elif align == "right":
            adjusted_x = x - text_w
        else:
            adjusted_x = x

        self.current_stream.append(
            f"q {r:.3f} {g:.3f} {b:.3f} rg BT /{font_name} {font_size:.1f} Tf "
            f"1 0 0 1 {adjusted_x:.2f} {y:.2f} Tm ({text}) Tj ET Q\n"
        )

    def build_pdf(self):
        self.finish_page()
        if not self.pages:
            self.pages.append("")

        output = io.BytesIO()
        objects = []
        
        # 1 0 obj: Catalog
        objects.append("<< /Type /Catalog /Pages 2 0 R >>")
        
        # 2 0 obj: Pages
        kids_refs = []
        page_obj_start = 5  # Resource obj is 3, Font1 is 4, Font2 is 5...
        
        # Resource definitions
        # Font 1: Helvetica (Regular)
        f1_obj = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
        # Font 2: Helvetica-Bold
        f2_obj = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"
        # Font 3: Helvetica-Oblique
        f3_obj = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Oblique /Encoding /WinAnsiEncoding >>"
        
        procset = "<< /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> /ProcSet [ /PDF /Text /ImageB /ImageC /ImageI ] >>"
        
        objects.append(None) # Index 1 (will become 2 0 obj Pages)
        objects.append(f1_obj) # 3 0 obj
        objects.append(f2_obj) # 4 0 obj
        objects.append(f3_obj) # 5 0 obj
        objects.append(procset) # 6 0 obj
        
        resource_id = 6
        current_obj_id = 7
        
        page_objs_map = []
        stream_objs_map = []
        
        for p_idx, page_content in enumerate(self.pages):
            page_id = current_obj_id
            stream_id = current_obj_id + 1
            current_obj_id += 2
            
            page_objs_map.append(page_id)
            stream_objs_map.append((stream_id, page_content))
            kids_refs.append(f"{page_id} 0 R")

        # Now fill in Pages object (Index 1 -> 2 0 obj)
        objects[1] = f"<< /Type /Pages /Kids [ {' '.join(kids_refs)} ] /Count {len(self.pages)} /MediaBox [ 0 0 {self.width} {self.height} ] >>"

        # Assemble page objects
        for i, page_id in enumerate(page_objs_map):
            stream_id = stream_objs_map[i][0]
            page_dict = f"<< /Type /Page /Parent 2 0 R /Resources {resource_id} 0 R /Contents {stream_id} 0 R >>"
            objects.append(page_dict)
            
            # Stream object with zlib FlateDecode
            content_bytes = stream_objs_map[i][1].encode("latin1", errors="replace")
            compressed = zlib.compress(content_bytes)
            stream_dict = f"<< /Length {len(compressed)} /Filter /FlateDecode >>\nstream\n"
            objects.append((stream_dict, compressed))

        # Write PDF binary header
        output.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        
        offsets = []
        for idx, obj in enumerate(objects, start=1):
            offset = output.tell()
            offsets.append(offset)
            output.write(f"{idx} 0 obj\n".encode("latin1"))
            if isinstance(obj, tuple):
                stream_hdr, stream_data = obj
                output.write(stream_hdr.encode("latin1"))
                output.write(stream_data)
                output.write(b"\nendstream\nendobj\n")
            else:
                output.write(f"{obj}\nendobj\n".encode("latin1"))

        # Write xref table
        start_xref = output.tell()
        output.write(f"xref\n0 {len(objects) + 1}\n".encode("latin1"))
        output.write(b"0000000000 65535 f \n")
        for offset in offsets:
            output.write(f"{offset:010d} 00000 n \n".encode("latin1"))

        # Write trailer
        trailer = (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{start_xref}\n%%EOF\n"
        )
        output.write(trailer.encode("latin1"))
        return output.getvalue()


class StudentExamMarksPDFService:
    @staticmethod
    def generate_exam_marks_pdf(exam_id):
        """
        Gathers candidate attempt details and generates a professional
        Student Examination Marks List PDF report for the given exam.
        """
        exam = Exam.query.get(exam_id)
        if not exam:
            raise ValueError(f"Examination with ID {exam_id} not found.")

        # Gather questions and total questions / marks
        questions = Question.query.filter_by(exam_id=exam_id).all()
        total_questions = len(questions)
        total_marks = sum(q.marks for q in questions) if questions else 0.0

        # Query all attempts for this exam ordered by started_at or attempt ID
        attempts = ExamAttempt.query.filter_by(exam_id=exam_id).order_by(ExamAttempt.started_at.asc()).all()

        # Compile candidate marks records
        records = []
        for idx, att in enumerate(attempts, start=1):
            student = att.student
            student_id_str = (student.last_name or f"STU{student.id:04d}") if student else "N/A"
            student_name = (student.first_name or "Unknown Student") if student else "Unknown"
            student_email = (student.email or "-") if student else "-"

            # Analyze answers
            answers_map = {ans.question_id: ans for ans in att.answers}
            correct_count = 0
            wrong_count = 0
            unanswered_count = 0

            for q in questions:
                ans = answers_map.get(q.id)
                if not ans:
                    unanswered_count += 1
                    continue

                has_answered = False
                is_correct = False

                if q.question_type in ["MCQ", "TF"]:
                    def extract_letter(val):
                        v = val.strip().upper()
                        if len(v) >= 2 and v[0].isalpha() and v[1] in [')', '.', '-', ':', ' ']:
                            return v[0]
                        return v

                    selected = [extract_letter(s) for s in (ans.selected_answers or []) if s]
                    correct_str = q.correct_answer or ""
                    correct_list = [extract_letter(c) for c in correct_str.split(",") if c.strip()]
                    
                    if selected:
                        has_answered = True
                        if sorted(selected) == sorted(correct_list):
                            is_correct = True
                elif q.question_type == "SHORT_ANSWER":
                    candidate_text = (ans.text_answer or "").strip().lower()
                    if candidate_text:
                        has_answered = True
                        correct_text = (q.correct_answer or "").strip().lower()
                        if candidate_text == correct_text:
                            is_correct = True

                if not has_answered:
                    unanswered_count += 1
                elif is_correct:
                    correct_count += 1
                else:
                    wrong_count += 1

            # Fetch result
            result = Result.query.filter_by(attempt_id=att.id).first()
            if not result and att.status in ["SUBMITTED", "AUTO_SUBMITTED", "MALPRACTICE_CANCELLED", "EXPIRED"]:
                try:
                    from backend.services.evaluation import EvaluationService
                    result = EvaluationService.evaluate_attempt(att.id)
                except Exception as eval_err:
                    logger.error(f"Error evaluating attempt {att.id} in pdf_generator: {str(eval_err)}")
            obtained_marks = result.total_score if result else 0.0
            percentage = result.percentage if result else 0.0
            passed = result.passed if result else (percentage >= 50.0)
            result_status = "PASSED" if passed else "FAILED"
            exam_status = att.status or "SUBMITTED"

            records.append({
                "s_no": idx,
                "student_id": student_id_str,
                "student_name": student_name,
                "email": student_email,
                "exam_name": exam.title,
                "total_questions": total_questions,
                "correct_answers": correct_count,
                "wrong_answers": wrong_count,
                "unanswered": unanswered_count,
                "total_marks": f"{total_marks:.1f}",
                "obtained_marks": f"{obtained_marks:.1f}",
                "percentage": f"{percentage:.1f}%",
                "result_status": result_status,
                "exam_status": exam_status
            })

        # Generate PDF document
        now = datetime.datetime.now()
        gen_date_str = now.strftime("%d %B %Y")
        gen_datetime_str = now.strftime("%d %B %Y, %I:%M %p")
        exam_date_str = exam.created_at.strftime("%d %B %Y") if exam.created_at else gen_date_str

        # Define 14 columns and their exact widths (Total = 782 pt)
        columns = [
            {"key": "s_no", "header": "S.No", "width": 30, "align": "center"},
            {"key": "student_id", "header": "Student ID", "width": 54, "align": "center"},
            {"key": "student_name", "header": "Student Name", "width": 78, "align": "left"},
            {"key": "email", "header": "Email", "width": 110, "align": "left"},
            {"key": "exam_name", "header": "Exam Name", "width": 82, "align": "left"},
            {"key": "total_questions", "header": "Total Qs", "width": 42, "align": "center"},
            {"key": "correct_answers", "header": "Correct", "width": 40, "align": "center"},
            {"key": "wrong_answers", "header": "Wrong", "width": 38, "align": "center"},
            {"key": "unanswered", "header": "Unans", "width": 40, "align": "center"},
            {"key": "total_marks", "header": "Total Mks", "width": 50, "align": "center"},
            {"key": "obtained_marks", "header": "Obt Mks", "width": 50, "align": "center"},
            {"key": "percentage", "header": "Percent", "width": 48, "align": "center"},
            {"key": "result_status", "header": "Result", "width": 56, "align": "center"},
            {"key": "exam_status", "header": "Exam Status", "width": 64, "align": "center"}
        ]

        pdf = PDFWriter(page_width=842, page_height=595)
        
        # Calculate pagination
        rows_per_first_page = 16
        rows_per_subsequent_page = 22

        total_records = len(records)
        if total_records <= rows_per_first_page:
            total_pages = 1
            page_chunks = [records]
        else:
            page_chunks = [records[:rows_per_first_page]]
            remaining = records[rows_per_first_page:]
            while remaining:
                page_chunks.append(remaining[:rows_per_subsequent_page])
                remaining = remaining[rows_per_subsequent_page:]
            total_pages = len(page_chunks)

        left_margin = 30
        top_margin = 560
        table_width = sum(c["width"] for c in columns)

        for p_idx, chunk in enumerate(page_chunks, start=1):
            pdf.start_page()

            # --- Background and Page Border ---
            pdf.set_fill_color(0.99, 0.99, 1.0)
            pdf.rect(0, 0, 842, 595, fill=True, stroke=False)
            
            # Outer page frame
            pdf.set_stroke_color(0.88, 0.91, 0.94)
            pdf.set_line_width(0.75)
            pdf.rect(15, 15, 812, 565, fill=False, stroke=True)

            current_y = top_margin

            if p_idx == 1:
                # --- Top Header Bar ---
                pdf.set_fill_color(0.09, 0.13, 0.24) # #17213C
                pdf.rect(left_margin, current_y - 28, table_width, 36, fill=True, stroke=False)
                
                # Teal accent strip
                pdf.set_fill_color(0.06, 0.73, 0.51) # #10B981
                pdf.rect(left_margin, current_y - 31, table_width, 3, fill=True, stroke=False)

                pdf.draw_text("SECURE AI-PROCTORED EXAMINATION SYSTEM", left_margin + 15, current_y - 12, font_name="F2", font_size=11, r=0.7, g=0.8, b=0.9)
                pdf.draw_text("CONFIDENTIAL ACADEMIC REPORT", left_margin + table_width - 15, current_y - 12, font_name="F2", font_size=9, r=0.06, g=0.73, b=0.51, align="right")

                current_y -= 45

                # Main Title
                pdf.draw_text("STUDENT EXAMINATION MARKS REPORT", left_margin, current_y, font_name="F2", font_size=18, r=0.09, g=0.13, b=0.24)
                
                current_y -= 14

                # Metadata Card Box
                meta_box_h = 46
                pdf.set_fill_color(0.96, 0.97, 0.99)
                pdf.rect(left_margin, current_y - meta_box_h, table_width, meta_box_h, fill=True, stroke=False)
                pdf.set_stroke_color(0.85, 0.88, 0.92)
                pdf.set_line_width(0.5)
                pdf.rect(left_margin, current_y - meta_box_h, table_width, meta_box_h, fill=False, stroke=True)

                # Metadata Items (Row 1)
                pdf.draw_text("Exam Name:", left_margin + 12, current_y - 16, font_name="F2", font_size=9.5, r=0.3, g=0.35, b=0.45)
                pdf.draw_text(exam.title, left_margin + 80, current_y - 16, font_name="F2", font_size=10, r=0.09, g=0.13, b=0.24, max_width=250)

                pdf.draw_text("Exam Date:", left_margin + 360, current_y - 16, font_name="F2", font_size=9.5, r=0.3, g=0.35, b=0.45)
                pdf.draw_text(exam_date_str, left_margin + 425, current_y - 16, font_name="F1", font_size=9.5, r=0.09, g=0.13, b=0.24)

                pdf.draw_text("Total Candidates:", left_margin + 570, current_y - 16, font_name="F2", font_size=9.5, r=0.3, g=0.35, b=0.45)
                pdf.draw_text(f"{total_records} Students", left_margin + 665, current_y - 16, font_name="F2", font_size=9.5, r=0.09, g=0.13, b=0.24)

                # Metadata Items (Row 2)
                pass_count = sum(1 for r in records if r["result_status"] == "PASSED")
                pass_rate_str = f"{(pass_count / total_records * 100):.1f}%" if total_records > 0 else "0.0%"
                
                pdf.draw_text("Duration:", left_margin + 12, current_y - 34, font_name="F2", font_size=9.5, r=0.3, g=0.35, b=0.45)
                pdf.draw_text(f"{exam.duration_minutes} Minutes", left_margin + 80, current_y - 34, font_name="F1", font_size=9.5, r=0.09, g=0.13, b=0.24)

                pdf.draw_text("Generated On:", left_margin + 360, current_y - 34, font_name="F2", font_size=9.5, r=0.3, g=0.35, b=0.45)
                pdf.draw_text(gen_datetime_str, left_margin + 440, current_y - 34, font_name="F1", font_size=9.5, r=0.09, g=0.13, b=0.24)

                pdf.draw_text("Overall Pass Rate:", left_margin + 570, current_y - 34, font_name="F2", font_size=9.5, r=0.3, g=0.35, b=0.45)
                pdf.draw_text(f"{pass_rate_str} ({pass_count}/{total_records})", left_margin + 665, current_y - 34, font_name="F2", font_size=9.5, r=0.06, g=0.73, b=0.51)

                current_y -= (meta_box_h + 16)
            else:
                pdf.draw_text(f"STUDENT EXAMINATION MARKS REPORT • {exam.title} (Cont.)", left_margin, current_y - 6, font_name="F2", font_size=11, r=0.09, g=0.13, b=0.24)
                pdf.draw_text(f"Generated On: {gen_datetime_str}", left_margin + table_width, current_y - 6, font_name="F1", font_size=9, r=0.4, g=0.45, b=0.5, align="right")
                
                pdf.set_stroke_color(0.85, 0.88, 0.92)
                pdf.set_line_width(0.75)
                pdf.line(left_margin, current_y - 12, left_margin + table_width, current_y - 12)

                current_y -= 22

            # --- Table Header ---
            header_height = 20
            pdf.set_fill_color(0.12, 0.16, 0.28) # Dark Navy #1E2942
            pdf.rect(left_margin, current_y - header_height, table_width, header_height, fill=True, stroke=False)

            col_x = left_margin
            for col in columns:
                align = col["align"]
                cw = col["width"]
                if align == "center":
                    tx = col_x + (cw / 2)
                elif align == "right":
                    tx = col_x + cw - 4
                else:
                    tx = col_x + 4

                pdf.draw_text(col["header"], tx, current_y - 14, font_name="F2", font_size=7.5, r=1.0, g=1.0, b=1.0, align=align, max_width=cw - 4)
                col_x += cw

            current_y -= header_height

            # --- Table Data Rows ---
            row_height = 19
            if not chunk:
                pdf.set_fill_color(1.0, 1.0, 1.0)
                pdf.rect(left_margin, current_y - row_height, table_width, row_height, fill=True, stroke=True)
                pdf.draw_text("No candidate examination attempts recorded for this exam yet.", left_margin + (table_width / 2), current_y - 13, font_name="F3", font_size=8.5, r=0.5, g=0.5, b=0.5, align="center")
                current_y -= row_height
            else:
                for r_idx, record in enumerate(chunk):
                    if r_idx % 2 == 1:
                        pdf.set_fill_color(0.965, 0.975, 0.99)
                    else:
                        pdf.set_fill_color(1.0, 1.0, 1.0)

                    pdf.rect(left_margin, current_y - row_height, table_width, row_height, fill=True, stroke=False)

                    pdf.set_stroke_color(0.88, 0.90, 0.94)
                    pdf.set_line_width(0.4)
                    pdf.line(left_margin, current_y - row_height, left_margin + table_width, current_y - row_height)

                    col_x = left_margin
                    for col in columns:
                        k = col["key"]
                        val = record.get(k, "")
                        cw = col["width"]
                        align = col["align"]

                        if align == "center":
                            tx = col_x + (cw / 2)
                        elif align == "right":
                            tx = col_x + cw - 4
                        else:
                            tx = col_x + 4

                        font_style = "F1"
                        font_sz = 7.2
                        cr, cg, cb = 0.15, 0.18, 0.25

                        if k == "s_no":
                            font_style = "F2"
                            cr, cg, cb = 0.35, 0.4, 0.5
                        elif k == "student_id":
                            font_style = "F2"
                            cr, cg, cb = 0.1, 0.15, 0.25
                        elif k == "student_name":
                            font_style = "F2"
                            cr, cg, cb = 0.05, 0.1, 0.2
                        elif k == "correct_answers":
                            font_style = "F2"
                            cr, cg, cb = 0.05, 0.6, 0.35 # Green
                        elif k == "wrong_answers":
                            font_style = "F2"
                            cr, cg, cb = 0.85, 0.2, 0.2 # Red
                        elif k == "obtained_marks":
                            font_style = "F2"
                        elif k == "percentage":
                            font_style = "F2"
                        elif k == "result_status":
                            font_style = "F2"
                            if val == "PASSED":
                                cr, cg, cb = 0.05, 0.6, 0.35 # Green
                            else:
                                cr, cg, cb = 0.85, 0.2, 0.2 # Red
                        elif k == "exam_status":
                            font_style = "F2"
                            if "CANCELLED" in str(val):
                                cr, cg, cb = 0.85, 0.2, 0.2 # Red
                            elif val in ["SUBMITTED", "AUTO_SUBMITTED"]:
                                cr, cg, cb = 0.05, 0.6, 0.35 # Green
                            else:
                                cr, cg, cb = 0.8, 0.5, 0.1 # Amber

                        pdf.draw_text(str(val), tx, current_y - 13, font_name=font_style, font_size=font_sz, r=cr, g=cg, b=cb, align=align, max_width=cw - 6)
                        col_x += cw

                    current_y -= row_height

            pdf.set_stroke_color(0.8, 0.83, 0.88)
            pdf.set_line_width(0.6)
            table_total_h = header_height + (len(chunk) * row_height if chunk else row_height)
            pdf.rect(left_margin, current_y, table_width, table_total_h, fill=False, stroke=True)

            # Footer
            footer_y = 30
            pdf.set_stroke_color(0.85, 0.88, 0.92)
            pdf.set_line_width(0.5)
            pdf.line(left_margin, footer_y + 12, left_margin + table_width, footer_y + 12)

            pdf.draw_text(
                "Secure AI-Proctored Examination System • Official Academic Assessment Record • System-Generated Document",
                left_margin, footer_y + 2, font_name="F3", font_size=7.5, r=0.45, g=0.5, b=0.55
            )
            pdf.draw_text(
                f"Page {p_idx} of {total_pages}",
                left_margin + table_width, footer_y + 2, font_name="F2", font_size=7.5, r=0.45, g=0.5, b=0.55, align="right"
            )

        return pdf.build_pdf()
