import unittest
from unittest.mock import patch

import pymupdf
from docx import Document
from openpyxl import Workbook
from io import BytesIO

from pipeline.classify import classify_email
from pipeline.documents import (
    identify_doc_type,
    parse_attachment_bytes,
)
from pipeline.run import _finalize, process_email
from models import EmailResult


SI_TEXT = """
SHIPPING INSTRUCTION

Shipper: TEST EXPORTER LTD
Consignee: TEST IMPORTER SDN BHD
Notify Party: TEST IMPORTER SDN BHD
Port of Loading: SINGAPORE
Port of Discharge: KARACHI, PAKISTAN (PKKHI)
Container Count: 3
Gross Weight: 22000 KG
"""

BL_TEXT = """
DRAFT BILL OF LADING

Shipper: TEST EXPORTER LTD
Consignee: TEST IMPORTER SDN BHD
Notify Party: TEST IMPORTER SDN BHD
Port of Loading: SINGAPORE
Port of Discharge: KARACHI, PAKISTAN (PKKHI)
Container Count: 3
Gross Weight: 22000 KG
"""


def make_pdf(text: str) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def make_empty_pdf() -> bytes:
    doc = pymupdf.open()
    doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


def make_docx(text: str) -> bytes:
    document = Document()

    for line in text.strip().splitlines():
        document.add_paragraph(line)

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def make_xlsx(text: str) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active

    for row_index, line in enumerate(text.strip().splitlines(), start=1):
        worksheet.cell(row=row_index, column=1, value=line)

    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()

    return buffer.getvalue()


class PipelineRegressionTests(unittest.TestCase):

    def test_txt_si_bl_end_to_end(self):
        email = {
            "email_id": "email_test_txt",
            "from": "ops@example.com",
            "subject": "Please check draft BL against shipping instruction",
            "body": "Please verify the shipping instruction against the draft bill of lading.",
            "attachments": [
                "attachments/si.txt",
                "attachments/bl.txt",
            ],
        }

        attachment_bytes = {
            "attachments/si.txt": SI_TEXT.encode(),
            "attachments/bl.txt": BL_TEXT.encode(),
        }

        result = process_email(
            email,
            attachment_bytes=attachment_bytes,
        )

        self.assertEqual(result.category, "BL_COMPARISON")
        self.assertEqual(result.status, "OK")
        self.assertFalse(result.has_defect)
        self.assertEqual(result.defect_fields, [])

    def test_pdf_text_extraction(self):
        data = make_pdf(BL_TEXT)

        text = parse_attachment_bytes(
            data,
            "draft_bl.pdf",
        )

        self.assertIsNotNone(text)
        self.assertIn("DRAFT BILL OF LADING", text)
        self.assertEqual(identify_doc_type(text), "BL")

    def test_docx_extraction(self):
        data = make_docx(BL_TEXT)

        text = parse_attachment_bytes(
            data,
            "draft_bl.docx",
        )

        self.assertIsNotNone(text)
        self.assertIn("DRAFT BILL OF LADING", text)
        self.assertEqual(identify_doc_type(text), "BL")

    def test_xlsx_extraction(self):
        data = make_xlsx(SI_TEXT)

        text = parse_attachment_bytes(
            data,
            "shipping_instruction.xlsx",
        )

        self.assertIsNotNone(text)
        self.assertIn("SHIPPING INSTRUCTION", text)
        self.assertEqual(identify_doc_type(text), "SI")

    @patch(
        "pipeline.documents.read_scanned_pdf_with_vision",
        return_value=SI_TEXT,
    )
    def test_scanned_pdf_uses_vision_fallback(self, mock_vision):
        data = make_empty_pdf()

        text = parse_attachment_bytes(
            data,
            "scanned_si.pdf",
        )

        mock_vision.assert_called_once()

        self.assertIsNotNone(text)
        self.assertIn("SHIPPING INSTRUCTION", text)
        self.assertEqual(identify_doc_type(text), "SI")

    def test_missing_attachment_routes_to_review(self):
        email = {
            "email_id": "email_test_missing",
            "from": "ops@example.com",
            "subject": "Please check draft BL against shipping instruction",
            "body": "Please verify the shipping instruction against the draft bill of lading.",
            "attachments": [
                "attachments/si.txt",
            ],
        }

        attachment_bytes = {
            "attachments/si.txt": SI_TEXT.encode(),
        }

        category, _ = classify_email(email)

        self.assertEqual(
            category,
            "BL_COMPARISON",
        )

        result = process_email(
            email,
            attachment_bytes=attachment_bytes,
        )

        self.assertEqual(
            result.status,
            "NEEDS_REVIEW",
        )

        self.assertEqual(
            result.review_reason,
            "missing_attachment",
        )

    @patch(
        "pipeline.classify.classify_with_llm",
        return_value=None,
    )
    def test_ai_unavailable_has_safe_classification_fallback(
        self,
        mock_llm,
    ):
        email = {
            "email_id": "email_test_ai_failure",
            "from": "ops@example.com",
            "subject": "Operational update",
            "body": "Please review when available.",
            "attachments": [],
        }

        category, decided_by = classify_email(email)

        mock_llm.assert_called_once()

        self.assertEqual(category, "GENERAL")
        self.assertEqual(decided_by, "rule")

    @patch(
        "pipeline.documents.read_scanned_pdf_with_vision",
        return_value=None,
    )
    def test_failed_vision_returns_unreadable(
        self,
        mock_vision,
    ):
        data = make_empty_pdf()

        text = parse_attachment_bytes(
            data,
            "unreadable_scan.pdf",
        )

        mock_vision.assert_called_once()
        self.assertIsNone(text)


