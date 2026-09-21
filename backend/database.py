import time
from collections.abc import Mapping
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Callable, TypeVar

import httpx
from supabase import Client, create_client

from config import settings

DOCUMENTS_BUCKET = "documents"
DEFAULT_SIGNED_URL_EXPIRY_SECONDS = 300

# Bounded retry for transient httpx/network failures (e.g. the
# "[WinError 10035] non-blocking socket operation" ReadErrors observed
# under concurrent Supabase calls during batch-upload processing).
# 3 total attempts, small fixed-step backoff between them.
_TRANSIENT_RETRY_ATTEMPTS = 3
_TRANSIENT_RETRY_BACKOFF_SECONDS = 0.2

_T = TypeVar("_T")


def _call_with_retry(fn: Callable[[], _T]) -> _T:
    """Run fn() with a small bounded retry for transient network failures
    only: httpx.TransportError and its subclasses (ReadError, ConnectError,
    WriteError, TimeoutException, RemoteProtocolError, ...) — errors that
    happen before/without a PostgREST response. Application-level errors
    (postgrest.exceptions.APIError — bad data, constraint violations,
    validation) are never caught here and propagate on the first attempt,
    since they are not transient and retrying them would just repeat the
    same failure.
    """
    attempt = 0
    while True:
        try:
            return fn()
        except httpx.TransportError:
            attempt += 1
            if attempt >= _TRANSIENT_RETRY_ATTEMPTS:
                raise
            time.sleep(_TRANSIENT_RETRY_BACKOFF_SECONDS * attempt)


# Columns owned by upsert_email()/get_email() — mirrors the canonical
# EmailResult shape without importing it (models.py does not exist yet).
_EMAIL_RESULT_FIELDS = (
    "email_id",
    "category",
    "status",
    "si",
    "bl",
    "defect_fields",
    "has_defect",
    "review_reason",
    "decided_by",
    "notes",
)

_UNSET = object()


@lru_cache
def get_supabase_client() -> Client:
    """Lazily construct the shared Supabase client (Postgres + Storage)."""
    if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
        raise RuntimeError(
            "Supabase is not configured: SUPABASE_URL and SUPABASE_KEY "
            "must be set before database or storage access can be used."
        )
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)


