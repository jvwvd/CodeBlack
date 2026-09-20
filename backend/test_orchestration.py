"""
Regression tests for backend/orchestration.py.

Standard-library unittest + unittest.mock only. Every database.py call and
pipeline.run.process_email are mocked — no real Supabase client, network
call, or AI call is ever made.

Run from inside backend/:
    python -m unittest -v test_orchestration
"""
import unittest
from unittest.mock import patch

import database
import orchestration
from models import EmailResult


class ProcessStoredEmailTests(unittest.TestCase):
    def test_missing_email_returns_none(self):
        with patch.object(database, "get_email", return_value=None) as mocked_get:
            result = orchestration.process_stored_email("email_missing")
        self.assertIsNone(result)
        mocked_get.assert_called_once_with("email_missing")

    def test_organizer_shaped_email_mapping_is_correct(self):
        row = {
            "email_id": "email_004",
            "sender": "docs@example.com",
            "subject": "SI + BL",
            "body": "please compare",
            "source_attachments": ["attachments/email_004_SI.txt", "attachments/email_004_BL.txt"],
        }
        fake_result = EmailResult(email_id="email_004", category="GENERAL")
        with patch.object(database, "get_email", return_value=row), \
             patch.object(database, "list_attachments", return_value=[]), \
             patch.object(orchestration, "process_email", return_value=fake_result) as mocked_process:
            orchestration.process_stored_email("email_004")

        sent_email = mocked_process.call_args.args[0]
        self.assertEqual(sent_email, {
            "email_id": "email_004",
            "from": "docs@example.com",
            "subject": "SI + BL",
            "body": "please compare",
            "attachments": ["attachments/email_004_SI.txt", "attachments/email_004_BL.txt"],
        })

    def test_missing_raw_fields_and_no_attachments_produce_empty_list(self):
        row = {
            "email_id": "email_005", "sender": None, "subject": None, "body": None,
            "source_attachments": None,
        }
        fake_result = EmailResult(email_id="email_005", category="SPAM")
        with patch.object(database, "get_email", return_value=row), \
             patch.object(database, "list_attachments", return_value=[]), \
             patch.object(orchestration, "process_email", return_value=fake_result) as mocked_process:
            orchestration.process_stored_email("email_005")

        sent_email = mocked_process.call_args.args[0]
        self.assertEqual(sent_email["attachments"], [])
        self.assertIsNone(sent_email["from"])

    def test_attachment_bytes_keyed_by_organizer_reference(self):
        row = {
            "email_id": "email_004", "sender": "a@b.com", "subject": "s", "body": "b",
            "source_attachments": ["attachments/email_004_SI.txt", "attachments/email_004_BL.txt"],
        }
        attachment_rows = [
            {"original_filename": "email_004_SI.txt", "storage_path": "email_004/email_004_SI.txt"},
            {"original_filename": "email_004_BL.txt", "storage_path": "email_004/email_004_BL.txt"},
        ]
        fake_result = EmailResult(email_id="email_004", category="BL_COMPARISON")

        def fake_download(storage_path):
            return {
                "email_004/email_004_SI.txt": b"SI BYTES",
                "email_004/email_004_BL.txt": b"BL BYTES",
            }[storage_path]

        with patch.object(database, "get_email", return_value=row), \
             patch.object(database, "list_attachments", return_value=attachment_rows), \
             patch.object(database, "download_document", side_effect=fake_download), \
             patch.object(orchestration, "process_email", return_value=fake_result) as mocked_process:
            orchestration.process_stored_email("email_004")

        sent_attachment_bytes = mocked_process.call_args.kwargs["attachment_bytes"]
        self.assertEqual(sent_attachment_bytes, {
            "attachments/email_004_SI.txt": b"SI BYTES",
            "attachments/email_004_BL.txt": b"BL BYTES",
        })
        # Keys are the ORIGINAL organizer references, never the internal storage paths.
        self.assertNotIn("email_004/email_004_SI.txt", sent_attachment_bytes)

    def test_download_document_called_with_storage_path_not_organizer_path(self):
        row = {
            "email_id": "email_004", "sender": "a", "subject": "s", "body": "b",
            "source_attachments": ["attachments/email_004_SI.txt"],
        }
        attachment_rows = [
            {"original_filename": "email_004_SI.txt", "storage_path": "email_004/email_004_SI.txt"},
        ]
        fake_result = EmailResult(email_id="email_004", category="BL_COMPARISON")
        with patch.object(database, "get_email", return_value=row), \
             patch.object(database, "list_attachments", return_value=attachment_rows), \
             patch.object(database, "download_document", return_value=b"bytes") as mocked_download, \
             patch.object(orchestration, "process_email", return_value=fake_result):
            orchestration.process_stored_email("email_004")

        mocked_download.assert_called_once_with("email_004/email_004_SI.txt")

    def test_missing_attachment_metadata_not_fabricated(self):
        row = {
            "email_id": "email_006", "sender": "a", "subject": "s", "body": "b",
            "source_attachments": ["attachments/email_006_SI.txt", "attachments/email_006_BL.txt"],
        }
        # Only the SI attachment actually made it into public.attachments;
        # the BL one was never successfully imported.
        attachment_rows = [
            {"original_filename": "email_006_SI.txt", "storage_path": "email_006/email_006_SI.txt"},
        ]
        fake_result = EmailResult(email_id="email_006", category="BL_COMPARISON")
        with patch.object(database, "get_email", return_value=row), \
             patch.object(database, "list_attachments", return_value=attachment_rows), \
             patch.object(database, "download_document", return_value=b"SI BYTES") as mocked_download, \
             patch.object(orchestration, "process_email", return_value=fake_result) as mocked_process:
            orchestration.process_stored_email("email_006")

        mocked_download.assert_called_once_with("email_006/email_006_SI.txt")
        sent_attachment_bytes = mocked_process.call_args.kwargs["attachment_bytes"]
        self.assertEqual(list(sent_attachment_bytes.keys()), ["attachments/email_006_SI.txt"])
        self.assertNotIn("attachments/email_006_BL.txt", sent_attachment_bytes)

    def test_ambiguous_duplicate_basename_is_not_guessed(self):
        row = {
            "email_id": "email_007", "sender": "a", "subject": "s", "body": "b",
            "source_attachments": ["attachments/email_007_SI.txt"],
        }
        # Two stored rows happen to share the same original_filename -- ambiguous,
        # must not guess which one is the real match.
        attachment_rows = [
            {"original_filename": "email_007_SI.txt", "storage_path": "email_007/email_007_SI.txt"},
            {"original_filename": "email_007_SI.txt", "storage_path": "email_007/email_007_SI (1).txt"},
        ]
        fake_result = EmailResult(email_id="email_007", category="BL_COMPARISON")
        with patch.object(database, "get_email", return_value=row), \
             patch.object(database, "list_attachments", return_value=attachment_rows), \
             patch.object(database, "download_document") as mocked_download, \
             patch.object(orchestration, "process_email", return_value=fake_result) as mocked_process:
            orchestration.process_stored_email("email_007")

        mocked_download.assert_not_called()
        sent_attachment_bytes = mocked_process.call_args.kwargs["attachment_bytes"]
        self.assertEqual(sent_attachment_bytes, {})

    def test_process_email_receives_expected_email_and_attachment_bytes(self):
        row = {
            "email_id": "email_008", "sender": "a", "subject": "s", "body": "b",
            "source_attachments": [],
        }
        fake_result = EmailResult(email_id="email_008", category="GENERAL")
        with patch.object(database, "get_email", return_value=row), \
             patch.object(database, "list_attachments", return_value=[]), \
             patch.object(orchestration, "process_email", return_value=fake_result) as mocked_process:
            orchestration.process_stored_email("email_008")

        mocked_process.assert_called_once_with(
            {"email_id": "email_008", "from": "a", "subject": "s", "body": "b", "attachments": []},
            attachment_bytes={},
        )

    def test_returned_email_result_is_passed_through_unchanged(self):
        row = {
            "email_id": "email_009", "sender": "a", "subject": "s", "body": "b",
            "source_attachments": [],
        }
        fake_result = EmailResult(
            email_id="email_009", category="BL_COMPARISON", status="MISMATCH",
            defect_fields=["shipper"], has_defect=True,
        )
        with patch.object(database, "get_email", return_value=row), \
             patch.object(database, "list_attachments", return_value=[]), \
             patch.object(orchestration, "process_email", return_value=fake_result):
            result = orchestration.process_stored_email("email_009")

        self.assertIs(result, fake_result)
        self.assertEqual(result.status, "MISMATCH")
        self.assertEqual(result.defect_fields, ["shipper"])


if __name__ == "__main__":
    unittest.main()
