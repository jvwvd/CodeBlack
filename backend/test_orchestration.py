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


class ProcessAndPersistEmailTests(unittest.TestCase):
    def test_missing_email_returns_none_and_never_upserts(self):
        with patch.object(orchestration, "process_stored_email", return_value=None), \
             patch.object(database, "update_processing_state") as mocked_state, \
             patch.object(database, "upsert_email") as mocked_upsert:
            result = orchestration.process_and_persist_email("email_missing")

        self.assertIsNone(result)
        mocked_upsert.assert_not_called()
        mocked_state.assert_called_once_with("email_missing", "processing", last_error=None)

    def test_success_call_order(self):
        fake_result = EmailResult(email_id="email_004", category="GENERAL")
        call_order = []

        def fake_update_state(email_id, processing_status, **kwargs):
            call_order.append(f"state:{processing_status}")
            return {"email_id": email_id, "processing_status": processing_status}

        def fake_process_stored(email_id):
            call_order.append("process_stored_email")
            return fake_result

        def fake_upsert(result):
            call_order.append("upsert_email")
            return {}

        with patch.object(database, "update_processing_state", side_effect=fake_update_state), \
             patch.object(orchestration, "process_stored_email", side_effect=fake_process_stored), \
             patch.object(database, "upsert_email", side_effect=fake_upsert):
            result = orchestration.process_and_persist_email("email_004")

        self.assertEqual(
            call_order,
            ["state:processing", "process_stored_email", "upsert_email", "state:completed"],
        )
        self.assertIs(result, fake_result)

    def test_processing_exception_marks_failed_with_safe_message_and_reraises(self):
        leaky = RuntimeError(
            "connection to https://xyz.supabase.co/rest/v1/emails failed, api_key=SUPER_SECRET_VALUE"
        )
        with patch.object(orchestration, "process_stored_email", side_effect=leaky), \
             patch.object(database, "update_processing_state") as mocked_state, \
             patch.object(database, "upsert_email") as mocked_upsert:
            with self.assertRaises(RuntimeError):
                orchestration.process_and_persist_email("email_010")

        mocked_upsert.assert_not_called()
        failed_call = mocked_state.call_args_list[-1]
        self.assertEqual(failed_call.args, ("email_010", "failed"))
        last_error = failed_call.kwargs["last_error"]
        self.assertNotIn("SUPER_SECRET_VALUE", last_error)
        self.assertNotIn("https://xyz.supabase.co", last_error)

    def test_persistence_exception_marks_failed_and_never_marks_completed(self):
        fake_result = EmailResult(email_id="email_011", category="GENERAL")
        with patch.object(orchestration, "process_stored_email", return_value=fake_result), \
             patch.object(database, "upsert_email", side_effect=RuntimeError("db write failed")), \
             patch.object(database, "update_processing_state") as mocked_state:
            with self.assertRaises(RuntimeError):
                orchestration.process_and_persist_email("email_011")

        statuses = [c.args[1] for c in mocked_state.call_args_list]
        self.assertEqual(statuses, ["processing", "failed"])
        self.assertNotIn("completed", statuses)

    def test_stale_last_error_cleared_on_processing_and_completed(self):
        fake_result = EmailResult(email_id="email_012", category="GENERAL")
        with patch.object(orchestration, "process_stored_email", return_value=fake_result), \
             patch.object(database, "upsert_email", return_value={}), \
             patch.object(database, "update_processing_state") as mocked_state:
            orchestration.process_and_persist_email("email_012")

        for call in mocked_state.call_args_list:
            self.assertIn("last_error", call.kwargs)
            self.assertIsNone(call.kwargs["last_error"])
        statuses = [c.args[1] for c in mocked_state.call_args_list]
        self.assertEqual(statuses, ["processing", "completed"])

    def test_returned_email_result_unchanged(self):
        fake_result = EmailResult(
            email_id="email_013", category="BL_COMPARISON", status="OK",
            notes="No mismatch detected.",
        )
        with patch.object(orchestration, "process_stored_email", return_value=fake_result), \
             patch.object(database, "upsert_email", return_value={}), \
             patch.object(database, "update_processing_state"):
            result = orchestration.process_and_persist_email("email_013")

        self.assertIs(result, fake_result)


class SafeErrorMessageTests(unittest.TestCase):
    def test_secret_bearing_exception_has_secret_absent(self):
        msg = orchestration._safe_error_message(
            RuntimeError("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.super.secret.jwt")
        )
        self.assertNotIn("eyJhbGciOiJIUzI1NiJ9", msg)
        self.assertNotIn("Bearer", msg)
        self.assertIn("RuntimeError", msg)

    def test_url_bearing_exception_has_url_absent(self):
        msg = orchestration._safe_error_message(
            RuntimeError("failed calling https://api.example.com/v1/x?foo=bar")
        )
        self.assertNotIn("https://api.example.com", msg)
        self.assertIn("RuntimeError", msg)

    def test_long_exception_has_raw_text_absent(self):
        huge = "x" * 5000
        msg = orchestration._safe_error_message(RuntimeError(huge))
        self.assertNotIn(huge, msg)
        self.assertIn("RuntimeError", msg)
        self.assertLess(len(msg), 100)

    def test_exception_type_remains_visible_but_message_does_not(self):
        msg = orchestration._safe_error_message(ValueError("email not found"))
        self.assertIn("ValueError", msg)
        self.assertNotIn("email not found", msg)


if __name__ == "__main__":
    unittest.main()
