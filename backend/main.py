import csv
import io
import json
import logging
import mimetypes
import uuid
from datetime import datetime, timezone
from pathlib import PurePosixPath

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

import database
import orchestration
from config import settings
from models import ReviewCorrectionRequest

logger = logging.getLogger("sdoc.backend")

# --- Export (Feature F-A) ---------------------------------------------------

EXPORT_MAX_ROWS = 100_000

_SEVEN_FIELDS = (
    "shipper",
    "consignee",
    "notify_party",
    "port_of_loading",
    "port_of_discharge",
    "container_count",
    "gross_weight_kg",
)

EXPORT_COLUMNS = [
    "email_id",
    "sender",
    "subject",
    "category",
    "status",
    "review_reason",
    "has_defect",
    "defect_fields",
    "decided_by",
    "updated_at",
] + [f"{side}_{field}" for field in _SEVEN_FIELDS for side in ("si", "bl")]


def _export_row(email: dict) -> dict:
    """Project one raw `emails` row (as returned by database.list_emails())
    into the flat export shape. Unprocessed emails naturally come through
    with empty/None result columns since si/bl/category/etc. are simply
    absent or None on those rows."""
    si = email.get("si") or {}
    bl = email.get("bl") or {}
    row = {
        "email_id": email.get("email_id"),
        "sender": email.get("sender"),
        "subject": email.get("subject"),
        "category": email.get("category"),
        "status": email.get("status"),
        "review_reason": email.get("review_reason"),
        "has_defect": email.get("has_defect"),
        "defect_fields": email.get("defect_fields") or [],
        "decided_by": email.get("decided_by"),
        "updated_at": email.get("updated_at"),
    }
    for field in _SEVEN_FIELDS:
        row[f"si_{field}"] = si.get(field)
        row[f"bl_{field}"] = bl.get(field)
    return row


def _export_filename(fmt: str) -> str:
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"codeblack_results_{date_str}.{fmt}"


# --- Upload (Feature F-B) ---------------------------------------------------

UPLOAD_ID_PREFIX = "upload_"
ALLOWED_UPLOAD_EXTENSIONS = {".txt", ".pdf", ".docx", ".xlsx"}
MAX_UPLOAD_FILES = 5
MAX_UPLOAD_FILE_BYTES = 10 * 1024 * 1024


def _sanitize_upload_filename(filename: str) -> str:
    """Strip any path parts from a client-supplied filename, keeping only the basename."""
    name = PurePosixPath((filename or "").replace("\\", "/")).name
    if not name or name in (".", ".."):
        raise HTTPException(status_code=400, detail=f"invalid file name: {filename!r}")
    return name


app = FastAPI(title="Shipping Document Verification Backend")

