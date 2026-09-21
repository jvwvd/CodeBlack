"""
Regression tests for backend/main.py.

Standard-library unittest + unittest.mock only. Every database.py call is
mocked at the module attribute main.py actually resolves at call time
(`database.<function>`, since main.py does `import database`) — no real
Supabase client, network call, or credential is ever touched.

Run from inside backend/:
    python -m unittest -v test_main
"""
import io
import json
import threading
import unittest
import zipfile
from unittest.mock import patch

from fastapi.testclient import TestClient

import database
import main
import orchestration
from models import EmailResult, ShipmentFields

client = TestClient(main.app, raise_server_exceptions=False)


class HealthEndpointTests(unittest.TestCase):
    def test_health_returns_200_and_status_ok(self):
        response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


class ListEmailsEndpointTests(unittest.TestCase):
    def test_default_call_returns_items_and_count(self):
        fake_rows = [{"email_id": "email_001"}, {"email_id": "email_002"}]
        with patch.object(database, "list_emails", return_value=fake_rows) as mocked:
            response = client.get("/api/emails")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"items": fake_rows, "count": 2})
        mocked.assert_called_once_with(status=None, category=None, processing_status=None, limit=100)

    def test_empty_result_is_valid(self):
        with patch.object(database, "list_emails", return_value=[]):
            response = client.get("/api/emails")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"items": [], "count": 0})

    def test_category_filter_passed_through(self):
        with patch.object(database, "list_emails", return_value=[]) as mocked:
            client.get("/api/emails?category=BL_COMPARISON")
        mocked.assert_called_once_with(status=None, category="BL_COMPARISON", processing_status=None, limit=100)

    def test_status_filter_passed_through(self):
        with patch.object(database, "list_emails", return_value=[]) as mocked:
            client.get("/api/emails?status=NEEDS_REVIEW")
        mocked.assert_called_once_with(status="NEEDS_REVIEW", category=None, processing_status=None, limit=100)

    def test_processing_status_filter_passed_through(self):
        with patch.object(database, "list_emails", return_value=[]) as mocked:
            client.get("/api/emails?processing_status=failed")
        mocked.assert_called_once_with(status=None, category=None, processing_status="failed", limit=100)

    def test_limit_passed_through(self):
        with patch.object(database, "list_emails", return_value=[]) as mocked:
            client.get("/api/emails?limit=5")
        mocked.assert_called_once_with(status=None, category=None, processing_status=None, limit=5)


class GetEmailEndpointTests(unittest.TestCase):
    def test_existing_email_returns_200(self):
        fake = {"email_id": "email_004", "status": "OK"}
        with patch.object(database, "get_email", return_value=fake) as mocked:
            response = client.get("/api/emails/email_004")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), fake)
        mocked.assert_called_once_with("email_004")

    def test_missing_email_returns_404(self):
        with patch.object(database, "get_email", return_value=None):
            response = client.get("/api/emails/email_999")
        self.assertEqual(response.status_code, 404)
        self.assertIn("email_999", response.json()["detail"])


class ListAttachmentsEndpointTests(unittest.TestCase):
    def test_returns_items_and_count(self):
        fake_rows = [{"id": "uuid-1", "email_id": "email_004"}]
        with patch.object(database, "list_attachments", return_value=fake_rows) as mocked:
            response = client.get("/api/emails/email_004/attachments")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"items": fake_rows, "count": 1})
        mocked.assert_called_once_with("email_004")

    def test_unknown_email_id_returns_empty_list_not_404(self):
        # Preserves the ACTUAL current contract: this endpoint never checks that
        # the parent email exists first — an unknown email_id simply produces
        # whatever database.list_attachments() returns for it (an empty list),
        # identical to a real email with zero attachments. Not inventing a new
        # 404-on-unknown-email behavior that main.py does not implement.
        with patch.object(database, "list_attachments", return_value=[]) as mocked:
            response = client.get("/api/emails/email_does_not_exist/attachments")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"items": [], "count": 0})
        mocked.assert_called_once_with("email_does_not_exist")


class SignedUrlEndpointTests(unittest.TestCase):
    def test_valid_path_returns_signed_url(self):
        with patch.object(database, "create_signed_document_url", return_value="https://example/signed") as mocked:
            response = client.get("/api/documents/signed-url?path=email_004/email_004_SI.txt")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"url": "https://example/signed", "expires_in": database.DEFAULT_SIGNED_URL_EXPIRY_SECONDS},
        )
        mocked.assert_called_once_with("email_004/email_004_SI.txt")

    def test_missing_path_param_returns_422(self):
        response = client.get("/api/documents/signed-url")
        self.assertEqual(response.status_code, 422)

    def test_empty_path_returns_422(self):
        # Query(..., min_length=1) rejects a zero-length value before the
        # handler body ever runs.
        response = client.get("/api/documents/signed-url?path=")
        self.assertEqual(response.status_code, 422)

    def test_whitespace_only_path_returns_400(self):
        # Explicit backstop: if main.py's validation ever regresses, this must
        # fail fast in-process instead of silently reaching real Supabase.
        with patch.object(
            database, "create_signed_document_url",
            side_effect=AssertionError("must not reach Supabase for rejected path"),
        ):
            response = client.get("/api/documents/signed-url?path=%20%20%20")
        self.assertEqual(response.status_code, 400)

    def test_leading_traversal_rejected(self):
        with patch.object(
            database, "create_signed_document_url",
            side_effect=AssertionError("must not reach Supabase for rejected path"),
        ):
            response = client.get("/api/documents/signed-url?path=../file.txt")
        self.assertEqual(response.status_code, 400)

    def test_embedded_traversal_rejected(self):
        with patch.object(
            database, "create_signed_document_url",
            side_effect=AssertionError("must not reach Supabase for rejected path"),
        ):
            response = client.get("/api/documents/signed-url?path=attachments/../file.txt")
        self.assertEqual(response.status_code, 400)

    def test_backslash_traversal_rejected(self):
        # main.py's current check is a plain "'..' in cleaned" substring test
        # (not the separator-aware normalization import_organizer_data.py's own
        # _is_safe_attachment_path performs). It still rejects this input
        # because the literal substring ".." is present either way.
        with patch.object(
            database, "create_signed_document_url",
            side_effect=AssertionError("must not reach Supabase for rejected path"),
        ):
            response = client.get("/api/documents/signed-url?path=..\\file.txt")
        self.assertEqual(response.status_code, 400)


