import hashlib
import datetime
from PIL import Image
from backend.config import Config
from backend.models import db, EvidenceRecord, ViolationLog
from backend.utils.logger import get_logger

logger = get_logger()

class EvidenceService:
    @staticmethod
    def save_evidence(attempt_id, event_type, file_stream, violation_log_id=None):
        """Processes, compresses, hashes, and stores a captured violation frame."""
        try:
            # Guarantee evidence directory exists on dynamic load
            Config.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
            
            # Generate clean filename
            timestamp_str = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = f"evidence_{attempt_id}_{event_type.lower()}_{timestamp_str}.jpg"
            dest_path = Config.EVIDENCE_DIR / filename

            # Open image stream using Pillow
            img = Image.open(file_stream)
            
            # Convert to RGB (in case of PNG/RGBA upload)
            if img.mode != "RGB":
                img = img.convert("RGB")
                
            # Resize image if it's excessively large (e.g. limit to 800px width/height)
            img.thumbnail((800, 600))
            
            # Save with compression (quality=70 to reduce size)
            img.save(dest_path, "JPEG", quality=70)
            
            # Read back compressed file to compute hash and file size
            with open(dest_path, "rb") as f:
                content = f.read()
                file_hash = hashlib.sha256(content).hexdigest()
                file_size = len(content)

            # Save metadata to database
            record = EvidenceRecord(
                violation_log_id=violation_log_id,
                attempt_id=attempt_id,
                file_path=str(dest_path.relative_to(Config.EVIDENCE_DIR.parent)), # Save relative path
                file_hash=file_hash,
                file_size=file_size,
                content_type="image/jpeg"
            )
            
            db.session.add(record)
            db.session.commit()
            
            # Associate record back to ViolationLog if provided
            if violation_log_id:
                vlog = ViolationLog.query.get(violation_log_id)
                if vlog:
                    vlog.action_taken = vlog.action_taken # triggers database dirty check
                    db.session.commit()

            logger.info(f"Evidence saved for attempt {attempt_id}, event: {event_type}. File size: {file_size} bytes.")
            return record

        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to process and save evidence: {str(e)}")
            return None
