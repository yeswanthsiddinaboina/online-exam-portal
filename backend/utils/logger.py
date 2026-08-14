import logging
import os
from pathlib import Path

# Setup logs directory
project_root = Path(__file__).resolve().parent.parent.parent
logs_dir = project_root / "logs"
logs_dir.mkdir(exist_ok=True)

# Create a logger
logger = logging.getLogger("secure_exam_system")
logger.setLevel(logging.INFO)

# Avoid adding multiple handlers if logger is already configured
if not logger.handlers:
    # Formatter
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s in %(module)s (Line %(lineno)d): %(message)s"
    )
    
    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File Handler
    file_handler = logging.FileHandler(logs_dir / "system.log", encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

def get_logger():
    return logger
