"""
Regression tests for backend/database.py.

Standard-library unittest + unittest.mock only. Every test patches
database.get_supabase_client (or, for RuntimeError-path testing, the
underlying settings values) with a fake — no real Supabase client is ever
constructed, and no network/storage/database operation ever occurs.

Run from inside backend/:
    python -m unittest -v test_database
"""
import unittest
from unittest.mock import MagicMock, patch

import database

# Captured immediately after import, before any test runs or patches
# anything — proves importing database.py alone never constructs a client.
_CACHE_INFO_AT_IMPORT = database.get_supabase_client.cache_info()


def _fake_client_with_table_chain(execute_return):
    """A MagicMock client whose table(...).<chain>.execute() returns execute_return."""
    client = MagicMock()
    table_mock = client.table.return_value
    for method in ("select", "eq", "upsert", "update", "order", "limit", "maybe_single"):
        getattr(table_mock, method).return_value = table_mock
    table_mock.execute.return_value = execute_return
    return client, table_mock


class LazyClientTests(unittest.TestCase):
    def test_import_does_not_construct_a_client(self):
        self.assertEqual(_CACHE_INFO_AT_IMPORT.hits, 0)
        self.assertEqual(_CACHE_INFO_AT_IMPORT.misses, 0)

    def test_raises_runtime_error_without_credentials(self):
        # Never constructs a real client: the function raises before reaching
        # create_client(), and functools.lru_cache never memoizes a raised
        # exception, so this cannot leak into or affect any other test.
        with patch.object(database.settings, "SUPABASE_URL", None), \
             patch.object(database.settings, "SUPABASE_KEY", None):
            with self.assertRaises(RuntimeError):
                database.get_supabase_client()


class UpsertEmailTests(unittest.TestCase):
    def test_dict_input_writes_only_canonical_fields(self):
        resp = MagicMock(data=[{"email_id": "email_001", "category": "GENERAL"}])
        client, table_mock = _fake_client_with_table_chain(resp)
        payload = {
            "email_id": "email_001",
            "category": "GENERAL",
            "status": "OK",
            "sender": "leak@example.com",
            "subject": "leaked subject",
            "body": "leaked body",
            "source_attachments": ["should", "not", "appear"],
        }
        with patch.object(database, "get_supabase_client", return_value=client):
            result = database.upsert_email(payload)

        sent_row = table_mock.upsert.call_args.args[0]
        self.assertEqual(sent_row["email_id"], "email_001")
        self.assertEqual(sent_row["category"], "GENERAL")
        for raw_field in ("sender", "subject", "body", "source_attachments"):
            self.assertNotIn(raw_field, sent_row)
        self.assertEqual(table_mock.upsert.call_args.kwargs["on_conflict"], "email_id")
        self.assertEqual(result, {"email_id": "email_001", "category": "GENERAL"})

    def test_pydantic_like_model_input_is_accepted(self):
        class FakeModel:
            def model_dump(self, mode="python", exclude_unset=False):
                return {"email_id": "email_002", "status": "MISMATCH"}

        resp = MagicMock(data=[{"email_id": "email_002"}])
        client, table_mock = _fake_client_with_table_chain(resp)
        with patch.object(database, "get_supabase_client", return_value=client):
            database.upsert_email(FakeModel())
        sent_row = table_mock.upsert.call_args.args[0]
        self.assertEqual(sent_row, {"email_id": "email_002", "status": "MISMATCH"})

    def test_requires_email_id(self):
        with self.assertRaises(ValueError):
            database._normalize_email_result({"category": "GENERAL"})

    def test_rejects_unsupported_type(self):
        with self.assertRaises(TypeError):
            database._normalize_email_result(12345)


