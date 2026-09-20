import re

from models import ShipmentFields


def norm_company(v: str) -> str:
    value = v.upper()

    value = re.sub(r"\b(?:CO|LTD|SDN|BHD)\b\.?", " ", value)
    value = re.sub(r"[^\w&]+", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def norm_port(v: str) -> str:
    value = v.upper().strip()

    locode = re.search(r"\(([A-Z]{5})\)", value)
    if locode:
        return locode.group(1)

    aliases = {
        "SINGAPORE": "SGSIN",
    }

    cleaned = re.sub(r"[^\w]+", " ", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return aliases.get(cleaned, cleaned)


def norm_weight(v: str) -> float:
    value = v.upper().replace(",", "")

    match = re.search(r"(\d+(?:\.\d+)?)", value)
    if not match:
        raise ValueError(f"Cannot parse weight: {v}")

    weight = float(match.group(1))

    if "LB" in value:
        weight *= 0.45359237

    return round(weight, 3)


def norm_count(v: str) -> int:
    match = re.search(r"\d+", str(v))

    if not match:
        raise ValueError(f"Cannot parse container count: {v}")

    return int(match.group())


def normalize_fields(fields: ShipmentFields) -> ShipmentFields:
    return ShipmentFields(
        shipper=norm_company(fields.shipper) if fields.shipper else None,
        consignee=norm_company(fields.consignee) if fields.consignee else None,
        notify_party=norm_company(fields.notify_party) if fields.notify_party else None,
        port_of_loading=norm_port(fields.port_of_loading)
        if fields.port_of_loading
        else None,
        port_of_discharge=norm_port(fields.port_of_discharge)
        if fields.port_of_discharge
        else None,
        container_count=fields.container_count,
        gross_weight_kg=fields.gross_weight_kg,
    )