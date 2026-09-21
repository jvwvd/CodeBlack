"""
Regression tests for backend/main.py.

Standard-library unittest + unittest.mock only. Every database.py call is
mocked at the module attribute main.py actually resolves at call time
(`database.<function>`, since main.py does `import database`) — no real
Supabase client, network call, or credential is ever touched.

Run from inside backend/:
    python -m unittest -v test_main
"""
import unittest
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


if __name__ == "__main__":
    unittest.main()