class UpsertEmailSourceTests(unittest.TestCase):
    def test_writes_exactly_the_five_raw_fields(self):
        resp = MagicMock(data=[{"email_id": "email_004"}])
        client, table_mock = _fake_client_with_table_chain(resp)
        with patch.object(database, "get_supabase_client", return_value=client):
            database.upsert_email_source(
                "email_004", sender="a@b.com", subject="s", body="b", source_attachments=["x"]
            )
        sent_row = table_mock.upsert.call_args.args[0]
        self.assertEqual(
            sent_row,
            {"email_id": "email_004", "sender": "a@b.com", "subject": "s", "body": "b", "source_attachments": ["x"]},
        )
        self.assertEqual(table_mock.upsert.call_args.kwargs["on_conflict"], "email_id")

    def test_cannot_be_called_with_processing_or_result_fields(self):
        # The keyword-only signature has no parameter for these at all — passing
        # one raises TypeError before any Supabase call is attempted, which is a
        # stronger guarantee than a runtime filter.
        with self.assertRaises(TypeError):
            database.upsert_email_source("email_004", status="OK")  # type: ignore[call-arg]

    def test_requires_non_empty_email_id(self):
        with self.assertRaises(ValueError):
            database.upsert_email_source("")


class SaveReviewCorrectionTests(unittest.TestCase):
    def test_writes_exactly_the_review_columns(self):
        resp = MagicMock(data=[{"email_id": "email_004", "status": "OK"}])
        client, table_mock = _fake_client_with_table_chain(resp)
        with patch.object(database, "get_supabase_client", return_value=client):
            result = database.save_review_correction(
                "email_004",
                si={"shipper": "ACME"},
                bl={"shipper": "ACME"},
                status="OK",
                defect_fields=[],
                has_defect=False,
                review_reason=None,
                reviewer_notes="looks fine",
            )
        sent_row = table_mock.update.call_args.args[0]
        self.assertEqual(
            set(sent_row),
            {"si", "bl", "status", "defect_fields", "has_defect", "review_reason", "reviewer_notes", "reviewed_at"},
        )
        for raw_field in ("sender", "subject", "body", "source_attachments", "processing_status", "retry_count", "last_error"):
            self.assertNotIn(raw_field, sent_row)
        self.assertEqual(sent_row["status"], "OK")
        self.assertEqual(sent_row["reviewer_notes"], "looks fine")
        self.assertIsInstance(sent_row["reviewed_at"], str)
        table_mock.eq.assert_called_once_with("email_id", "email_004")
        self.assertEqual(result, {"email_id": "email_004", "status": "OK"})

    def test_pydantic_like_si_bl_are_serialized(self):
        resp = MagicMock(data=[{"email_id": "email_004"}])
        client, table_mock = _fake_client_with_table_chain(resp)

        class FakeShipmentFields:
            def model_dump(self, mode="python"):
                return {"shipper": "ACME"}

        with patch.object(database, "get_supabase_client", return_value=client):
            database.save_review_correction(
                "email_004",
                si=FakeShipmentFields(),
                bl=FakeShipmentFields(),
                status="OK",
                defect_fields=[],
                has_defect=False,
                review_reason=None,
                reviewer_notes=None,
            )
        sent_row = table_mock.update.call_args.args[0]
        self.assertEqual(sent_row["si"], {"shipper": "ACME"})
        self.assertEqual(sent_row["bl"], {"shipper": "ACME"})

    def test_no_matching_row_returns_none(self):
        resp = MagicMock(data=[])
        client, table_mock = _fake_client_with_table_chain(resp)
        with patch.object(database, "get_supabase_client", return_value=client):
            result = database.save_review_correction(
                "email_missing",
                si=None, bl=None, status="NEEDS_REVIEW", defect_fields=[],
                has_defect=False, review_reason="missing_value", reviewer_notes=None,
            )
        self.assertIsNone(result)

    def test_requires_non_empty_email_id(self):
        with self.assertRaises(ValueError):
            database.save_review_correction(
                "", si=None, bl=None, status="OK", defect_fields=[],
                has_defect=False, review_reason=None, reviewer_notes=None,
            )


