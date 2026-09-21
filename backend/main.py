import concurrent.futures
import csv
import io
import json
import logging
import mimetypes
import re
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from email import message_from_bytes
from email import policy as email_policy
from pathlib import PurePosixPath

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
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
MAX_UPLOAD_FILES = 20
MAX_UPLOAD_FILE_BYTES = 25 * 1024 * 1024
MAX_UPLOAD_TOTAL_BYTES = 100 * 1024 * 1024

ZIP_MAX_FILES = 50
ZIP_MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024

BATCH_ID_PREFIX = "batch_"
BATCH_WORKERS = 3
BUNDLE_MAX_FILES = 5000
BUNDLE_MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
BUNDLE_MAX_UPLOAD_BYTES = MAX_UPLOAD_TOTAL_BYTES  # 100MB, same ceiling as a generic request

_KIND_CONTENT_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "json": "application/json",
    "eml": "message/rfc822",
    "txt": "text/plain",
}

_EML_HEADER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*:\s")


def _sanitize_upload_filename(filename: str) -> str:
    """Strip any path parts from a client-supplied filename, keeping only the basename."""
    name = PurePosixPath((filename or "").replace("\\", "/")).name
    if not name or name in (".", ".."):
        raise HTTPException(status_code=400, detail=f"invalid file name: {filename!r}")
    return name


async def _read_upload_capped(upload: UploadFile, max_bytes: int) -> bytes:
    """Read an UploadFile in chunks, aborting with 413 as soon as the cap is
    exceeded rather than buffering the whole (potentially huge) body first."""
    chunks: list[bytes] = []
    total = 0
    chunk_size = 1024 * 1024
    while True:
        chunk = await upload.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"file {upload.filename!r} exceeds max size of {max_bytes} bytes",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _initial_read_cap(filename: str) -> int:
    # A .zip might turn out to be an organizer-bundle upload (Task 2, up to
    # 100MB); everything else is capped at the regular per-file limit
    # straight away so an oversized non-zip file aborts mid-stream.
    if PurePosixPath(filename).suffix.lower() == ".zip":
        return MAX_UPLOAD_TOTAL_BYTES
    return MAX_UPLOAD_FILE_BYTES


def _looks_like_eml(data: bytes) -> bool:
    try:
        head = data[:4000].decode("utf-8", errors="ignore")
    except Exception:
        return False
    lines = head.splitlines()
    if not lines or not _EML_HEADER_RE.match(lines[0]):
        return False
    return ("\n\n" in head) or ("\r\n\r\n" in head)


def _is_organizer_json(data: bytes) -> bool:
    try:
        record = json.loads(data.decode("utf-8"))
    except Exception:
        return False
    return isinstance(record, dict) and {"email_id", "from", "subject", "body", "attachments"} <= record.keys()