allowed_origins = ["http://localhost:5173"]
if settings.FRONTEND_URL:
    allowed_origins.append(settings.FRONTEND_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled error while serving %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/emails")
def list_emails(
    status: str | None = None,
    category: str | None = None,
    processing_status: str | None = None,
    limit: int = 100,
):
    items = database.list_emails(
        status=status,
        category=category,
        processing_status=processing_status,
        limit=limit,
    )
    return {"items": items, "count": len(items)}


@app.get("/api/emails/export")
def export_emails(
    format: str = Query("json", pattern="^(csv|json)$"),
    status: str | None = None,
    category: str | None = None,
    processing_status: str | None = None,
):
    # Declared before GET /api/emails/{email_id} so FastAPI does not match
    # "export" as an email_id path parameter.
    emails = database.list_emails(
        status=status,
        category=category,
        processing_status=processing_status,
        limit=EXPORT_MAX_ROWS,
    )
    rows = [_export_row(email) for email in emails]
    filename = _export_filename(format)

    if format == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=EXPORT_COLUMNS)
        writer.writeheader()
        for row in rows:
            csv_row = dict(row)
            csv_row["defect_fields"] = ";".join(row["defect_fields"])
            writer.writerow(csv_row)
        return Response(
            content=buffer.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    return Response(
        content=json.dumps(rows, default=str),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/api/emails/{email_id}")
def get_email(email_id: str):
    email = database.get_email(email_id)
    if email is None:
        raise HTTPException(status_code=404, detail=f"email not found: {email_id}")
    return email


@app.get("/api/emails/{email_id}/attachments")
def list_email_attachments(email_id: str):
    items = database.list_attachments(email_id)
    return {"items": items, "count": len(items)}


@app.get("/api/documents/signed-url")
def get_signed_document_url(path: str = Query(..., min_length=1)):
    cleaned = path.strip()
    if not cleaned or ".." in cleaned:
        raise HTTPException(status_code=400, detail="invalid document path")
    url = database.create_signed_document_url(cleaned)
    return {"url": url, "expires_in": database.DEFAULT_SIGNED_URL_EXPIRY_SECONDS}


@app.post("/api/emails/{email_id}/process")
def process_email_endpoint(email_id: str):
    result = orchestration.process_and_persist_email(email_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"email not found: {email_id}")
    return result


@app.post("/api/emails/{email_id}/retry")
def retry_email_endpoint(email_id: str):
    result = orchestration.retry_and_persist_email(email_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"email not found: {email_id}")
    return result


@app.patch("/api/emails/{email_id}/review")
def review_email_endpoint(email_id: str, body: ReviewCorrectionRequest):
    updated = orchestration.apply_review_correction(
        email_id,
        si=body.si,
        bl=body.bl,
        reviewer_notes=body.reviewer_notes,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"email not found: {email_id}")
    return updated


@app.post("/api/emails/upload")
async def upload_email(
    subject: str = Form(...),
    body: str = Form(...),
    sender: str | None = Form(None),
    files: list[UploadFile] = File(default=[]),
):
    if len(files) > MAX_UPLOAD_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"too many files: at most {MAX_UPLOAD_FILES} allowed, got {len(files)}",
        )

    # Validate every file before persisting anything, so a rejected file
    # never leaves a partially-uploaded record behind.
    validated: list[tuple[str, bytes, str | None]] = []
    for upload in files:
        filename = _sanitize_upload_filename(upload.filename or "")
        extension = PurePosixPath(filename).suffix.lower()
        if extension not in ALLOWED_UPLOAD_EXTENSIONS:
            allowed = ", ".join(sorted(ALLOWED_UPLOAD_EXTENSIONS))
            raise HTTPException(
                status_code=400,
                detail=f"unsupported file type {extension!r} for {filename!r}; allowed: {allowed}",
            )
        data = await upload.read()
        if len(data) > MAX_UPLOAD_FILE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"file too large: {filename!r} exceeds {MAX_UPLOAD_FILE_BYTES // (1024 * 1024)}MB",
            )
        content_type, _ = mimetypes.guess_type(filename)
        validated.append((filename, data, content_type))

    email_id = f"{UPLOAD_ID_PREFIX}{uuid.uuid4().hex[:12]}"

    # Store attachments + create the email/attachment records the same way
    # import_organizer_data.py does (database.upload_document,
    # database.create_attachment_record, database.upsert_email_source).
    for filename, data, content_type in validated:
        storage_path = f"{email_id}/{filename}"
        database.upload_document(storage_path, data, content_type=content_type, upsert=True)
        database.create_attachment_record(
            email_id,
            storage_path,
            filename,
            doc_type=None,
            content_type=content_type,
            size_bytes=len(data),
        )

    database.upsert_email_source(
        email_id,
        sender=sender,
        subject=subject,
        body=body,
        source_attachments=[filename for filename, _, _ in validated],
    )

    try:
        result = orchestration.process_and_persist_email(email_id)
    except Exception:
        # Record is already created; keep it and return its current state
        # (processing_status="failed", last_error set) so the frontend can
        # surface it and call POST /api/emails/{email_id}/retry.
        logger.exception("upload processing failed for %s", email_id)
        return database.get_email(email_id)

    return result