class ProcessEmailEndpointTests(unittest.TestCase):
    def test_success_returns_200_with_canonical_email_result_body(self):
        fake_result = EmailResult(
            email_id="email_004", category="BL_COMPARISON", status="OK",
            notes="No mismatch detected.",
        )
        with patch.object(
            orchestration, "process_and_persist_email", return_value=fake_result
        ) as mocked:
            response = client.post("/api/emails/email_004/process")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), fake_result.model_dump(mode="json"))
        mocked.assert_called_once_with("email_004")

    def test_unknown_email_returns_404(self):
        with patch.object(orchestration, "process_and_persist_email", return_value=None):
            response = client.post("/api/emails/email_missing/process")
        self.assertEqual(response.status_code, 404)
        self.assertIn("email_missing", response.json()["detail"])

    def test_orchestration_exception_returns_generic_500_without_leaking_details(self):
        with patch.object(
            orchestration, "process_and_persist_email",
            side_effect=RuntimeError("internal failure with api_key=SUPER_SECRET_VALUE"),
        ):
            response = client.post("/api/emails/email_004/process")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"detail": "internal server error"})
        self.assertNotIn("SUPER_SECRET_VALUE", response.text)
        self.assertNotIn("RuntimeError", response.text)


class RetryEmailEndpointTests(unittest.TestCase):
    def test_successful_retry_returns_200_with_canonical_result_body(self):
        fake_result = EmailResult(
            email_id="email_004", category="BL_COMPARISON", status="OK",
            notes="No mismatch detected.",
        )
        with patch.object(
            orchestration, "retry_and_persist_email", return_value=fake_result
        ) as mocked:
            response = client.post("/api/emails/email_004/retry")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), fake_result.model_dump(mode="json"))
        mocked.assert_called_once_with("email_004")

    def test_missing_email_returns_404(self):
        with patch.object(orchestration, "retry_and_persist_email", return_value=None):
            response = client.post("/api/emails/email_missing/retry")
        self.assertEqual(response.status_code, 404)
        self.assertIn("email_missing", response.json()["detail"])

    def test_retry_calls_orchestration_not_database_directly(self):
        # Endpoint must delegate to orchestration.retry_and_persist_email()
        # rather than reimplementing retry_count/processing logic in main.py.
        fake_result = EmailResult(email_id="email_004", category="GENERAL")
        with patch.object(
            orchestration, "retry_and_persist_email", return_value=fake_result
        ) as mocked_orchestration, \
             patch.object(database, "increment_retry_count") as mocked_increment:
            response = client.post("/api/emails/email_004/retry")
        self.assertEqual(response.status_code, 200)
        mocked_orchestration.assert_called_once_with("email_004")
        mocked_increment.assert_not_called()

    def test_failed_retry_returns_generic_500_without_leaking_details(self):
        with patch.object(
            orchestration, "retry_and_persist_email",
            side_effect=RuntimeError("internal failure with api_key=SUPER_SECRET_VALUE"),
        ):
            response = client.post("/api/emails/email_004/retry")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"detail": "internal server error"})
        self.assertNotIn("SUPER_SECRET_VALUE", response.text)
        self.assertNotIn("RuntimeError", response.text)