def _sniff_file_kind(filename: str, data: bytes) -> str:
    """Best-effort file-type detection: magic bytes first, extension as
    fallback. Returns one of: txt, pdf, docx, xlsx, zip, eml, json, other."""
    ext = PurePosixPath(filename).suffix.lower()

    if data.startswith(b"%PDF-"):
        return "pdf"

    if data[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = zf.namelist()
        except Exception:
            return "zip" if ext == ".zip" else "other"
        if any(n.startswith("word/") for n in names):
            return "docx"
        if any(n.startswith("xl/") for n in names):
            return "xlsx"
        if ext == ".docx":
            return "docx"
        if ext == ".xlsx":
            return "xlsx"
        return "zip"

    stripped = data.lstrip()
    if stripped[:1] in (b"{", b"[") and (_is_organizer_json(data) or ext == ".json"):
        try:
            json.loads(data.decode("utf-8"))
            return "json"
        except Exception:
            pass

    if _looks_like_eml(data):
        return "eml"

    if ext in (".txt", ".pdf", ".docx", ".xlsx", ".zip", ".eml", ".json"):
        return ext[1:]

    return "other"


def _content_type_for(filename: str, kind: str) -> str | None:
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or _KIND_CONTENT_TYPES.get(kind, "application/octet-stream")


def _find_bundle_root(names: list[str]) -> str | None:
    """If this zip's contents look like the organizer's inbox/*.json +
    attachments/ bundle shape (optionally wrapped in one outer folder),
    return the root prefix to strip; otherwise None."""
    for name in names:
        match = re.match(r"^(.*?)inbox/[^/]+\.json$", name)
        if match:
            root = match.group(1)
            if any(n.startswith(root + "attachments/") for n in names):
                return root
    return None


def _is_safe_zip_path(path: str) -> bool:
    """Zip-slip guard for bundle processing, where the relative directory
    structure (inbox/, attachments/) must be preserved. Rejects absolute
    paths and any ".." path component."""
    posix_path = PurePosixPath(path.replace("\\", "/"))
    if posix_path.is_absolute():
        return False
    return ".." not in posix_path.parts


def _extract_zip_entries(
    zf: zipfile.ZipFile, *, max_files: int, max_uncompressed_bytes: int
) -> list[tuple[str, bytes]]:
    """Extract a plain (non-bundle) zip's entries in memory, one level deep.

    Zip-slip protection: only the basename of each entry is kept (per-task
    requirement), so path traversal in an entry name is neutralized by
    construction. __MACOSX/ and .DS_Store entries are skipped silently.
    Zip-bomb protection: rejects zips with too many files or too much
    uncompressed content before any bytes are extracted.
    """
    infos = [
        info
        for info in zf.infolist()
        if not info.is_dir()
        and not info.filename.startswith("__MACOSX/")
        and PurePosixPath(info.filename.replace("\\", "/")).name != ".DS_Store"
    ]

    if len(infos) > max_files:
        raise HTTPException(
            status_code=413,
            detail=f"zip contains too many files: {len(infos)} > {max_files} allowed",
        )

    total_uncompressed = sum(info.file_size for info in infos)
    if total_uncompressed > max_uncompressed_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"zip uncompressed size too large: {total_uncompressed} bytes > {max_uncompressed_bytes} allowed",
        )

    entries: list[tuple[str, bytes]] = []
    used_names: set[str] = set()
    for info in infos:
        base = PurePosixPath(info.filename.replace("\\", "/")).name
        if not base or base in (".", ".."):
            continue
        name = base
        counter = 1
        while name in used_names:
            stem, dot, ext_part = base.rpartition(".")
            name = f"{stem}_{counter}{dot}{ext_part}" if dot else f"{base}_{counter}"
            counter += 1
        used_names.add(name)
        entries.append((name, zf.read(info)))
    return entries


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
    format: str = Query("json", pattern="^(csv|json|submission)$"),
    status: str | None = None,
    category: str | None = None,
    processing_status: str | None = None,
    batch_id: str | None = None,
):
    # Declared before GET /api/emails/{email_id} so FastAPI does not match
    # "export" as an email_id path parameter.
    emails = database.list_emails(
        status=status,
        category=category,
        processing_status=processing_status,
        batch_id=batch_id,
        limit=EXPORT_MAX_ROWS,
    )

    if format == "submission":
        # Organizer submission shape: {email_id: {category, status,
        # review_reason, defect_fields, has_defect}}, keyed by the ORIGINAL
        # organizer email_id. Batch-processed rows are stored under a
        # synthetic, batch-namespaced email_id (see schema.sql's batch
        # migration note) with the real id preserved in original_email_id;
        # every other row simply has original_email_id = None, so it falls
        # back to its own email_id.
        submission = {}
        for email in emails:
            key = email.get("original_email_id") or email.get("email_id")
            submission[key] = {
                "category": email.get("category"),
                "status": email.get("status"),
                "review_reason": email.get("review_reason"),
                "defect_fields": email.get("defect_fields") or [],
                "has_defect": email.get("has_defect"),
            }
        filename = _export_filename("json")
        return Response(
            content=json.dumps(submission, default=str),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
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


def _process_new_email(email_id: str):
    """Reuse orchestration.process_and_persist_email() unchanged; on an
    unexpected processing failure the already-created record is kept and
    returned as-is (processing_status="failed") so the frontend can surface
    it and call POST /api/emails/{email_id}/retry — same contract as before."""
    try:
        result = orchestration.process_and_persist_email(email_id)
    except Exception:
        logger.exception("upload processing failed for %s", email_id)
        return database.get_email(email_id)
    return result


def _store_attachment(email_id: str, filename: str, data: bytes, kind: str) -> None:
    storage_path = f"{email_id}/{filename}"
    content_type = _content_type_for(filename, kind)
    database.upload_document(storage_path, data, content_type=content_type, upsert=True)
    database.create_attachment_record(
        email_id, storage_path, filename, doc_type=None, content_type=content_type, size_bytes=len(data)
    )


def _create_email_from_attachments(
    entries: list[tuple[str, bytes, str]], *, subject: str, body: str, sender: str | None
):
    """.txt/.pdf/.docx/.xlsx and any other (unrecognized) file type are all
    handled the same way here: stored and attached to one new email using
    the multipart form's subject/body. An unrecognized type is deliberately
    NOT an upload-time error — the pipeline marks that email NEEDS_REVIEW/
    unreadable downstream, which is the expected outcome."""
    email_id = f"{UPLOAD_ID_PREFIX}{uuid.uuid4().hex[:12]}"
    filenames = [filename for filename, _, _ in entries]

    # Parent row must exist before any attachment row references it
    # (attachments.email_id -> emails.email_id foreign key).
    database.upsert_email_source(
        email_id, sender=sender, subject=subject, body=body, source_attachments=filenames
    )

    for filename, data, kind in entries:
        _store_attachment(email_id, filename, data, kind)

    return _process_new_email(email_id)


def _create_email_from_eml(data: bytes):
    """Parse an .eml with Python's stdlib email package and import it as
    one new email, extracting sender/subject/body/attachments from it."""
    msg = message_from_bytes(data, policy=email_policy.default)
    sender = str(msg.get("From")) if msg.get("From") is not None else None
    subject = str(msg.get("Subject")) if msg.get("Subject") is not None else ""

    body_text = ""
    body_part = msg.get_body(preferencelist=("plain", "html"))
    if body_part is not None:
        try:
            body_text = body_part.get_content()
        except Exception:
            body_text = ""

    email_id = f"{UPLOAD_ID_PREFIX}{uuid.uuid4().hex[:12]}"

    attachments: list[tuple[str, bytes, str]] = []
    for index, part in enumerate(msg.iter_attachments(), start=1):
        raw_name = part.get_filename() or f"attachment_{index}"
        att_name = _sanitize_upload_filename(raw_name)
        try:
            att_data = part.get_content()
        except Exception:
            continue
        if isinstance(att_data, str):
            att_data = att_data.encode("utf-8", errors="replace")
        elif not isinstance(att_data, (bytes, bytearray)):
            continue
        att_data = bytes(att_data)
        attachments.append((att_name, att_data, _sniff_file_kind(att_name, att_data)))

    # Parent row must exist before any attachment row references it
    # (attachments.email_id -> emails.email_id foreign key).
    database.upsert_email_source(
        email_id, sender=sender, subject=subject, body=body_text,
        source_attachments=[name for name, _, _ in attachments],
    )

    for att_name, att_data, kind in attachments:
        _store_attachment(email_id, att_name, att_data, kind)

    return _process_new_email(email_id)


def _create_email_from_organizer_json(data: bytes):
    """Import a single email from organizer-inbox-format JSON
    (email_id/from/subject/body/attachments). No attachment bytes accompany
    a bare JSON upload — any attachment it references is simply absent, and
    the pipeline's own reliability checks handle that (missing_attachment/
    unreadable), same as any other incomplete email."""
    record = json.loads(data.decode("utf-8"))
    email_id = f"{UPLOAD_ID_PREFIX}{uuid.uuid4().hex[:12]}"
    database.upsert_email_source(
        email_id,
        sender=record.get("from"),
        subject=record.get("subject"),
        body=record.get("body"),
        source_attachments=record.get("attachments") or [],
    )
    return _process_new_email(email_id)


def _run_batch(batch_id: str, root: str, records: list[dict], attachment_cache: dict[str, bytes]) -> None:
    """Process one upload batch with a pool of BATCH_WORKERS workers,
    calling orchestration.process_and_persist_email() for each email. A
    failure on one email is recorded (failed count) and never aborts the
    rest of the batch. Each email keeps its ORIGINAL organizer email_id in
    original_email_id while being persisted under a batch-namespaced
    synthetic email_id, so two batches sharing the same original email_id
    never collide (see schema.sql's batch migration note)."""
    done = 0
    failed = 0
    lock = threading.Lock()

    def process_one(record: dict) -> bool:
        original_id = record.get("email_id")
        composite_id = f"{batch_id}__{original_id}"
        try:
            attachments = record.get("attachments") or []

            # Parent row must exist before any attachment row references it
            # (attachments.email_id -> emails.email_id foreign key).
            database.upsert_email_source(
                composite_id,
                sender=record.get("from"),
                subject=record.get("subject"),
                body=record.get("body"),
                source_attachments=attachments,
                batch_id=batch_id,
                original_email_id=original_id,
            )

            for att_path in attachments:
                zip_path = root + att_path
                data = attachment_cache.get(zip_path)
                if data is None:
                    continue
                basename = PurePosixPath(att_path).name
                kind = _sniff_file_kind(basename, data)
                _store_attachment(composite_id, basename, data, kind)

            orchestration.process_and_persist_email(composite_id)
            return True
        except Exception:
            logger.exception("batch %s: failed to process %s", batch_id, original_id)
            return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=BATCH_WORKERS) as executor:
        futures = [executor.submit(process_one, record) for record in records]
        for future in concurrent.futures.as_completed(futures):
            ok = future.result()
            with lock:
                if ok:
                    done += 1
                else:
                    failed += 1
                database.update_batch_progress(batch_id, done=done, failed=failed)

    database.update_batch_progress(batch_id, status="completed", finished=True)


