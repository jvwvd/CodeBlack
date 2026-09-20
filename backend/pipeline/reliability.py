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


def check(
    email: dict,
    si_text: str | None,
    bl_text: str | None,
) -> ReviewReason | None:

    if len(email.get("attachments", [])) < 2:
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