class ReviewEmailEndpointTests(unittest.TestCase):
    def test_successful_correction_returns_200_with_updated_row(self):
        fake_row = {
            "email_id": "email_010", "status": "OK", "defect_fields": [], "has_defect": False,
            "reviewer_notes": "confirmed", "reviewed_at": "2026-09-21T00:00:00+00:00",
        }
        with patch.object(orchestration, "apply_review_correction", return_value=fake_row) as mocked:
            response = client.patch(
                "/api/emails/email_010/review",
                json={
                    "si": {"shipper": "ACME"},
                    "bl": {"shipper": "ACME"},
                    "reviewer_notes": "confirmed",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), fake_row)
        mocked.assert_called_once()
        call_kwargs = mocked.call_args.kwargs
        self.assertEqual(call_kwargs["si"], ShipmentFields(shipper="ACME"))
        self.assertEqual(call_kwargs["bl"], ShipmentFields(shipper="ACME"))
        self.assertEqual(call_kwargs["reviewer_notes"], "confirmed")
        self.assertEqual(mocked.call_args.args, ("email_010",))

    def test_review_resulting_in_ok(self):
        fake_row = {"email_id": "email_010", "status": "OK", "defect_fields": [], "has_defect": False}
        with patch.object(orchestration, "apply_review_correction", return_value=fake_row):
            response = client.patch(
                "/api/emails/email_010/review",
                json={
                    "si": {"shipper": "ACME"},
                    "bl": {"shipper": "ACME"},
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "OK")

    def test_review_resulting_in_mismatch(self):
        fake_row = {
            "email_id": "email_010", "status": "MISMATCH",
            "defect_fields": ["shipper"], "has_defect": True,
        }
        with patch.object(orchestration, "apply_review_correction", return_value=fake_row):
            response = client.patch(
                "/api/emails/email_010/review",
                json={"si": {"shipper": "ACME"}, "bl": {"shipper": "OTHER"}},
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "MISMATCH")
        self.assertEqual(body["defect_fields"], ["shipper"])
        self.assertTrue(body["has_defect"])

    def test_missing_email_returns_404(self):
        with patch.object(orchestration, "apply_review_correction", return_value=None):
            response = client.patch(
                "/api/emails/email_missing/review",
                json={"reviewer_notes": "n/a"},
            )
        self.assertEqual(response.status_code, 404)
        self.assertIn("email_missing", response.json()["detail"])

    def test_partial_correction_only_si_supplied(self):
        with patch.object(orchestration, "apply_review_correction", return_value={"status": "OK"}) as mocked:
            response = client.patch(
                "/api/emails/email_010/review",
                json={"si": {"shipper": "ACME"}},
            )
        self.assertEqual(response.status_code, 200)
        call_kwargs = mocked.call_args.kwargs
        self.assertEqual(call_kwargs["si"], ShipmentFields(shipper="ACME"))
        self.assertIsNone(call_kwargs["bl"])

    def test_partial_correction_only_bl_supplied(self):
        with patch.object(orchestration, "apply_review_correction", return_value={"status": "OK"}) as mocked:
            response = client.patch(
                "/api/emails/email_010/review",
                json={"bl": {"shipper": "ACME"}},
            )
        self.assertEqual(response.status_code, 200)
        call_kwargs = mocked.call_args.kwargs
        self.assertIsNone(call_kwargs["si"])
        self.assertEqual(call_kwargs["bl"], ShipmentFields(shipper="ACME"))

    def test_reviewer_notes_and_reviewed_at_round_trip_in_response(self):
        fake_row = {
            "email_id": "email_010", "status": "OK",
            "reviewer_notes": "double-checked", "reviewed_at": "2026-09-21T12:00:00+00:00",
        }
        with patch.object(orchestration, "apply_review_correction", return_value=fake_row):
            response = client.patch(
                "/api/emails/email_010/review",
                json={"reviewer_notes": "double-checked"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reviewer_notes"], "double-checked")
        self.assertEqual(response.json()["reviewed_at"], "2026-09-21T12:00:00+00:00")

    def test_empty_body_is_valid_and_forwards_all_none(self):
        with patch.object(orchestration, "apply_review_correction", return_value={"status": "OK"}) as mocked:
            response = client.patch("/api/emails/email_010/review", json={})
        self.assertEqual(response.status_code, 200)
        call_kwargs = mocked.call_args.kwargs
        self.assertIsNone(call_kwargs["si"])
        self.assertIsNone(call_kwargs["bl"])
        self.assertIsNone(call_kwargs["reviewer_notes"])


class ErrorHandlingTests(unittest.TestCase):
    def test_database_exception_returns_generic_500_without_leaking_details(self):
        with patch.object(
            database, "list_emails",
            side_effect=RuntimeError("supabase connection refused: secret-token-xyz"),
        ):
            response = client.get("/api/emails")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"detail": "internal server error"})
        self.assertNotIn("secret-token-xyz", response.text)
        self.assertNotIn("RuntimeError", response.text)

    def test_signed_url_storage_failure_returns_generic_500(self):
        with patch.object(database, "create_signed_document_url", side_effect=RuntimeError("bucket unreachable")):
            response = client.get("/api/documents/signed-url?path=email_004/SI.txt")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"detail": "internal server error"})
        self.assertNotIn("bucket unreachable", response.text)


class CorsTests(unittest.TestCase):
    def test_localhost_frontend_origin_allowed(self):
        response = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
        self.assertEqual(response.headers.get("access-control-allow-origin"), "http://localhost:5173")

    def test_unknown_origin_not_reflected(self):
        response = client.get("/api/health", headers={"Origin": "http://evil.example.com"})
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_preflight_options_request_succeeds_for_localhost(self):
        # Verified without requiring any deployed FRONTEND_URL value — the
        # localhost:5173 dev origin is unconditionally present in main.py's
        # allowed_origins list.
        response = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"), "http://localhost:5173")


class ExportEmailsEndpointTests(unittest.TestCase):
    _FAKE_ROWS = [
        {
            "email_id": "email_004",
            "sender": "a@b.com",
            "subject": "SI request",
            "category": "BL_COMPARISON",
            "status": "MISMATCH",
            "review_reason": None,
            "has_defect": True,
            "defect_fields": ["shipper", "consignee"],
            "decided_by": "rule",
            "updated_at": "2026-09-21T00:00:00+00:00",
            "si": {"shipper": "ACME SI", "consignee": "C1"},
            "bl": {"shipper": "ACME BL", "consignee": "C1"},
        },
        {
            "email_id": "email_005",
            "sender": None,
            "subject": "not yet processed",
            "category": None,
            "status": None,
            "review_reason": None,
            "has_defect": None,
            "defect_fields": None,
            "decided_by": None,
            "updated_at": None,
            "si": None,
            "bl": None,
        },
    ]

    def test_default_json_export_returns_flat_rows_with_download_header(self):
        with patch.object(database, "list_emails", return_value=self._FAKE_ROWS) as mocked:
            response = client.get("/api/emails/export")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/json")
        self.assertTrue(response.headers["content-disposition"].startswith("attachment; filename=codeblack_results_"))
        self.assertTrue(response.headers["content-disposition"].endswith(".json"))
        mocked.assert_called_once_with(
            status=None, category=None, processing_status=None, batch_id=None, limit=main.EXPORT_MAX_ROWS
        )

        rows = response.json()
        self.assertEqual(len(rows), 2)
        processed, unprocessed = rows
        self.assertEqual(processed["email_id"], "email_004")
        self.assertEqual(processed["si_shipper"], "ACME SI")
        self.assertEqual(processed["bl_shipper"], "ACME BL")
        self.assertEqual(processed["si_consignee"], "C1")
        self.assertEqual(processed["defect_fields"], ["shipper", "consignee"])
        # An unprocessed email is included with empty/None result columns, not omitted.
        self.assertEqual(unprocessed["email_id"], "email_005")
        self.assertIsNone(unprocessed["category"])
        self.assertIsNone(unprocessed["si_shipper"])
        self.assertIsNone(unprocessed["bl_shipper"])
        self.assertEqual(unprocessed["defect_fields"], [])

    def test_csv_export_has_header_and_one_data_row(self):
        with patch.object(database, "list_emails", return_value=self._FAKE_ROWS[:1]):
            response = client.get("/api/emails/export?format=csv")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/csv"))
        self.assertTrue(response.headers["content-disposition"].endswith(".csv"))

        lines = response.text.strip("\r\n").split("\r\n")
        self.assertEqual(len(lines), 2)
        header, row = lines
        self.assertEqual(header.split(","), main.EXPORT_COLUMNS)
        cells = row.split(",")
        self.assertEqual(cells[0], "email_004")
        self.assertIn("shipper;consignee", row)  # defect_fields joined with ";"

    def test_filters_forwarded_to_list_emails(self):
        with patch.object(database, "list_emails", return_value=[]) as mocked:
            client.get("/api/emails/export?status=MISMATCH&category=BL_COMPARISON")
        mocked.assert_called_once_with(
            status="MISMATCH", category="BL_COMPARISON", processing_status=None, batch_id=None, limit=main.EXPORT_MAX_ROWS
        )

    def test_route_declared_before_single_email_route(self):
        # If /api/emails/export were declared after /api/emails/{email_id},
        # FastAPI would match "export" as an email_id and call
        # database.get_email("export") instead of database.list_emails().
        with patch.object(database, "get_email", side_effect=AssertionError("must not hit the {email_id} route")), \
             patch.object(database, "list_emails", return_value=[]) as mocked_list:
            response = client.get("/api/emails/export")
        self.assertEqual(response.status_code, 200)
        mocked_list.assert_called_once()