def _handle_bundle_upload(zf: zipfile.ZipFile, root: str, background_tasks: BackgroundTasks) -> dict:
    """Route an organizer-bundle-shaped zip (inbox/*.json + attachments/)
    to batch handling: create a batch record, then process every email in
    the background with a pool of workers, returning immediately."""
    infos = {info.filename: info for info in zf.infolist() if not info.is_dir()}
    relevant = [
        (name, info)
        for name, info in infos.items()
        if name.startswith(root)
        and not name[len(root):].startswith("__MACOSX/")
        and PurePosixPath(name).name != ".DS_Store"
        and _is_safe_zip_path(name)
    ]
    if len(relevant) > BUNDLE_MAX_FILES:
        raise HTTPException(
            status_code=413,
            detail=f"bundle contains too many files: {len(relevant)} > {BUNDLE_MAX_FILES} allowed",
        )
    total_uncompressed = sum(info.file_size for _, info in relevant)
    if total_uncompressed > BUNDLE_MAX_UNCOMPRESSED_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"bundle uncompressed size too large: {total_uncompressed} bytes > {BUNDLE_MAX_UNCOMPRESSED_BYTES} allowed",
        )

    inbox_paths = sorted(
        name for name in infos
        if name.startswith(root + "inbox/") and name.endswith(".json") and _is_safe_zip_path(name)
    )
    records: list[dict] = []
    for path in inbox_paths:
        try:
            record = json.loads(zf.read(path).decode("utf-8"))
        except Exception:
            continue
        if isinstance(record, dict) and record.get("email_id"):
            records.append(record)

    # Snapshot referenced attachment bytes now: the zip's underlying bytes
    # are request-scoped and must not be depended on from the background
    # task after this request has returned.
    attachment_cache: dict[str, bytes] = {}
    for record in records:
        for att_path in record.get("attachments") or []:
            zip_path = root + att_path
            if zip_path in attachment_cache or zip_path not in infos or not _is_safe_zip_path(zip_path):
                continue
            attachment_cache[zip_path] = zf.read(zip_path)

    batch_id = f"{BATCH_ID_PREFIX}{uuid.uuid4().hex[:12]}"
    database.create_batch(batch_id, total=len(records))
    background_tasks.add_task(_run_batch, batch_id, root, records, attachment_cache)

    return {"batch_id": batch_id, "total": len(records), "status": "processing"}


