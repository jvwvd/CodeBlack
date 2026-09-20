from models import ShipmentFields


FIELDS = (
    "shipper",
    "consignee",
    "notify_party",
    "port_of_loading",
    "port_of_discharge",
    "container_count",
    "gross_weight_kg",
)


def compare(si: ShipmentFields, bl: ShipmentFields) -> list[str]:
    """Compare normalized SI against normalized BL."""

    defects = []

    for field in FIELDS:
        if getattr(si, field) != getattr(bl, field):
            defects.append(field)

    return defects