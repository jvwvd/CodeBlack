from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from supabase import Client, create_client

from config import settings

DOCUMENTS_BUCKET = "documents"
DEFAULT_SIGNED_URL_EXPIRY_SECONDS = 300

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
    response = (
        client.table("emails")
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
    response = (
        client.table("emails")
        .upsert(row, on_conflict="email_id")
        .execute()
    )
    return response.data[0] if response.data else row


def list_emails(
    *,
    status: str | None = None,
    category: str | None = None,
    processing_status: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Minimal dashboard listing, optionally filtered by status/category/processing_status."""
    client = get_supabase_client()
    query = client.table("emails").select("*")
    if status is not None:
        query = query.eq("status", status)
    if category is not None:
        query = query.eq("category", category)
    if processing_status is not None:
        query = query.eq("processing_status", processing_status)
    response = query.order("created_at", desc=True).limit(limit).execute()
    return response.data


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
    response = (
        client.table("emails")
        .update(updates)
        .eq("email_id", email_id)
        .execute()
    )
    return response.data[0] if response.data else None


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
    response = (
        client.table("attachments")
        .upsert(row, on_conflict="email_id,storage_path")
        .execute()
    )
    return response.data[0] if response.data else row


def list_attachments(email_id: str) -> list[dict]:
    """Return attachment rows belonging to the given email."""
    client = get_supabase_client()
    response = (
        client.table("attachments")
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
    client.storage.from_(bucket).upload(storage_path, data, file_options or None)
    return storage_path


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