@app.post("/api/emails/upload")
async def upload_email(
    background_tasks: BackgroundTasks,
    subject: str | None = Form(None),
    body: str | None = Form(None),
    sender: str | None = Form(None),
    files: list[UploadFile] = File(default=[]),
):
    if len(files) > MAX_UPLOAD_FILES:
        raise HTTPException(
            status_code=413,
            detail=f"too many files: at most {MAX_UPLOAD_FILES} allowed, got {len(files)}",
        )

    # Read every top-level file first (capped so an oversized file aborts
    # mid-stream rather than being fully buffered), then classify it.
    top_level: list[tuple[str, bytes]] = []
    running_total = 0
    for upload in files:
        filename = _sanitize_upload_filename(upload.filename or "")
        data = await _read_upload_capped(upload, _initial_read_cap(filename))
        running_total += len(data)
        if running_total > MAX_UPLOAD_TOTAL_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"upload exceeds total request size limit of {MAX_UPLOAD_TOTAL_BYTES} bytes",
            )
        top_level.append((filename, data))

    # Expand into a flat worklist, inlining one level of zip contents. A
    # zip shaped like the organizer's inbox/*.json + attachments/ bundle is
    # routed to batch handling instead and returns immediately.
    worklist: list[tuple[str, bytes, str]] = []
    for filename, data in top_level:
        kind = _sniff_file_kind(filename, data)
        if kind == "zip":
            try:
                zf = zipfile.ZipFile(io.BytesIO(data))
                names = zf.namelist()
            except zipfile.BadZipFile:
                raise HTTPException(status_code=400, detail=f"{filename!r} is not a valid zip file")

            root = _find_bundle_root(names)
            if root is not None:
                return _handle_bundle_upload(zf, root, background_tasks)

            if len(data) > MAX_UPLOAD_FILE_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"file {filename!r} exceeds max size of {MAX_UPLOAD_FILE_BYTES} bytes",
                )
            entries = _extract_zip_entries(zf, max_files=ZIP_MAX_FILES, max_uncompressed_bytes=ZIP_MAX_UNCOMPRESSED_BYTES)
            for entry_name, entry_data in entries:
                worklist.append((entry_name, entry_data, _sniff_file_kind(entry_name, entry_data)))
        else:
            if len(data) > MAX_UPLOAD_FILE_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"file {filename!r} exceeds max size of {MAX_UPLOAD_FILE_BYTES} bytes",
                )
            worklist.append((filename, data, kind))

    # .eml and organizer-format .json entries each carry their own
    # sender/subject/body and become their own independent email; every
    # other kind (txt/pdf/docx/xlsx/zip-passthrough/other) is an attachment
    # merged into one shared email using the form's subject/body.
    structured_items: list[tuple[str, bytes]] = []
    attachment_entries: list[tuple[str, bytes, str]] = []
    for name, data, kind in worklist:
        if kind == "eml":
            structured_items.append(("eml", data))
        elif kind == "json" and _is_organizer_json(data):
            structured_items.append(("json", data))
        else:
            attachment_entries.append((name, data, kind))

    created: list = []
    for kind, data in structured_items:
        if kind == "eml":
            created.append(_create_email_from_eml(data))
        else:
            created.append(_create_email_from_organizer_json(data))

    need_form_email = bool(attachment_entries) or not structured_items
    if need_form_email:
        if subject is None or body is None:
            raise HTTPException(
                status_code=422,
                detail="subject and body are required unless an .eml or organizer-format .json file is uploaded",
            )
        created.append(_create_email_from_attachments(attachment_entries, subject=subject, body=body, sender=sender))

    if len(created) == 1:
        return created[0]
    return {"emails": created}


@app.get("/api/batches/{batch_id}")
def get_batch_endpoint(batch_id: str):
    batch = database.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"batch not found: {batch_id}")
    return batch