SI_TEXT_MISSING_WEIGHT = """
SHIPPING INSTRUCTION

Shipper: TEST EXPORTER LTD
Consignee: TEST IMPORTER SDN BHD
Notify Party: TEST IMPORTER SDN BHD
Port of Loading: SINGAPORE
Port of Discharge: KARACHI, PAKISTAN (PKKHI)
Container Count: 3
"""

BL_TEXT_DIFFERENT_CONSIGNEE = """
DRAFT BILL OF LADING

Shipper: TEST EXPORTER LTD
Consignee: DIFFERENT IMPORTER SDN BHD
Notify Party: TEST IMPORTER SDN BHD
Port of Loading: SINGAPORE
Port of Discharge: KARACHI, PAKISTAN (PKKHI)
Container Count: 3
Gross Weight: 22000 KG
"""


class DefectReviewInvariantTests(unittest.TestCase):
    """Organizer README invariant: has_defect/defect_fields are reported
    for MISMATCH, review_reason is reported for NEEDS_REVIEW -- never
    both. Regression coverage for email_040/email_516/email_518, which
    previously came back NEEDS_REVIEW + review_reason=missing_value while
    still carrying has_defect=true and a non-empty defect_fields list."""

    @patch("pipeline.extract.extract_with_llm", return_value=None)
    def test_missing_si_weight_with_apparent_differences_is_clean_needs_review(self, mock_llm):
        # SI is missing gross weight (required field) AND consignee genuinely
        # differs from BL -- the exact shape that used to leak has_defect/
        # defect_fields alongside NEEDS_REVIEW.
        email = {
            "email_id": "email_test_missing_weight",
            "from": "ops@example.com",
            "subject": "Please check draft BL against shipping instruction",
            "body": "Please verify the shipping instruction against the draft bill of lading.",
            "attachments": ["attachments/si.txt", "attachments/bl.txt"],
        }
        attachment_bytes = {
            "attachments/si.txt": SI_TEXT_MISSING_WEIGHT.encode(),
            "attachments/bl.txt": BL_TEXT_DIFFERENT_CONSIGNEE.encode(),
        }

        result = process_email(email, attachment_bytes=attachment_bytes)

        self.assertEqual(result.status, "NEEDS_REVIEW")
        self.assertEqual(result.review_reason, "missing_value")
        self.assertFalse(result.has_defect)
        self.assertEqual(result.defect_fields, [])

    def test_real_mismatch_with_complete_data_still_reports_defects(self):
        # Both sides fully readable/complete, genuine difference on consignee:
        # must remain MISMATCH with has_defect/defect_fields populated and
        # no review_reason.
        email = {
            "email_id": "email_test_real_mismatch",
            "from": "ops@example.com",
            "subject": "Please check draft BL against shipping instruction",
            "body": "Please verify the shipping instruction against the draft bill of lading.",
            "attachments": ["attachments/si.txt", "attachments/bl.txt"],
        }
        attachment_bytes = {
            "attachments/si.txt": SI_TEXT.encode(),
            "attachments/bl.txt": BL_TEXT_DIFFERENT_CONSIGNEE.encode(),
        }

        result = process_email(email, attachment_bytes=attachment_bytes)

        self.assertEqual(result.status, "MISMATCH")
        self.assertIsNone(result.review_reason)
        self.assertTrue(result.has_defect)
        self.assertIn("consignee", result.defect_fields)

    def test_exact_match_remains_ok_with_no_defect_markers(self):
        email = {
            "email_id": "email_test_exact_match",
            "from": "ops@example.com",
            "subject": "Please check draft BL against shipping instruction",
            "body": "Please verify the shipping instruction against the draft bill of lading.",
            "attachments": ["attachments/si.txt", "attachments/bl.txt"],
        }
        attachment_bytes = {
            "attachments/si.txt": SI_TEXT.encode(),
            "attachments/bl.txt": BL_TEXT.encode(),
        }

        result = process_email(email, attachment_bytes=attachment_bytes)

        self.assertEqual(result.status, "OK")
        self.assertIsNone(result.review_reason)
        self.assertFalse(result.has_defect)
        self.assertEqual(result.defect_fields, [])

    def test_finalize_strips_defects_whenever_review_reason_is_set(self):
        # Direct unit coverage of the guard itself, independent of how the
        # (possibly stale) has_defect/defect_fields got onto the result.
        leaky = EmailResult(
            email_id="email_leaky",
            category="BL_COMPARISON",
            status="NEEDS_REVIEW",
            defect_fields=["consignee", "gross_weight_kg"],
            has_defect=True,
            review_reason="missing_value",
        )

        cleaned = _finalize(leaky)

        self.assertEqual(cleaned.status, "NEEDS_REVIEW")
        self.assertFalse(cleaned.has_defect)
        self.assertEqual(cleaned.defect_fields, [])

    def test_finalize_leaves_mismatch_result_untouched(self):
        clean = EmailResult(
            email_id="email_clean",
            category="BL_COMPARISON",
            status="MISMATCH",
            defect_fields=["shipper"],
            has_defect=True,
            review_reason=None,
        )

        result = _finalize(clean)

        self.assertEqual(result.status, "MISMATCH")
        self.assertTrue(result.has_defect)
        self.assertEqual(result.defect_fields, ["shipper"])


if __name__ == "__main__":
    unittest.main()