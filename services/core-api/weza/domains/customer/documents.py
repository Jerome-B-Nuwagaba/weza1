"""Document pipeline (TSD §42, §51; blueprint 10 §8):
UPLOAD → QUARANTINE → MALWARE SCAN → VALIDATION → SECURE STORAGE → CLASSIFICATION → (EXTRACTION) → CONFIRMATION.
Raw, unscanned uploads are never sent to an LLM. Files are encrypted at rest and never exposed by public URL."""

import uuid

from sqlalchemy.orm import Session

from weza.domains.customer.models import Document, DocumentBlob
from weza.domains.trust.service import audit
from weza.platform import classification, crypto
from weza.platform.context import Actor
from weza.platform.errors import ValidationFailed
from weza.platform.events import emit

MAX_BYTES = 10 * 1024 * 1024
DOC_TYPES = {
    "national_id": "National ID", "business_registration": "Business registration certificate",
    "trading_licence": "Trading licence", "bank_statement": "Bank statement (3–6 months)",
    "mobile_money_statement": "Mobile money statement", "payslip": "Recent payslip",
    "employment_letter": "Employment letter", "farm_records": "Farm records / land documents",
    "product_document": "Approved product document", "other": "Other supporting document",
}
MAGIC = {b"%PDF": "application/pdf", b"\xff\xd8\xff": "image/jpeg", b"\x89PNG": "image/png"}
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!"


class BasicScanner:
    """V1-test scanner adapter (blueprint conflict C7): signature + type checks. Production uses ClamAVScanner
    (MALWARE_SCANNER=clamav); the API refuses to start in production with this one."""

    name = "BASIC"

    def scan(self, data: bytes) -> tuple[bool, str]:
        if EICAR in data:
            return False, "malware_signature:EICAR"
        if b"<script" in data[:4096].lower() or data[:2] == b"MZ":
            return False, "suspicious_content"
        return True, "clean"


class ClamAVScanner:
    """Production adapter: streams the bytes to clamd (INSTREAM) over TCP. Fails closed — if clamd can't be reached
    or answers unexpectedly, the file is not stored."""

    name = "CLAMAV"
    CHUNK = 64 * 1024

    def __init__(self, host: str, port: int, timeout: float):
        self.host, self.port, self.timeout = host, port, timeout

    def scan(self, data: bytes) -> tuple[bool, str]:
        ok, result = BasicScanner().scan(data)  # cheap structural checks first
        if not ok:
            return ok, result
        import socket
        import struct
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as s:
                s.sendall(b"zINSTREAM\0")
                for i in range(0, len(data), self.CHUNK):
                    chunk = data[i:i + self.CHUNK]
                    s.sendall(struct.pack(">I", len(chunk)) + chunk)
                s.sendall(struct.pack(">I", 0))
                reply = b""
                while not reply.endswith(b"\0"):
                    part = s.recv(4096)
                    if not part:
                        break
                    reply += part
        except OSError:
            return False, SCAN_UNAVAILABLE
        text = reply.rstrip(b"\0").decode("utf8", "replace").strip()
        if text.endswith(" OK"):
            return True, "clean"
        if text.endswith(" FOUND"):
            return False, "malware_signature:" + text.removeprefix("stream:").removesuffix(" FOUND").strip()[:80]
        return False, SCAN_UNAVAILABLE


SCAN_UNAVAILABLE = "scan_unavailable"


def get_scanner() -> BasicScanner | ClamAVScanner:
    from weza.config import get_settings
    s = get_settings()
    if s.malware_scanner == "clamav":
        return ClamAVScanner(s.clamav_host, s.clamav_port, s.clamav_timeout_seconds)
    return BasicScanner()


def sniff(data: bytes) -> str | None:
    for sig, mime in MAGIC.items():
        if data.startswith(sig):
            return mime
    return None


def ingest(db: Session, customer_id: uuid.UUID, *, doc_type: str, filename: str, declared_mime: str, data: bytes,
           need_id: uuid.UUID | None = None, actor: Actor | None = None) -> Document:
    if doc_type not in DOC_TYPES:
        raise ValidationFailed("Choose a document type.")
    d = Document(customer_id=customer_id, need_id=need_id, doc_type=doc_type, filename=filename[:200],
                 mime=declared_mime[:80], size=len(data), sha256=crypto.sha256_hex(data), pipeline_state="UPLOADED",
                 classification=classification.document_level(doc_type))
    db.add(d)
    db.flush()
    if len(data) > MAX_BYTES:
        return _reject(db, d, "File is larger than 10 MB.")
    ct, wk = crypto.encrypt_bytes(data)
    db.add(DocumentBlob(document_id=d.id, ciphertext=ct, wrapped_key=wk, quarantined=True))
    d.pipeline_state = "QUARANTINED"
    scanner = get_scanner()
    ok, result = scanner.scan(data)
    d.scan_result = f"{scanner.name}:{result}"
    if not ok:
        if result == SCAN_UNAVAILABLE:
            return _reject(db, d, "We couldn't check this file right now, so it was not stored. Please try again "
                                  "in a few minutes.")
        return _reject(db, d, "This file failed our security check and was not stored.")
    d.pipeline_state = "SCANNED"
    real = sniff(data)
    if real is None:
        return _reject(db, d, "Only PDF, JPG or PNG files are accepted.")
    d.mime = real
    d.pipeline_state = "VALIDATED"
    blob = db.get(DocumentBlob, d.id)
    blob.quarantined = False
    d.pipeline_state = "STORED"
    audit(db, actor or Actor(kind="CUSTOMER", id=customer_id, display="customer"), "document.stored", "document", d.id,
          after={"doc_type": doc_type, "size": len(data)})
    emit(db, "DocumentStored", topic="customer", aggregate_type="customer", aggregate_id=customer_id,
         data={"doc_type": doc_type})
    return d


def _reject(db: Session, d: Document, reason: str) -> Document:
    d.pipeline_state, d.reject_reason = "REJECTED", reason
    blob = db.get(DocumentBlob, d.id)
    if blob:
        db.delete(blob)  # never retain rejected/unscanned bytes
    return d


def read_bytes(db: Session, document_id: uuid.UUID) -> bytes | None:
    blob = db.get(DocumentBlob, document_id)
    if blob is None or blob.quarantined:
        return None
    return crypto.decrypt_bytes(blob.ciphertext, blob.wrapped_key)


def describe(d: Document) -> dict:
    return {"id": str(d.id), "doc_type": d.doc_type, "label": DOC_TYPES.get(d.doc_type, d.doc_type),
            "filename": d.filename, "size": d.size, "state": d.pipeline_state, "reason": d.reject_reason,
            "uploaded_at": d.created_at.isoformat() if d.created_at else None}
