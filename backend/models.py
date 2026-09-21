from typing import Literal, Optional

from pydantic import BaseModel, Field


Category = Literal[
    "BL_COMPARISON",
    "SI_REQUEST",
    "INVOICE_QUERY",
    "GENERAL",
    "SPAM",
]

Status = Literal[
    "OK",
    "MISMATCH",
    "NEEDS_REVIEW",
]

ReviewReason = Literal[
    "wrong_doc_type",
    "missing_attachment",
    "unreadable",
    "missing_value",
]


class ShipmentFields(BaseModel):
    shipper: Optional[str] = None
    consignee: Optional[str] = None
    notify_party: Optional[str] = None
    port_of_loading: Optional[str] = None
    port_of_discharge: Optional[str] = None
    container_count: Optional[int] = None
    gross_weight_kg: Optional[float] = None


class EmailResult(BaseModel):
    email_id: str
    category: Category
    status: Status = "OK"
    si: Optional[ShipmentFields] = None
    bl: Optional[ShipmentFields] = None
    defect_fields: list[str] = Field(default_factory=list)
    has_defect: bool = False
    review_reason: Optional[ReviewReason] = None
    decided_by: Optional[Literal["rule", "llm"]] = None
    notes: Optional[str] = None


class ReviewCorrectionRequest(BaseModel):
    """PATCH /api/emails/{email_id}/review request body.

    si/bl are whole-side corrections: when provided, they replace the
    stored side entirely (not merged field-by-field); when omitted, the
    existing stored side is kept unchanged.
    """
    si: Optional[ShipmentFields] = None
    bl: Optional[ShipmentFields] = None
    reviewer_notes: Optional[str] = None