class UploadEmailEndpointTests(unittest.TestCase):
    def test_upload_with_txt_pair_creates_record_and_processes(self):
        fake_result = EmailResult(email_id="placeholder", category="SI_REQUEST", status="OK")
        with patch.object(database, "upload_document") as mocked_upload, \
             patch.object(database, "create_attachment_record") as mocked_attach, \
             patch.object(database, "upsert_email_source") as mocked_source, \
             patch.object(orchestration, "process_and_persist_email", return_value=fake_result) as mocked_process:
            response = client.post(
                "/api/emails/upload",
                data={"subject": "Test SI/BL", "body": "please verify", "sender": "x@y.com"},
                files=[
                    ("files", ("si.txt", b"SI content", "text/plain")),
                    ("files", ("bl.txt", b"BL content", "text/plain")),
                ],
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), fake_result.model_dump(mode="json"))

        self.assertEqual(mocked_upload.call_count, 2)
        self.assertEqual(mocked_attach.call_count, 2)
        mocked_source.assert_called_once()
        source_kwargs = mocked_source.call_args.kwargs
        self.assertEqual(source_kwargs["sender"], "x@y.com")
        self.assertEqual(source_kwargs["subject"], "Test SI/BL")
        self.assertEqual(source_kwargs["body"], "please verify")
        self.assertEqual(source_kwargs["source_attachments"], ["si.txt", "bl.txt"])

        email_id = mocked_source.call_args.args[0]
        self.assertTrue(email_id.startswith("upload_"))
        mocked_process.assert_called_once_with(email_id)

    def test_unrecognized_extension_is_accepted_and_passed_through(self):
        # Task 1 changes this deliberately: an unrecognized/unsupported file
        # type (image, .doc, unknown extension, etc.) is no longer an
        # upload-time error. It is stored and attached to the new email like
        # any other file; the pipeline marks that email NEEDS_REVIEW/
        # unreadable downstream — that is the expected outcome, not a 400.
        fake_result = EmailResult(email_id="placeholder", category="GENERAL", status="NEEDS_REVIEW")
        with patch.object(database, "upload_document") as mocked_upload, \
             patch.object(database, "create_attachment_record") as mocked_attach, \
             patch.object(database, "upsert_email_source") as mocked_source, \
             patch.object(orchestration, "process_and_persist_email", return_value=fake_result):
            response = client.post(
                "/api/emails/upload",
                data={"subject": "Test", "body": "body"},
                files=[("files", ("mystery.exe", b"x", "application/octet-stream"))],
            )
        self.assertEqual(response.status_code, 200)
        mocked_upload.assert_called_once()
        mocked_attach.assert_called_once()
        mocked_source.assert_called_once()
        self.assertEqual(mocked_source.call_args.kwargs["source_attachments"], ["mystery.exe"])

    def test_oversize_file_returns_413_and_persists_nothing(self):
        oversize = b"x" * (main.MAX_UPLOAD_FILE_BYTES + 1)
        with patch.object(database, "upload_document") as mocked_upload, \
             patch.object(database, "upsert_email_source") as mocked_source:
            response = client.post(
                "/api/emails/upload",
                data={"subject": "Test", "body": "body"},
                files=[("files", ("big.txt", oversize, "text/plain"))],
            )
        self.assertEqual(response.status_code, 413)
        mocked_upload.assert_not_called()
        mocked_source.assert_not_called()

    def test_too_many_files_returns_413(self):
        files = [("files", (f"f{i}.txt", b"x", "text/plain")) for i in range(main.MAX_UPLOAD_FILES + 1)]
        response = client.post(
            "/api/emails/upload",
            data={"subject": "Test", "body": "body"},
            files=files,
        )
        self.assertEqual(response.status_code, 413)

    def test_missing_required_fields_returns_422(self):
        response = client.post("/api/emails/upload", data={"subject": "Test"})
        self.assertEqual(response.status_code, 422)

    def test_processing_failure_keeps_record_and_returns_it(self):
        failed_row = {
            "email_id": "upload_abc123",
            "processing_status": "failed",
            "last_error": "RuntimeError: processing failed",
        }
        with patch.object(database, "upload_document"), \
             patch.object(database, "create_attachment_record"), \
             patch.object(database, "upsert_email_source"), \
             patch.object(orchestration, "process_and_persist_email", side_effect=RuntimeError("boom")), \
             patch.object(database, "get_email", return_value=failed_row) as mocked_get:
            response = client.post(
                "/api/emails/upload",
                data={"subject": "Test", "body": "body"},
                files=[("files", ("si.txt", b"content", "text/plain"))],
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), failed_row)
        mocked_get.assert_called_once()


