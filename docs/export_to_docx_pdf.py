"""
Export Script: Converts Secure_AI_Proctored_Exam_System_FRD.md into .docx and .pdf
Usage:
    python export_to_docx_pdf.py

Prerequisites (install if not present):
    pip install markdown python-docx weasyprint
    - OR -
    pandoc Secure_AI_Proctored_Exam_System_FRD.md -o Secure_AI_Proctored_Exam_System_FRD.docx
    pandoc Secure_AI_Proctored_Exam_System_FRD.md -o Secure_AI_Proctored_Exam_System_FRD.pdf
"""

import os
import sys

DOCS_DIR = os.path.dirname(os.path.abspath(__file__))
MD_PATH = os.path.join(DOCS_DIR, "Secure_AI_Proctored_Exam_System_FRD.md")
DOCX_PATH = os.path.join(DOCS_DIR, "Secure_AI_Proctored_Exam_System_FRD.docx")
PDF_PATH = os.path.join(DOCS_DIR, "Secure_AI_Proctored_Exam_System_FRD.pdf")
HTML_PATH = os.path.join(DOCS_DIR, "Secure_AI_Proctored_Exam_System_FRD.html")

def generate_styled_html():
    """Generates a standalone styled HTML file suitable for 1-click Print to PDF or Word import."""
    print("Reading markdown file...")
    with open(MD_PATH, "r", encoding="utf-8") as f:
        md_text = f.read()

    try:
        import markdown
        html_body = markdown.markdown(md_text, extensions=['tables', 'fenced_code', 'toc'])
    except ImportError:
        print("[Notice] 'markdown' package not installed. Generating semantic HTML wrapper.")
        # Minimal conversion for headers and paragraphs
        lines = md_text.splitlines()
        body_parts = []
        for line in lines:
            if line.startswith("# "):
                body_parts.append(f"<h1>{line[2:]}</h1>")
            elif line.startswith("## "):
                body_parts.append(f"<h2>{line[3:]}</h2>")
            elif line.startswith("### "):
                body_parts.append(f"<h3>{line[4:]}</h3>")
            elif line.startswith("#### "):
                body_parts.append(f"<h4>{line[5:]}</h4>")
            elif line.startswith("```"):
                body_parts.append("<pre><code>")
            elif line.startswith("|"):
                body_parts.append(f"<p style='font-family: monospace;'>{line}</p>")
            elif line.strip() == "":
                body_parts.append("<br/>")
            else:
                body_parts.append(f"<p>{line}</p>")
        html_body = "\n".join(body_parts)

    html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Functional Requirements Document - Secure AI-Proctored Examination System</title>
    <style>
        body {{
            font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, Helvetica, Arial, sans-serif;
            color: #1a202c;
            line-height: 1.6;
            margin: 40px auto;
            max-width: 900px;
            padding: 0 20px;
        }}
        h1 {{
            color: #1a365d;
            border-bottom: 2px solid #2b6cb0;
            padding-bottom: 8px;
            margin-top: 40px;
            font-size: 26pt;
        }}
        h2 {{
            color: #2b6cb0;
            border-bottom: 1px solid #e2e8f0;
            padding-bottom: 6px;
            margin-top: 32px;
            font-size: 18pt;
            page-break-before: always;
        }}
        h3 {{
            color: #2d3748;
            margin-top: 20px;
            font-size: 14pt;
        }}
        table {{
            border-collapse: collapse;
            width: 100%;
            margin: 20px 0;
            font-size: 10pt;
        }}
        th, td {{
            border: 1px solid #cbd5e0;
            padding: 8px 12px;
            text-align: left;
        }}
        th {{
            background-color: #edf2f7;
            font-weight: 600;
            color: #2d3748;
        }}
        tr:nth-child(even) {{
            background-color: #f7fafc;
        }}
        code {{
            background-color: #edf2f7;
            padding: 2px 6px;
            border-radius: 4px;
            font-family: 'Consolas', 'Courier New', monospace;
            font-size: 9.5pt;
        }}
        pre {{
            background-color: #2d3748;
            color: #f7fafc;
            padding: 14px;
            border-radius: 6px;
            overflow-x: auto;
        }}
        pre code {{
            background-color: transparent;
            color: inherit;
        }}
        blockquote {{
            border-left: 4px solid #3182ce;
            margin: 16px 0;
            padding: 8px 16px;
            background-color: #ebf8ff;
            color: #2b6cb0;
        }}
        @media print {{
            body {{
                max-width: 100%;
                margin: 0;
                padding: 10mm;
                font-size: 10pt;
            }}
            h2 {{
                page-break-before: always;
            }}
        }}
    </style>
</head>
<body>
{html_body}
</body>
</html>
"""
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html_template)
    print(f"Generated standalone styled HTML: {HTML_PATH}")
    print("Tip: Open this HTML in Chrome or Edge, press Ctrl+P -> 'Save as PDF' to generate the official PDF!")

def convert_with_pandoc():
    """Attempts conversion using pandoc if installed in system PATH."""
    try:
        import subprocess
        print("Checking pandoc...")
        subprocess.run(["pandoc", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        print("Running pandoc to create DOCX...")
        subprocess.run(["pandoc", MD_PATH, "-o", DOCX_PATH], check=True)
        print(f"Created: {DOCX_PATH}")
    except Exception as e:
        print(f"Pandoc not available or failed: {e}")

if __name__ == "__main__":
    generate_styled_html()
    convert_with_pandoc()
