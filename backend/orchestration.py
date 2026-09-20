"""
orchestration.py — bridges Supabase persistence/storage to the existing
Member-1 pipeline, without putting orchestration inside database.py,
main.py, or pipeline/run.py.

The one deliberate place allowed to import both database.py and
pipeline.run/models in the same process (see PROJECT_RULES.md §16). Does
not persist results, does not add API routes, and does not implement any
classification/extraction/comparison/reliability logic itself.
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