class UploadForeignKeyOrderingTests(unittest.TestCase):
    """Regression coverage for the upload FK-ordering bug: the parent
    `emails` row must be persisted via database.upsert_email_source()
    before any database.create_attachment_record() call for that same
    email_id, since attachments.email_id has a foreign key onto
    emails.email_id (Postgres 23503 otherwise). Covers all three upload
    paths that store attachments: plain multipart files, .eml, and the
    organizer-bundle/batch path."""

    def test_plain_attachment_upload_creates_parent_row_before_attachment_records(self):
        call_order: list[str] = []
        fake_result = EmailResult(email_id="placeholder", category="SI_REQUEST", status="OK")

        def record_source(*args, **kwargs):
            call_order.append("upsert_email_source")
            return {"email_id": args[0] if args else kwargs.get("email_id")}

        def record_attachment(*args, **kwargs):
            call_order.append("create_attachment_record")

        with patch.object(database, "upload_document"), \
             patch.object(database, "create_attachment_record", side_effect=record_attachment), \
             patch.object(database, "upsert_email_source", side_effect=record_source), \
             patch.object(orchestration, "process_and_persist_email", return_value=fake_result):
            response = client.post(
                "/api/emails/upload",
                data={"subject": "Test SI/BL", "body": "please verify"},
                files=[
                    ("files", ("si.txt", b"SI content", "text/plain")),
                    ("files", ("bl.txt", b"BL content", "text/plain")),
                ],
            )

        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(call_order), 3)
        self.assertEqual(call_order[0], "upsert_email_source")
        self.assertNotIn("create_attachment_record", call_order[: call_order.index("upsert_email_source") + 1])

    def test_eml_upload_creates_parent_row_before_attachment_records(self):
        eml_bytes = (
            b"From: sender@example.com\r\n"
            b"Subject: Please verify BL\r\n"
            b"MIME-Version: 1.0\r\n"
            b'Content-Type: multipart/mixed; boundary="BOUNDARY"\r\n'
            b"\r\n"
            b"--BOUNDARY\r\n"
            b"Content-Type: text/plain\r\n"
            b"\r\n"
            b"Please compare the attached SI and BL.\r\n"
            b"--BOUNDARY\r\n"
            b"Content-Type: text/plain\r\n"
            b'Content-Disposition: attachment; filename="si.txt"\r\n'
            b"\r\n"
            b"SI content\r\n"
            b"--BOUNDARY--\r\n"
        )
        call_order: list[str] = []
        fake_result = EmailResult(email_id="placeholder", category="BL_COMPARISON", status="OK")

        with patch.object(database, "upload_document"), \
             patch.object(
                 database, "create_attachment_record",
                 side_effect=lambda *a, **k: call_order.append("create_attachment_record"),
             ), \
             patch.object(
                 database, "upsert_email_source",
                 side_effect=lambda *a, **k: call_order.append("upsert_email_source") or {"email_id": a[0]},
             ), \
             patch.object(orchestration, "process_and_persist_email", return_value=fake_result):
            response = client.post(
                "/api/emails/upload",
                files=[("files", ("incoming.eml", eml_bytes, "message/rfc822"))],
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(call_order, ["upsert_email_source", "create_attachment_record"])

    def test_bundle_upload_creates_parent_row_before_attachment_records_per_email(self):
        zip_bytes = _make_bundle_zip(_BUNDLE_RECORDS, _BUNDLE_ATTACHMENTS)
        fake_result = EmailResult(email_id="placeholder", category="BL_COMPARISON", status="OK")

        # Track ordering PER composite email_id, since the batch runs several
        # emails concurrently across worker threads -- the FK constraint is
        # per email_id, so what matters is that each email's own
        # upsert_email_source() call precedes its own create_attachment_record()
        # call(s), not a single global order across the whole batch.
        events: dict[str, list[str]] = {}
        lock = threading.Lock()

        def record_source(email_id, *args, **kwargs):
            with lock:
                events.setdefault(email_id, []).append("upsert_email_source")
            return {"email_id": email_id}

        def record_attachment(email_id, *args, **kwargs):
            with lock:
                events.setdefault(email_id, []).append("create_attachment_record")

        with patch.object(database, "create_batch"), \
             patch.object(database, "update_batch_progress"), \
             patch.object(database, "upload_document"), \
             patch.object(database, "create_attachment_record", side_effect=record_attachment), \
             patch.object(database, "upsert_email_source", side_effect=record_source), \
             patch.object(orchestration, "process_and_persist_email", return_value=fake_result):
            response = client.post(
                "/api/emails/upload",
                files=[("files", ("bundle.zip", zip_bytes, "application/zip"))],
            )

        self.assertEqual(response.status_code, 200)
        # email_001 and email_002 each have exactly one attachment.
        emails_with_attachments = [eid for eid in events if eid.endswith("email_001") or eid.endswith("email_002")]
        self.assertEqual(len(emails_with_attachments), 2)
        for email_id in emails_with_attachments:
            self.assertEqual(events[email_id], ["upsert_email_source", "create_attachment_record"])


def _make_zip(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


class ZipUploadTests(unittest.TestCase):
    def test_zip_with_txt_pair_creates_one_email_with_two_attachments(self):
        zip_bytes = _make_zip({"si.txt": b"SI content", "bl.txt": b"BL content"})
        fake_result = EmailResult(email_id="placeholder", category="BL_COMPARISON", status="OK")
        with patch.object(database, "upload_document") as mocked_upload, \
             patch.object(database, "create_attachment_record") as mocked_attach, \
             patch.object(database, "upsert_email_source") as mocked_source, \
             patch.object(orchestration, "process_and_persist_email", return_value=fake_result):
            response = client.post(
                "/api/emails/upload",
                data={"subject": "Zip upload", "body": "please verify"},
                files=[("files", ("docs.zip", zip_bytes, "application/zip"))],
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mocked_upload.call_count, 2)
        self.assertEqual(mocked_attach.call_count, 2)
        mocked_source.assert_called_once()
        self.assertEqual(
            sorted(mocked_source.call_args.kwargs["source_attachments"]),
            ["bl.txt", "si.txt"],
        )

    def test_zip_slip_path_traversal_is_neutralized(self):
        zip_bytes = _make_zip({"../../evil.txt": b"payload", "../escape.txt": b"payload2"})
        fake_result = EmailResult(email_id="placeholder", category="GENERAL", status="OK")
        with patch.object(database, "upload_document") as mocked_upload, \
             patch.object(database, "create_attachment_record"), \
             patch.object(database, "upsert_email_source") as mocked_source, \
             patch.object(orchestration, "process_and_persist_email", return_value=fake_result):
            response = client.post(
                "/api/emails/upload",
                data={"subject": "Zip slip", "body": "body"},
                files=[("files", ("evil.zip", zip_bytes, "application/zip"))],
            )
        self.assertEqual(response.status_code, 200)
        for call in mocked_upload.call_args_list:
            storage_path = call.args[0]
            self.assertNotIn("..", storage_path)
        for name in mocked_source.call_args.kwargs["source_attachments"]:
            self.assertNotIn("..", name)
            self.assertNotIn("/", name)

    def test_zip_exceeding_file_count_limit_is_rejected(self):
        entries = {f"f{i}.txt": b"x" for i in range(main.ZIP_MAX_FILES + 1)}
        zip_bytes = _make_zip(entries)
        with patch.object(database, "upload_document") as mocked_upload:
            response = client.post(
                "/api/emails/upload",
                data={"subject": "Too many", "body": "body"},
                files=[("files", ("many.zip", zip_bytes, "application/zip"))],
            )
        self.assertEqual(response.status_code, 413)
        mocked_upload.assert_not_called()

    def test_zip_exceeding_uncompressed_size_limit_is_rejected(self):
        zip_bytes = _make_zip({"big.txt": b"x" * 1000})
        with patch.object(main, "ZIP_MAX_UNCOMPRESSED_BYTES", 100), \
             patch.object(database, "upload_document") as mocked_upload:
            response = client.post(
                "/api/emails/upload",
                data={"subject": "Too big", "body": "body"},
                files=[("files", ("big.zip", zip_bytes, "application/zip"))],
            )
        self.assertEqual(response.status_code, 413)
        mocked_upload.assert_not_called()

    def test_zip_inside_zip_is_not_extracted_further(self):
        inner_zip = _make_zip({"deep.txt": b"deep content"})
        outer_zip = _make_zip({"nested.zip": inner_zip, "top.txt": b"top content"})
        fake_result = EmailResult(email_id="placeholder", category="GENERAL", status="OK")
        with patch.object(database, "upload_document") as mocked_upload, \
             patch.object(database, "create_attachment_record"), \
             patch.object(database, "upsert_email_source") as mocked_source, \
             patch.object(orchestration, "process_and_persist_email", return_value=fake_result):
            response = client.post(
                "/api/emails/upload",
                data={"subject": "Nested", "body": "body"},
                files=[("files", ("outer.zip", outer_zip, "application/zip"))],
            )
        self.assertEqual(response.status_code, 200)
        # nested.zip itself is stored as a passthrough attachment, not expanded.
        self.assertEqual(
            sorted(mocked_source.call_args.kwargs["source_attachments"]),
            ["nested.zip", "top.txt"],
        )
        self.assertEqual(mocked_upload.call_count, 2)


class EmlUploadTests(unittest.TestCase):
    def test_eml_with_two_attachments_parses_correctly(self):
        eml_bytes = (
            b"From: sender@example.com\r\n"
            b"Subject: Please verify BL\r\n"
            b"MIME-Version: 1.0\r\n"
            b'Content-Type: multipart/mixed; boundary="BOUNDARY"\r\n'
            b"\r\n"
            b"--BOUNDARY\r\n"
            b"Content-Type: text/plain\r\n"
            b"\r\n"
            b"Please compare the attached SI and BL.\r\n"
            b"--BOUNDARY\r\n"
            b"Content-Type: text/plain\r\n"
            b'Content-Disposition: attachment; filename="si.txt"\r\n'
            b"\r\n"
            b"SI content\r\n"
            b"--BOUNDARY\r\n"
            b"Content-Type: text/plain\r\n"
            b'Content-Disposition: attachment; filename="bl.txt"\r\n'
            b"\r\n"
            b"BL content\r\n"
            b"--BOUNDARY--\r\n"
        )
        fake_result = EmailResult(email_id="placeholder", category="BL_COMPARISON", status="OK")
        with patch.object(database, "upload_document") as mocked_upload, \
             patch.object(database, "create_attachment_record") as mocked_attach, \
             patch.object(database, "upsert_email_source") as mocked_source, \
             patch.object(orchestration, "process_and_persist_email", return_value=fake_result):
            response = client.post(
                "/api/emails/upload",
                files=[("files", ("incoming.eml", eml_bytes, "message/rfc822"))],
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mocked_upload.call_count, 2)
        self.assertEqual(mocked_attach.call_count, 2)
        source_kwargs = mocked_source.call_args.kwargs
        self.assertEqual(source_kwargs["sender"], "sender@example.com")
        self.assertEqual(source_kwargs["subject"], "Please verify BL")
        self.assertIn("compare", source_kwargs["body"])
        self.assertEqual(sorted(source_kwargs["source_attachments"]), ["bl.txt", "si.txt"])

    def test_eml_upload_does_not_require_subject_or_body_form_fields(self):
        eml_bytes = b"From: a@b.com\r\nSubject: Hi\r\n\r\nBody text\r\n"
        fake_result = EmailResult(email_id="placeholder", category="GENERAL", status="OK")
        with patch.object(database, "upsert_email_source") as mocked_source, \
             patch.object(orchestration, "process_and_persist_email", return_value=fake_result):
            response = client.post(
                "/api/emails/upload",
                files=[("files", ("no_form_fields.eml", eml_bytes, "message/rfc822"))],
            )
        self.assertEqual(response.status_code, 200)
        mocked_source.assert_called_once()


class OrganizerJsonUploadTests(unittest.TestCase):
    def test_organizer_format_json_import(self):
        record = {
            "email_id": "email_004",
            "from": "shipper@example.com",
            "subject": "SI for shipment 004",
            "body": "Please find SI attached.",
            "attachments": ["attachments/email_004_SI.txt"],
        }
        payload = json.dumps(record).encode("utf-8")
        fake_result = EmailResult(email_id="placeholder", category="SI_REQUEST", status="OK")
        with patch.object(database, "upsert_email_source") as mocked_source, \
             patch.object(orchestration, "process_and_persist_email", return_value=fake_result):
            response = client.post(
                "/api/emails/upload",
                files=[("files", ("email_004.json", payload, "application/json"))],
            )
        self.assertEqual(response.status_code, 200)
        source_kwargs = mocked_source.call_args.kwargs
        self.assertEqual(source_kwargs["sender"], "shipper@example.com")
        self.assertEqual(source_kwargs["subject"], "SI for shipment 004")
        self.assertEqual(source_kwargs["body"], "Please find SI attached.")
        self.assertEqual(source_kwargs["source_attachments"], ["attachments/email_004_SI.txt"])


class MultiFileUploadTests(unittest.TestCase):
    def test_six_or_more_files_in_one_request_succeeds(self):
        fake_result = EmailResult(email_id="placeholder", category="GENERAL", status="OK")
        files = [("files", (f"f{i}.txt", f"content {i}".encode(), "text/plain")) for i in range(6)]
        with patch.object(database, "upload_document") as mocked_upload, \
             patch.object(database, "create_attachment_record"), \
             patch.object(database, "upsert_email_source") as mocked_source, \
             patch.object(orchestration, "process_and_persist_email", return_value=fake_result):
            response = client.post(
                "/api/emails/upload",
                data={"subject": "Six files", "body": "body"},
                files=files,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mocked_upload.call_count, 6)
        self.assertEqual(len(mocked_source.call_args.kwargs["source_attachments"]), 6)


def _make_bundle_zip(records: list, attachments: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for record in records:
            zf.writestr(f"inbox/{record['email_id']}.json", json.dumps(record))
        for path, data in attachments.items():
            zf.writestr(path, data)
    return buf.getvalue()


_BUNDLE_RECORDS = [
    {
        "email_id": "email_001",
        "from": "a@example.com",
        "subject": "SI 1",
        "body": "body 1",
        "attachments": ["attachments/email_001_SI.txt"],
    },
    {
        "email_id": "email_002",
        "from": "b@example.com",
        "subject": "SI 2",
        "body": "body 2",
        "attachments": ["attachments/email_002_SI.txt"],
    },
    {
        "email_id": "email_003",
        "from": "c@example.com",
        "subject": "SI 3",
        "body": "body 3",
        "attachments": [],
    },
]

_BUNDLE_ATTACHMENTS = {
    "attachments/email_001_SI.txt": b"SI one",
    "attachments/email_002_SI.txt": b"SI two",
}


class BundleUploadTests(unittest.TestCase):
    def test_bundle_shaped_zip_creates_batch_and_processes_all_emails(self):
        zip_bytes = _make_bundle_zip(_BUNDLE_RECORDS, _BUNDLE_ATTACHMENTS)
        fake_result = EmailResult(email_id="placeholder", category="BL_COMPARISON", status="OK")
        with patch.object(database, "create_batch") as mocked_create_batch, \
             patch.object(database, "update_batch_progress") as mocked_progress, \
             patch.object(database, "upload_document") as mocked_upload, \
             patch.object(database, "create_attachment_record"), \
             patch.object(database, "upsert_email_source") as mocked_source, \
             patch.object(orchestration, "process_and_persist_email", return_value=fake_result) as mocked_process:
            response = client.post(
                "/api/emails/upload",
                files=[("files", ("bundle.zip", zip_bytes, "application/zip"))],
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 3)
        self.assertEqual(body["status"], "processing")
        self.assertTrue(body["batch_id"].startswith("batch_"))

        mocked_create_batch.assert_called_once()
        self.assertEqual(mocked_create_batch.call_args.kwargs["total"], 3)

        # All 3 emails were processed (background task ran synchronously
        # under TestClient), each keyed by a batch-namespaced composite id
        # while carrying its original_email_id through upsert_email_source.
        self.assertEqual(mocked_process.call_count, 3)
        original_ids = {call.kwargs.get("original_email_id") for call in mocked_source.call_args_list}
        self.assertEqual(original_ids, {"email_001", "email_002", "email_003"})
        for call in mocked_process.call_args_list:
            composite_id = call.args[0]
            self.assertTrue(composite_id.startswith(body["batch_id"] + "__"))

        # 2 attachments uploaded (email_003 has none).
        self.assertEqual(mocked_upload.call_count, 2)

        # Progress was updated incrementally, ending at done=3, failed=0,
        # status=completed.
        final_call = mocked_progress.call_args_list[-1]
        self.assertEqual(final_call.kwargs.get("status"), "completed")

    def test_batch_progress_counts_update_correctly_including_failures(self):
        zip_bytes = _make_bundle_zip(_BUNDLE_RECORDS, _BUNDLE_ATTACHMENTS)

        def flaky_process(email_id):
            if email_id.endswith("email_002"):
                raise RuntimeError("simulated failure")
            return EmailResult(email_id=email_id, category="GENERAL", status="OK")

        with patch.object(database, "create_batch"), \
             patch.object(database, "update_batch_progress") as mocked_progress, \
             patch.object(database, "upload_document"), \
             patch.object(database, "create_attachment_record"), \
             patch.object(database, "upsert_email_source"), \
             patch.object(orchestration, "process_and_persist_email", side_effect=flaky_process):
            response = client.post(
                "/api/emails/upload",
                files=[("files", ("bundle.zip", zip_bytes, "application/zip"))],
            )
        self.assertEqual(response.status_code, 200)

        done_failed_pairs = [
            (call.kwargs.get("done"), call.kwargs.get("failed"))
            for call in mocked_progress.call_args_list
            if call.kwargs.get("done") is not None or call.kwargs.get("failed") is not None
        ]
        final_done, final_failed = done_failed_pairs[-1]
        self.assertEqual(final_done, 2)
        self.assertEqual(final_failed, 1)

    def test_two_batches_with_same_original_email_ids_do_not_collide(self):
        zip_bytes_a = _make_bundle_zip(_BUNDLE_RECORDS, _BUNDLE_ATTACHMENTS)
        zip_bytes_b = _make_bundle_zip(_BUNDLE_RECORDS, _BUNDLE_ATTACHMENTS)
        fake_result = EmailResult(email_id="placeholder", category="GENERAL", status="OK")

        seen_composite_ids = []

        def capture_process(email_id):
            seen_composite_ids.append(email_id)
            return fake_result

        with patch.object(database, "create_batch"), \
             patch.object(database, "update_batch_progress"), \
             patch.object(database, "upload_document"), \
             patch.object(database, "create_attachment_record"), \
             patch.object(database, "upsert_email_source"), \
             patch.object(orchestration, "process_and_persist_email", side_effect=capture_process):
            response_a = client.post(
                "/api/emails/upload", files=[("files", ("bundle_a.zip", zip_bytes_a, "application/zip"))]
            )
            response_b = client.post(
                "/api/emails/upload", files=[("files", ("bundle_b.zip", zip_bytes_b, "application/zip"))]
            )

        batch_id_a = response_a.json()["batch_id"]
        batch_id_b = response_b.json()["batch_id"]
        self.assertNotEqual(batch_id_a, batch_id_b)

        ids_from_a = {cid for cid in seen_composite_ids if cid.startswith(batch_id_a + "__")}
        ids_from_b = {cid for cid in seen_composite_ids if cid.startswith(batch_id_b + "__")}
        # No overlap between the two batches' actual persisted email_ids,
        # even though both batches share the same underlying original
        # organizer email_ids (email_001/002/003).
        self.assertEqual(ids_from_a & ids_from_b, set())
        self.assertEqual(len(ids_from_a), 3)
        self.assertEqual(len(ids_from_b), 3)


class GetBatchEndpointTests(unittest.TestCase):
    def test_existing_batch_returns_200(self):
        fake_batch = {
            "batch_id": "batch_abc123",
            "total": 3,
            "done": 2,
            "failed": 1,
            "status": "completed",
            "created_at": "2026-09-22T00:00:00+00:00",
            "finished_at": "2026-09-22T00:01:00+00:00",
        }
        with patch.object(database, "get_batch", return_value=fake_batch) as mocked:
            response = client.get("/api/batches/batch_abc123")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), fake_batch)
        mocked.assert_called_once_with("batch_abc123")

    def test_missing_batch_returns_404(self):
        with patch.object(database, "get_batch", return_value=None):
            response = client.get("/api/batches/batch_missing")
        self.assertEqual(response.status_code, 404)
        self.assertIn("batch_missing", response.json()["detail"])


class ExportSubmissionFormatTests(unittest.TestCase):
    def test_submission_format_returns_organizer_shape_keyed_by_original_email_id(self):
        fake_rows = [
            {
                "email_id": "batch_xyz__email_001",
                "original_email_id": "email_001",
                "category": "BL_COMPARISON",
                "status": "MISMATCH",
                "review_reason": None,
                "has_defect": True,
                "defect_fields": ["shipper"],
            },
            {
                "email_id": "email_010",
                "original_email_id": None,
                "category": "SI_REQUEST",
                "status": "OK",
                "review_reason": None,
                "has_defect": False,
                "defect_fields": [],
            },
        ]
        with patch.object(database, "list_emails", return_value=fake_rows) as mocked:
            response = client.get("/api/emails/export?format=submission&batch_id=batch_xyz")
        self.assertEqual(response.status_code, 200)
        mocked.assert_called_once_with(
            status=None, category=None, processing_status=None, batch_id="batch_xyz", limit=main.EXPORT_MAX_ROWS
        )
        body = response.json()
        self.assertEqual(
            body,
            {
                "email_001": {
                    "category": "BL_COMPARISON",
                    "status": "MISMATCH",
                    "review_reason": None,
                    "defect_fields": ["shipper"],
                    "has_defect": True,
                },
                "email_010": {
                    "category": "SI_REQUEST",
                    "status": "OK",
                    "review_reason": None,
                    "defect_fields": [],
                    "has_defect": False,
                },
            },
        )


if __name__ == "__main__":
    unittest.main()
