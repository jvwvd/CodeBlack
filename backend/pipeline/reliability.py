from models import ReviewReason, ShipmentFields


_REQUIRED_FIELDS = (
    "shipper",
    "consignee",
    "notify_party",
    "port_of_loading",
    "port_of_discharge",
    "container_count",
    "gross_weight_kg",
)

# Same phrasing classify.py's own mentions_si check uses for "this email is
# talking about an SI" -- kept as an independent, local copy here rather
# than importing from classify.py, since this answers a different question
# (did THIS email claim a document pair to compare) than classification
# does, and pipeline/classify.py is intentionally left untouched.
_SI_REFERENCE_PHRASES = (
    "shipping instruction",
    "attached si",
    "the si",
)


def _references_si(email: dict) -> bool:
    """Whether the email's own text references an SI (shipping instruction)
    at all -- i.e. the sender is treating this as a two-document comparison,
    not just a request to send one document later."""
    text = f"{email.get('subject', '')}\n{email.get('body', '')}".lower()
    return any(phrase in text for phrase in _SI_REFERENCE_PHRASES)


def check(
    email: dict,
    si_text: str | None,
    bl_text: str | None,
) -> ReviewReason | None:

    attachment_count = len(email.get("attachments", []))

    if attachment_count == 0:
        # No attachments AND no claim that one exists to compare against is
        # not evidence of a genuinely missing document -- e.g. "please send
        # the draft BL" has nothing to compare yet and is not a review case
        # (see process_email(), which short-circuits this to a clean OK
        # instead of attempting extraction on nothing). Only escalate when
        # the email itself indicates a comparison was expected.
        if _references_si(email):
            return "missing_attachment"
        return None

    if attachment_count == 1:
        # Exactly one of the two required documents is physically present --
        # genuinely partial, unlike the zero-attachment case above.
        return "missing_attachment"

    if si_text == "" or bl_text == "":
        return "unreadable"

    if si_text is None or bl_text is None:
        return "wrong_doc_type"

    return None


def check_missing_values(
    si: ShipmentFields,
    bl: ShipmentFields,
) -> ReviewReason | None:

    for field in _REQUIRED_FIELDS:
        if getattr(si, field) is None or getattr(bl, field) is None:
            return "missing_value"

    return None