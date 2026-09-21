"""
Regression tests for evaluation/run_all.py's attachment-loading integration
(PROJECT_RULES.md section 19: never touches ground_truth.json; these tests
don't either).

Standard-library unittest only. process_email is always a plain fake/stub
function here — the real backend pipeline (pipeline.run.process_email) is
never imported or invoked, matching run_all.py's own lazy-import design
for a real run vs. --stub.

Run from inside evaluation/:
    python -m unittest -v test_run_all
"""
import tempfile
import unittest
from pathlib import Path

import run_all


class LoadAttachmentBytesTests(unittest.TestCase):
    def test_original_organizer_path_used_as_dict_key(self):
        with tempfile.TemporaryDirectory() as data_dir:
            (Path(data_dir) / "attachments").mkdir()
            (Path(data_dir) / "attachments" / "email_512_SI.pdf").write_bytes(b"SI BYTES")
            email = {"email_id": "email_512", "attachments": ["attachments/email_512_SI.pdf"]}

            attachment_bytes, problems = run_all._load_attachment_bytes(email, data_dir)

            self.assertEqual(problems, [])
            self.assertIn("attachments/email_512_SI.pdf", attachment_bytes)
            self.assertEqual(attachment_bytes["attachments/email_512_SI.pdf"], b"SI BYTES")

    def test_two_attachments_loaded_correctly(self):
        with tempfile.TemporaryDirectory() as data_dir:
            att_dir = Path(data_dir) / "attachments"
            att_dir.mkdir()
            (att_dir / "email_512_SI.pdf").write_bytes(b"SI BYTES")
            (att_dir / "email_512_BL.pdf").write_bytes(b"BL BYTES")
            email = {
                "email_id": "email_512",
                "attachments": ["attachments/email_512_SI.pdf", "attachments/email_512_BL.pdf"],
            }

            attachment_bytes, problems = run_all._load_attachment_bytes(email, data_dir)

            self.assertEqual(problems, [])
            self.assertEqual(len(attachment_bytes), 2)
            self.assertEqual(attachment_bytes["attachments/email_512_SI.pdf"], b"SI BYTES")
            self.assertEqual(attachment_bytes["attachments/email_512_BL.pdf"], b"BL BYTES")

    def test_missing_attachment_does_not_crash_and_is_recorded(self):
        with tempfile.TemporaryDirectory() as data_dir:
            email = {"email_id": "email_512", "attachments": ["attachments/does_not_exist.pdf"]}

            attachment_bytes, problems = run_all._load_attachment_bytes(email, data_dir)

            self.assertEqual(attachment_bytes, {})
            self.assertEqual(len(problems), 1)
            self.assertIn("attachments/does_not_exist.pdf", problems[0])

    def test_never_guesses_alternate_filenames(self):
        with tempfile.TemporaryDirectory() as data_dir:
            att_dir = Path(data_dir) / "attachments"
            att_dir.mkdir()
            # A basename-similar file exists, but not the exact referenced path
            # -- must not be picked up as a substitute.
            (att_dir / "email_512_SI (1).pdf").write_bytes(b"SI BYTES")
            email = {"email_id": "email_512", "attachments": ["attachments/email_512_SI.pdf"]}

            attachment_bytes, problems = run_all._load_attachment_bytes(email, data_dir)

            self.assertEqual(attachment_bytes, {})
            self.assertEqual(len(problems), 1)

    def test_no_attachments_returns_empty(self):
        attachment_bytes, problems = run_all._load_attachment_bytes(
            {"email_id": "email_001", "attachments": []}, "unused"
        )
        self.assertEqual(attachment_bytes, {})
        self.assertEqual(problems, [])