def _jsonable(value: Any) -> Any:
    """Convert a Pydantic model to a plain JSON-safe value; pass through otherwise."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _normalize_email_result(result: Any) -> dict:
    if hasattr(result, "model_dump"):
        data = result.model_dump(mode="json", exclude_unset=True)
    elif isinstance(result, Mapping):
        data = dict(result)
    else:
        raise TypeError(
            f"expected a dict or a Pydantic model, got {type(result)!r}"
        )

    if not data.get("email_id"):
        raise ValueError("email result requires a non-empty 'email_id'")

    row = {k: v for k, v in data.items() if k in _EMAIL_RESULT_FIELDS}
    for key in ("si", "bl"):
        if key in row:
            row[key] = _jsonable(row[key])
    return row


def get_email(email_id: str) -> dict | None:
    """Fetch one email row by email_id, or None if it does not exist."""
    client = get_supabase_client()
    response = _call_with_retry(
        lambda: client.table("emails")
        .select("*")
        .eq("email_id", email_id)
        .maybe_single()
        .execute()
    )
    return response.data if response is not None else None


def upsert_email(result: Any) -> dict:
    """Persist an email/result record (dict or Pydantic model) keyed by email_id."""
    row = _normalize_email_result(result)
    client = get_supabase_client()
    response = _call_with_retry(
        lambda: client.table("emails")
        .upsert(row, on_conflict="email_id")
        .execute()
    )
    return response.data[0] if response.data else row


def save_review_correction(
    email_id: str,
    *,
    si: Any,
    bl: Any,
    status: str,
    defect_fields: list[str],
    has_defect: bool,
    review_reason: str | None,
    reviewer_notes: str | None,
) -> dict | None:
    """Persist a human reviewer's SI/BL correction and its recomputed
    result fields, plus reviewer_notes and a fresh reviewed_at timestamp.

    Deliberately separate from upsert_email(): reviewed_at/reviewer_notes
    are excluded from upsert_email()'s canonical EmailResult field set
    (_EMAIL_RESULT_FIELDS), and this never writes the raw source columns
    (sender/subject/body/source_attachments) or processing_status/
    retry_count/last_error. Returns None if email_id does not match any row.
    """
    if not email_id:
        raise ValueError("save_review_correction() requires a non-empty 'email_id'")

    row = {
        "si": _jsonable(si),
        "bl": _jsonable(bl),
        "status": status,
        "defect_fields": defect_fields,
        "has_defect": has_defect,
        "review_reason": review_reason,
        "reviewer_notes": reviewer_notes,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }
    client = get_supabase_client()
    response = (
        client.table("emails")
        .update(row)
        .eq("email_id", email_id)
        .execute()
    )
    return response.data[0] if response.data else None


def upsert_email_source(
    email_id: str,
    *,
    sender: str | None = None,
    subject: str | None = None,
    body: str | None = None,
    source_attachments: list[str] | None = None,
    batch_id: str | None = None,
    original_email_id: str | None = None,
) -> dict:
    """Persist only the raw organizer source fields for an email.

    Writes exactly email_id/sender/subject/body/source_attachments and
    nothing else — never category/status/si/bl/defect_fields/has_defect/
    review_reason/decided_by/notes/processing_status/retry_count/last_error/
    reviewed_at/reviewer_notes. Safe to call repeatedly for the same
    email_id: it only ever updates these same raw columns.

    batch_id/original_email_id are additive, optional columns (see
    schema.sql's batch-upload migration section) used only by batch-upload
    processing: they let two batches reuse the same original organizer
    email_id without colliding, since the row's actual primary key
    (email_id) is a batch-namespaced id such as "batch_xxx__email_004"
    while original_email_id preserves the organizer's own id for exports.
    Both are simply left None for every other caller.
    """
    if not email_id:
        raise ValueError("upsert_email_source() requires a non-empty 'email_id'")

    row = {
        "email_id": email_id,
        "sender": sender,
        "subject": subject,
        "body": body,
        "source_attachments": source_attachments,
        "batch_id": batch_id,
        "original_email_id": original_email_id,
    }
    client = get_supabase_client()
    response = _call_with_retry(
        lambda: client.table("emails")
        .upsert(row, on_conflict="email_id")
        .execute()
    )
    return response.data[0] if response.data else row


def list_emails(
    *,
    status: str | None = None,
    category: str | None = None,
    processing_status: str | None = None,
    batch_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Minimal dashboard listing, optionally filtered by status/category/processing_status/batch_id.

    Sorted by created_at desc, then email_id asc as a deterministic
    tie-breaker, so that paginating with limit/offset never skips or
    duplicates rows that happen to share the same created_at value.
    """
    client = get_supabase_client()
    query = client.table("emails").select("*")
    if status is not None:
        query = query.eq("status", status)
    if category is not None:
        query = query.eq("category", category)
    if processing_status is not None:
        query = query.eq("processing_status", processing_status)
    if batch_id is not None:
        query = query.eq("batch_id", batch_id)
    query = query.order("created_at", desc=True).order("email_id", desc=False)
    response = query.range(offset, offset + limit - 1).execute()
    return response.data


def count_emails(
    *,
    status: str | None = None,
    category: str | None = None,
    processing_status: str | None = None,
    batch_id: str | None = None,
) -> int:
    """Total row count for the same filters list_emails() accepts, ignoring limit/offset."""
    client = get_supabase_client()
    query = client.table("emails").select("*", count="exact")
    if status is not None:
        query = query.eq("status", status)
    if category is not None:
        query = query.eq("category", category)
    if processing_status is not None:
        query = query.eq("processing_status", processing_status)
    if batch_id is not None:
        query = query.eq("batch_id", batch_id)
    response = query.execute()
    return response.count or 0


def update_processing_state(
    email_id: str,
    processing_status: str,
    *,
    retry_count: int | None = _UNSET,
    last_error: str | None = _UNSET,
) -> dict | None:
    """Update processing_status, and optionally retry_count/last_error when supplied."""
    updates: dict = {"processing_status": processing_status}
    if retry_count is not _UNSET:
        updates["retry_count"] = retry_count
    if last_error is not _UNSET:
        updates["last_error"] = last_error

    client = get_supabase_client()
    response = _call_with_retry(
        lambda: client.table("emails")
        .update(updates)
        .eq("email_id", email_id)
        .execute()
    )
    return response.data[0] if response.data else None


def increment_retry_count(email_id: str) -> dict | None:
    """Bump retry_count by exactly 1 for one manual retry attempt.

    Reads the current retry_count and writes back current + 1 (missing/
    None treated as 0). Touches only retry_count — never processing_status
    or last_error, which process_and_persist_email() manages itself right
    after this is called. Returns None if the email does not exist.
    """
    row = get_email(email_id)
    if row is None:
        return None

    next_count = (row.get("retry_count") or 0) + 1
    client = get_supabase_client()
    response = (
        client.table("emails")
        .update({"retry_count": next_count})
        .eq("email_id", email_id)
        .execute()
    )
    return response.data[0] if response.data else {**row, "retry_count": next_count}


def create_attachment_record(
    email_id: str,
    storage_path: str,
    original_filename: str,
    *,
    doc_type: str | None = None,
    storage_bucket: str = DOCUMENTS_BUCKET,
    content_type: str | None = None,
    size_bytes: int | None = None,
) -> dict:
    """Insert/upsert attachment metadata, respecting UNIQUE(email_id, storage_path)."""
    row = {
        "email_id": email_id,
        "storage_path": storage_path,
        "original_filename": original_filename,
        "doc_type": doc_type,
        "storage_bucket": storage_bucket,
        "content_type": content_type,
        "size_bytes": size_bytes,
    }
    client = get_supabase_client()
    response = _call_with_retry(
        lambda: client.table("attachments")
        .upsert(row, on_conflict="email_id,storage_path")
        .execute()
    )
    return response.data[0] if response.data else row


def list_attachments(email_id: str) -> list[dict]:
    """Return attachment rows belonging to the given email."""
    client = get_supabase_client()
    response = _call_with_retry(
        lambda: client.table("attachments")
        .select("*")
        .eq("email_id", email_id)
        .order("created_at")
        .execute()
    )
    return response.data


def upload_document(
    storage_path: str,
    data: bytes,
    *,
    content_type: str | None = None,
    bucket: str = DOCUMENTS_BUCKET,
    upsert: bool = False,
) -> str:
    """Upload raw bytes to the private documents bucket at the caller-supplied path."""
    file_options: dict[str, str] = {}
    if content_type is not None:
        file_options["content-type"] = content_type
    if upsert:
        file_options["upsert"] = "true"

    client = get_supabase_client()
    _call_with_retry(lambda: client.storage.from_(bucket).upload(storage_path, data, file_options or None))
    return storage_path


def download_document(storage_path: str, *, bucket: str = DOCUMENTS_BUCKET) -> bytes:
    """Download raw bytes of a private document by storage_path. No parsing, no classification."""
    client = get_supabase_client()
    return _call_with_retry(lambda: client.storage.from_(bucket).download(storage_path))


def create_signed_document_url(
    storage_path: str,
    *,
    bucket: str = DOCUMENTS_BUCKET,
    expires_in: int = DEFAULT_SIGNED_URL_EXPIRY_SECONDS,
) -> str:
    """Generate a short-lived signed URL for a private document (bucket stays private)."""
    client = get_supabase_client()
    response = client.storage.from_(bucket).create_signed_url(storage_path, expires_in)
    url = response.get("signedURL") or response.get("signedUrl")
    if not url:
        raise RuntimeError(f"Supabase did not return a signed URL for {storage_path!r}")
    return url


# --- Batch upload tracking (see schema.sql's batch-upload migration section) ---


def create_batch(batch_id: str, *, total: int) -> dict:
    """Create (or reset, if re-run with the same id) one batch progress row."""
    row = {
        "batch_id": batch_id,
        "total": total,
        "done": 0,
        "failed": 0,
        "status": "processing",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    }
    client = get_supabase_client()
    response = _call_with_retry(
        lambda: client.table("batches")
        .upsert(row, on_conflict="batch_id")
        .execute()
    )
    return response.data[0] if response.data else row


def get_batch(batch_id: str) -> dict | None:
    """Fetch one batch progress row by batch_id, or None if it does not exist."""
    client = get_supabase_client()
    response = _call_with_retry(
        lambda: client.table("batches")
        .select("*")
        .eq("batch_id", batch_id)
        .maybe_single()
        .execute()
    )
    return response.data if response is not None else None


def update_batch_progress(
    batch_id: str,
    *,
    done: int | None = None,
    failed: int | None = None,
    status: str | None = None,
    finished: bool = False,
) -> dict | None:
    """Update a batch's done/failed counts and/or status. Only the fields
    supplied are written; `finished=True` also stamps `finished_at`."""
    updates: dict = {}
    if done is not None:
        updates["done"] = done
    if failed is not None:
        updates["failed"] = failed
    if status is not None:
        updates["status"] = status
    if finished:
        updates["finished_at"] = datetime.now(timezone.utc).isoformat()
    if not updates:
        return get_batch(batch_id)

    client = get_supabase_client()
    response = _call_with_retry(
        lambda: client.table("batches")
        .update(updates)
        .eq("batch_id", batch_id)
        .execute()
    )
    return response.data[0] if response.data else None
