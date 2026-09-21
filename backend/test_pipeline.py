import unittest
from io import BytesIO
from unittest.mock import patch

import pymupdf
from docx import Document
from openpyxl import Workbook

from pipeline.classify import classify_email
from pipeline.documents import (
    identify_doc_type,
    parse_attachment_bytes,
)
from pipeline.run import process_email


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

    def test_si_request_subject_beats_invoice_text_in_body(self):
        body = """
        Please find the shipping instruction attached.

        Documents Required:
        1) 3 Original invoice
        2) Packing list
        3) Original BL

        Forwarded thread also mentions billing and payment.
        """

        subjects = (
            "CUST SI _ MEA _ 5RCY-52735 __ PO_25_5465",
            "RE_ CUST SI _ MEA _ 5RCY-51168 __ PO_25_3508",
            "REQUEST SI _ 5APH-62718 _ HOUSTON_US",
            "RE_ REQUEST SI _ 5RCY-60883 _ CONAKRY_GUINEA",
            "SI NEEDED_ 5RUS-16202 _ EAST BRIGHT",
            "RE_ SI NEEDED_ 5APH-26773 _ UAB NOVAKOPA",
            "SI - HLCUSIN331541006 - DIRECT(HAPAG) - 5RUS-61793",
            "RE_ SI - SIJ3777014 - DIRECT(CMA) - 5ALT-88568",
        )

        for subject in subjects:
            with self.subTest(subject=subject):
                email = {
                    "email_id": "email_test_si_request",
                    "from": "ops@example.com",
                    "subject": subject,
                    "body": body,
                    "attachments": [],
                }

                category, decided_by = classify_email(email)

                self.assertEqual(category, "SI_REQUEST")
                self.assertEqual(decided_by, "rule")

    def test_documented_invoice_subject_signals(self):
        subjects = (
            "REQUEST TO CANCEL INVOICE -5250075802",
            "RE_ LOCAL CHARGES FOB - KARGOSMAR - TELEX RELEASE CHARGES",
            "2157 RAK BILLING 5070146693 MISSING GR",
            "_RPA_ India HSS SD Billing Process Completed - VISION",
            "Mill D & D charges - 6437419230",
        )

        for subject in subjects:
            with self.subTest(subject=subject):
                email = {
                    "email_id": "email_test_invoice",
                    "from": "ops@example.com",
                    "subject": subject,
                    "body": "Normal forwarded operational thread.",
                    "attachments": [],
                }

                category, decided_by = classify_email(email)

                self.assertEqual(category, "INVOICE_QUERY")
                self.assertEqual(decided_by, "rule")


if __name__ == "__main__":
    unittest.main()