class ProcessWithRetriesTests(unittest.TestCase):
    def test_attachment_bytes_passed_to_process_email(self):
        with tempfile.TemporaryDirectory() as data_dir:
            (Path(data_dir) / "attachments").mkdir()
            (Path(data_dir) / "attachments" / "email_512_SI.pdf").write_bytes(b"SI BYTES")
            email = {"email_id": "email_512", "attachments": ["attachments/email_512_SI.pdf"]}

            captured = {}

            def fake_process_email(email_arg, attachment_bytes=None):
                captured["attachment_bytes"] = attachment_bytes
                return run_all.EmailResult(email_id=email_arg["email_id"], category="GENERAL")

            record = run_all._process_with_retries(fake_process_email, email, retries=0, data_dir=data_dir)

            self.assertTrue(record["ok"])
            self.assertIn("attachment_bytes", captured)
            self.assertEqual(captured["attachment_bytes"], {"attachments/email_512_SI.pdf": b"SI BYTES"})

    def test_two_attachments_both_reach_process_email(self):
        with tempfile.TemporaryDirectory() as data_dir:
            att_dir = Path(data_dir) / "attachments"
            att_dir.mkdir()
            (att_dir / "email_513_SI.pdf").write_bytes(b"SI BYTES")
            (att_dir / "email_513_BL.pdf").write_bytes(b"BL BYTES")
            email = {
                "email_id": "email_513",
                "attachments": ["attachments/email_513_SI.pdf", "attachments/email_513_BL.pdf"],
            }

            captured = {}

            def fake_process_email(email_arg, attachment_bytes=None):
                captured["attachment_bytes"] = attachment_bytes
                return run_all.EmailResult(email_id=email_arg["email_id"], category="BL_COMPARISON")

            run_all._process_with_retries(fake_process_email, email, retries=0, data_dir=data_dir)

            self.assertEqual(
                captured["attachment_bytes"],
                {
                    "attachments/email_513_SI.pdf": b"SI BYTES",
                    "attachments/email_513_BL.pdf": b"BL BYTES",
                },
            )

    def test_missing_attachment_does_not_crash_runner(self):
        with tempfile.TemporaryDirectory() as data_dir:
            email = {"email_id": "email_512", "attachments": ["attachments/does_not_exist.pdf"]}

            def fake_process_email(email_arg, attachment_bytes=None):
                return run_all.EmailResult(
                    email_id=email_arg["email_id"], category="BL_COMPARISON",
                    status="NEEDS_REVIEW", review_reason="missing_attachment",
                )

            record = run_all._process_with_retries(fake_process_email, email, retries=0, data_dir=data_dir)

            self.assertTrue(record["ok"])
            self.assertEqual(record["result"]["email_id"], "email_512")
            self.assertIn("attachment_problems", record["result"])
            self.assertIn("attachments/does_not_exist.pdf", record["result"]["attachment_problems"][0])

    def test_stub_mode_still_works(self):
        with tempfile.TemporaryDirectory() as data_dir:
            email = {"email_id": "email_004", "attachments": []}
            stub = run_all._make_stub()

            record = run_all._process_with_retries(stub, email, retries=0, data_dir=data_dir)

            self.assertTrue(record["ok"])
            self.assertEqual(record["result"]["email_id"], "email_004")
            self.assertEqual(record["result"]["category"], "GENERAL")

    def test_stub_mode_receives_attachment_bytes_without_error(self):
        with tempfile.TemporaryDirectory() as data_dir:
            (Path(data_dir) / "attachments").mkdir()
            (Path(data_dir) / "attachments" / "email_004_SI.pdf").write_bytes(b"X")
            email = {"email_id": "email_004", "attachments": ["attachments/email_004_SI.pdf"]}

            captured = {}
            stub = run_all._make_stub()

            def spying_stub(email_arg, attachment_bytes=None):
                captured["attachment_bytes"] = attachment_bytes
                return stub(email_arg, attachment_bytes=attachment_bytes)

            record = run_all._process_with_retries(spying_stub, email, retries=0, data_dir=data_dir)

            self.assertTrue(record["ok"])
            self.assertEqual(captured["attachment_bytes"], {"attachments/email_004_SI.pdf": b"X"})


if __name__ == "__main__":
    unittest.main()
