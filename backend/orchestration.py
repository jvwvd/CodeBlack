"""
orchestration.py — bridges Supabase persistence/storage to the existing
Member-1 pipeline, without putting orchestration inside database.py,
main.py, or pipeline/run.py.

The one deliberate place allowed to import both database.py and
pipeline.run/models in the same process (see PROJECT_RULES.md §16).
process_stored_email() itself does not persist results or add API routes;
process_and_persist_email() is the explicit persistence wrapper around it.
Neither implements any classification/extraction/comparison/reliability
logic itself.
"""
from pathlib import PurePosixPath

import database
from models import EmailResult
from pipeline.run import process_email


def _reconstruct_email(row: dict) -> dict:
    return {
        "email_id": row["email_id"],
        "from": row.get("sender"),
        "subject": row.get("subject"),
        "body": row.get("body"),
        "attachments": row.get("source_attachments") or [],
    }


def _build_attachment_bytes(email_id: str, organizer_paths: list[str]) -> dict[str, bytes]:
    """Download bytes for each organizer attachment reference that has an
    unambiguous matching stored row, keyed by the ORIGINAL organizer path
    string (pipeline.documents.load_pair() looks attachments up by that
    exact key). Never fabricates a mapping: a reference with no matching
    row, or with more than one same-named row, is simply left absent so
    the pipeline's own reliability checks handle it."""
    rows = database.list_attachments(email_id)

    basename_counts: dict[str, int] = {}
    basename_to_row: dict[str, dict] = {}
    for row in rows:
        name = row.get("original_filename")
        if not name:
            continue
        basename_counts[name] = basename_counts.get(name, 0) + 1
        basename_to_row[name] = row

    attachment_bytes: dict[str, bytes] = {}
    for organizer_path in organizer_paths:
        basename = PurePosixPath(organizer_path).name
        if basename_counts.get(basename, 0) != 1:
            # No matching row, or an ambiguous (duplicate) basename — do not guess.
            continue
        storage_path = basename_to_row[basename].get("storage_path")
        if not storage_path:
            continue
        attachment_bytes[organizer_path] = database.download_document(storage_path)

    return attachment_bytes


def process_stored_email(email_id: str) -> EmailResult | None:
    """Read one imported email and its attachments from Supabase, run it
    through the pipeline, and return the resulting EmailResult unchanged.

    Returns None if the email does not exist. Does not persist the result —
    that remains the caller's explicit, separate decision.
    """
    row = database.get_email(email_id)
    if row is None:
        return None

    email = _reconstruct_email(row)
    attachment_bytes = _build_attachment_bytes(email_id, email["attachments"])

    return process_email(email, attachment_bytes=attachment_bytes)


def _safe_error_message(exc: Exception) -> str:
    """A generic, bounded summary safe to store in emails.last_error.

    Deliberately never includes any portion of str(exc): regex-based
    redaction can miss formats such as "Authorization: Bearer <token>",
    JWTs, connection strings, provider payloads, or other unanticipated
    credential shapes. Only the exception's class name is exposed — the
    API already returns a generic 500 to callers regardless.
    """
    return f"{type(exc).__name__}: processing failed"


def process_and_persist_email(email_id: str) -> EmailResult | None:
    """Run one stored email through the pipeline and persist the result,
    tracking processing_status/last_error around the attempt.

    Returns None (without persisting anything) if the email does not
    exist. On success, persists the EmailResult via database.upsert_email()
    and returns it unchanged. On any unexpected exception during processing
    or persistence, marks processing_status = "failed" with a safe,
    sanitized error summary and re-raises so main.py's existing generic
    exception handler returns the standard safe 500 response.

    Deliberately does not add retry/concurrency/idempotency guards.
    """
    database.update_processing_state(email_id, "processing", last_error=None)

    try:
        result = process_stored_email(email_id)
        if result is None:
            return None
        database.upsert_email(result)
    except Exception as exc:
        database.update_processing_state(
            email_id, "failed", last_error=_safe_error_message(exc)
        )
        raise

    database.update_processing_state(email_id, "completed", last_error=None)
    return result