class ListEmailsTests(unittest.TestCase):
    def test_no_filters_uses_defaults(self):
        resp = MagicMock(data=[])
        client, table_mock = _fake_client_with_table_chain(resp)
        with patch.object(database, "get_supabase_client", return_value=client):
            result = database.list_emails()
        self.assertEqual(result, [])
        table_mock.eq.assert_not_called()
        table_mock.order.assert_called_once_with("created_at", desc=True)
        table_mock.limit.assert_called_once_with(100)

    def test_category_filter(self):
        resp = MagicMock(data=[{"email_id": "e1"}])
        client, table_mock = _fake_client_with_table_chain(resp)
        with patch.object(database, "get_supabase_client", return_value=client):
            result = database.list_emails(category="BL_COMPARISON")
        table_mock.eq.assert_called_once_with("category", "BL_COMPARISON")
        self.assertEqual(result, [{"email_id": "e1"}])

    def test_status_filter(self):
        resp = MagicMock(data=[])
        client, table_mock = _fake_client_with_table_chain(resp)
        with patch.object(database, "get_supabase_client", return_value=client):
            database.list_emails(status="NEEDS_REVIEW")
        table_mock.eq.assert_called_once_with("status", "NEEDS_REVIEW")

    def test_processing_status_filter(self):
        resp = MagicMock(data=[])
        client, table_mock = _fake_client_with_table_chain(resp)
        with patch.object(database, "get_supabase_client", return_value=client):
            database.list_emails(processing_status="failed")
        table_mock.eq.assert_called_once_with("processing_status", "failed")

    def test_limit_passed_through(self):
        resp = MagicMock(data=[])
        client, table_mock = _fake_client_with_table_chain(resp)
        with patch.object(database, "get_supabase_client", return_value=client):
            database.list_emails(limit=5)
        table_mock.limit.assert_called_once_with(5)


class UpdateProcessingStateTests(unittest.TestCase):
    def test_only_processing_status_by_default(self):
        resp = MagicMock(data=[{"email_id": "email_001", "processing_status": "processing"}])
        client, table_mock = _fake_client_with_table_chain(resp)
        with patch.object(database, "get_supabase_client", return_value=client):
            database.update_processing_state("email_001", "processing")
        sent = table_mock.update.call_args.args[0]
        self.assertEqual(sent, {"processing_status": "processing"})

    def test_sentinel_allows_explicit_none_to_clear_last_error(self):
        resp = MagicMock(data=[{"email_id": "email_001"}])
        client, table_mock = _fake_client_with_table_chain(resp)
        with patch.object(database, "get_supabase_client", return_value=client):
            database.update_processing_state("email_001", "completed", retry_count=2, last_error=None)
        sent = table_mock.update.call_args.args[0]
        self.assertEqual(sent, {"processing_status": "completed", "retry_count": 2, "last_error": None})

    def test_not_found_returns_none(self):
        resp = MagicMock(data=[])
        client, table_mock = _fake_client_with_table_chain(resp)
        with patch.object(database, "get_supabase_client", return_value=client):
            result = database.update_processing_state("email_missing", "failed")
        self.assertIsNone(result)


class CreateAttachmentRecordTests(unittest.TestCase):
    def test_expected_metadata_mapping_with_doc_type_none(self):
        resp = MagicMock(data=[{"id": "uuid-1"}])
        client, table_mock = _fake_client_with_table_chain(resp)
        with patch.object(database, "get_supabase_client", return_value=client):
            result = database.create_attachment_record(
                "email_004", "email_004/SI.txt", "SI.txt",
                doc_type=None, content_type="text/plain", size_bytes=42,
            )
        sent_row = table_mock.upsert.call_args.args[0]
        self.assertEqual(sent_row, {
            "email_id": "email_004",
            "storage_path": "email_004/SI.txt",
            "original_filename": "SI.txt",
            "doc_type": None,
            "storage_bucket": "documents",
            "content_type": "text/plain",
            "size_bytes": 42,
        })
        self.assertEqual(table_mock.upsert.call_args.kwargs["on_conflict"], "email_id,storage_path")
        self.assertEqual(result, {"id": "uuid-1"})


