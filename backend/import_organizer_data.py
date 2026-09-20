"""
import_organizer_data.py — controlled, on-demand organizer bundle -> Supabase import.

Not part of FastAPI startup, not a request handler, not pipeline logic, not
an evaluation script, not a background service. Run manually:

    python import_organizer_data.py <bundle-path-or-http-source>

Uses backend/loader.py's organizer-provided Inbox class (unmodified) to read
the organizer's participant data, and backend/database.py's persistence
helpers to write it into Supabase. Performs no classification, document
identification, extraction, normalization, comparison, or reliability
decisions, and never touches processing/result/review state.
"""
import argparse
import mimetypes
from pathlib import PurePosixPath, PureWindowsPath

import database
from loader import Inbox


def _is_safe_attachment_path(path: str) -> bool:
    """Reject empty, absolute (POSIX or Windows), traversal-style, or filename-less attachment paths."""
    if not path or not path.strip():
        return False
    normalized = path.replace("\\", "/")
    if normalized.startswith("/") or normalized.endswith("/"):
        return False
    if PureWindowsPath(normalized).is_absolute():
        return False
    if any(part == ".." for part in normalized.split("/")):
        return False
    return bool(PurePosixPath(normalized).name)


def _import_attachment(inbox: Inbox, email_id: str, att_path: str) -> None:
    """Read one organizer attachment and persist it under the owning email's Storage prefix."""
    normalized_path = att_path.replace("\\", "/")
    if not _is_safe_attachment_path(normalized_path):
        raise ValueError(f"unsafe attachment path: {att_path!r}")

    raw_bytes = inbox.read_bytes(normalized_path)
    original_filename = PurePosixPath(normalized_path).name
    storage_path = f"{email_id}/{original_filename}"
    content_type, _ = mimetypes.guess_type(original_filename)

    database.upload_document(storage_path, raw_bytes, content_type=content_type, upsert=True)
    database.create_attachment_record(
        email_id,
        storage_path,
        original_filename,
        doc_type=None,
        content_type=content_type,
        size_bytes=len(raw_bytes),
    )


def run_import(source: str) -> dict:
    """Import every organizer email + attachment from `source` into Supabase.

    `source` is passed straight to the organizer's Inbox — a local bundle
    directory or an http(s):// organizer server URL, exactly as loader.py
    already supports. Safe to rerun: source-field upserts and attachment
    uploads/metadata are all idempotent on (email_id[, storage_path]).
    """
    inbox = Inbox(source)
    summary = {
        "total_emails": 0,
        "emails_imported": 0,
        "emails_incomplete": 0,
        "emails_failed": 0,
        "attachments_uploaded": 0,
        "attachment_failures": 0,
        "failures": [],
    }

    for email in inbox.emails():
        summary["total_emails"] += 1
        email_id = email.get("email_id")

        try:
            database.upsert_email_source(
                email_id,
                sender=email.get("from"),
                subject=email.get("subject"),
                body=email.get("body"),
                source_attachments=email.get("attachments", []),
            )
        except Exception as exc:
            summary["emails_failed"] += 1
            summary["failures"].append(
                {"email_id": email_id, "stage": "email_source", "error": str(exc)}
            )
            continue

        attachments_ok = True
        for att_path in email.get("attachments", []):
            try:
                _import_attachment(inbox, email_id, att_path)
                summary["attachments_uploaded"] += 1
            except Exception as exc:
                attachments_ok = False
                summary["attachment_failures"] += 1
                summary["failures"].append(
                    {"email_id": email_id, "stage": "attachment", "path": att_path, "error": str(exc)}
                )

        if attachments_ok:
            summary["emails_imported"] += 1
        else:
            summary["emails_incomplete"] += 1

    return summary


def _print_summary(summary: dict) -> None:
    print("Organizer bundle import summary")
    print(f"  total emails seen:      {summary['total_emails']}")
    print(f"  emails imported (full): {summary['emails_imported']}")
    print(f"  emails incomplete:      {summary['emails_incomplete']}")
    print(f"  emails failed:          {summary['emails_failed']}")
    print(f"  attachments uploaded:   {summary['attachments_uploaded']}")
    print(f"  attachment failures:    {summary['attachment_failures']}")
    if summary["failures"]:
        print("\nFailures:")
        for f in summary["failures"]:
            if "path" in f:
                print(f"  - {f['email_id']} [{f['stage']}] {f['path']}: {f['error']}")
            else:
                print(f"  - {f['email_id']} [{f['stage']}]: {f['error']}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Import the organizer participant bundle (local path or HTTP source) into Supabase."
    )
    parser.add_argument("source", help="Local bundle directory, or an http(s):// organizer server URL")
    args = parser.parse_args(argv)

    summary = run_import(args.source)
    _print_summary(summary)


if __name__ == "__main__":
    main()