class ListAttachmentsTests(unittest.TestCase):
    def test_filters_by_email_id(self):
        resp = MagicMock(data=[{"id": "uuid-1"}])
        client, table_mock = _fake_client_with_table_chain(resp)
        with patch.object(database, "get_supabase_client", return_value=client):
            result = database.list_attachments("email_004")
        table_mock.eq.assert_called_once_with("email_id", "email_004")
        self.assertEqual(result, [{"id": "uuid-1"}])


class UploadDocumentTests(unittest.TestCase):
    def test_uploads_with_content_type_to_documents_bucket(self):
        client = MagicMock()
        bucket_mock = client.storage.from_.return_value
        with patch.object(database, "get_supabase_client", return_value=client):
            path = database.upload_document("email_004/SI.txt", b"hello", content_type="text/plain")
        client.storage.from_.assert_called_once_with("documents")
        bucket_mock.upload.assert_called_once_with("email_004/SI.txt", b"hello", {"content-type": "text/plain"})
        self.assertEqual(path, "email_004/SI.txt")

    def test_upsert_true_sets_expected_file_option(self):
        client = MagicMock()
        bucket_mock = client.storage.from_.return_value
        with patch.object(database, "get_supabase_client", return_value=client):
            database.upload_document("email_004/SI.txt", b"hello", upsert=True)
        bucket_mock.upload.assert_called_once_with("email_004/SI.txt", b"hello", {"upsert": "true"})

    def test_no_options_passes_none(self):
        client = MagicMock()
        bucket_mock = client.storage.from_.return_value
        with patch.object(database, "get_supabase_client", return_value=client):
            database.upload_document("email_004/SI.txt", b"hello")
        bucket_mock.upload.assert_called_once_with("email_004/SI.txt", b"hello", None)


class DownloadDocumentTests(unittest.TestCase):
    def test_returns_bytes_from_mocked_storage(self):
        client = MagicMock()
        bucket_mock = client.storage.from_.return_value
        bucket_mock.download.return_value = b"raw pdf bytes"
        with patch.object(database, "get_supabase_client", return_value=client):
            result = database.download_document("email_004/SI.pdf")
        client.storage.from_.assert_called_once_with("documents")
        bucket_mock.download.assert_called_once_with("email_004/SI.pdf")
        self.assertEqual(result, b"raw pdf bytes")


class CreateSignedDocumentUrlTests(unittest.TestCase):
    def test_uses_documents_bucket_and_default_expiry(self):
        client = MagicMock()
        bucket_mock = client.storage.from_.return_value
        bucket_mock.create_signed_url.return_value = {
            "signedURL": "https://example/signed", "signedUrl": "https://example/signed",
        }
        with patch.object(database, "get_supabase_client", return_value=client):
            url = database.create_signed_document_url("email_004/SI.txt")
        client.storage.from_.assert_called_once_with("documents")
        bucket_mock.create_signed_url.assert_called_once_with(
            "email_004/SI.txt", database.DEFAULT_SIGNED_URL_EXPIRY_SECONDS
        )
        self.assertEqual(url, "https://example/signed")

    def test_missing_url_in_response_raises(self):
        client = MagicMock()
        bucket_mock = client.storage.from_.return_value
        bucket_mock.create_signed_url.return_value = {"signedURL": None, "signedUrl": None}
        with patch.object(database, "get_supabase_client", return_value=client):
            with self.assertRaises(RuntimeError):
                database.create_signed_document_url("nope.txt")


class EmailResultFieldsTests(unittest.TestCase):
    def test_contains_only_the_canonical_email_result_fields(self):
        expected = {
            "email_id", "category", "status", "si", "bl", "defect_fields",
            "has_defect", "review_reason", "decided_by", "notes",
        }
        self.assertEqual(set(database._EMAIL_RESULT_FIELDS), expected)

    def test_excludes_raw_source_and_processing_fields(self):
        forbidden = {
            "sender", "subject", "body", "source_attachments",
            "processing_status", "retry_count", "last_error",
            "reviewed_at", "reviewer_notes",
        }
        self.assertTrue(forbidden.isdisjoint(database._EMAIL_RESULT_FIELDS))


if __name__ == "__main__":
    unittest.main()
