import re

from llm import extract_with_llm
from models import ShipmentFields
from pipeline.normalize import norm_count, norm_weight


def _find(text: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE | re.MULTILINE,
        )

        if match:
            value = match.group(1).strip().strip("|").strip()

            if value:
                return value

    return None


def _safe_count(value: str | None) -> int | None:
    if value is None:
        return None

    try:
        return norm_count(value)
    except ValueError:
        return None


def _safe_weight(value: str | None) -> float | None:
    if value is None:
        return None

    try:
        return norm_weight(value)
    except ValueError:
        return None


def extract_fields(text: str) -> ShipmentFields:
    """
    Deterministic extraction first.
    Gemini may only fill fields deterministic extraction missed.
    """

    shipper = _find(
        text,
        (
            r"^\s*Shipper(?:/Exporter)?(?:\s*\([^)]*\))*\s*(?::|\|)\s*([^|\n]+)",
            r"^\s*Shipper(?:/Exporter)?(?:\s*\([^)]*\))*\s*$\n\s*([^|\n]+)",
        ),
    )

    consignee = _find(
        text,
        (
            r"^\s*Consignee(?:\s*\([^)]*\))*\s*(?::|\|)\s*([^|\n]+)",
            r"^\s*Consignee(?:\s*\([^)]*\))*\s*$\n\s*([^|\n]+)",
            r"^\s*To the Order of\s*(?::|\|)\s*([^|\n]+)",
            r"^\s*To the Order of\s*$\n\s*([^|\n]+)",
        ),
    )

    notify_party = _find(
        text,
        (
            r"^\s*Notify Party(?:/Intermediate Consignee)?(?:\s*\([^)]*\))*\s*(?::|\|)\s*([^|\n]+)",
            r"^\s*Notify(?:\s*\([^)]*\))*\s*(?::|\|)\s*([^|\n]+)",
            r"^\s*Notify Party\s*$\n\s*([^|\n]+)",
        ),
    )

    port_of_loading = _find(
        text,
        (
            r"^\s*Port of Loading(?:\s*\(POL\))?(?:\s*\([^)]*\))*\s*(?::|\|)\s*([^|\n]+)",
            r"^\s*POL(?:\s*\([^)]*\))*\s*(?::|\|)\s*([^|\n]+)",
            r"^\s*Load Port\s*(?::|\|)\s*([^|\n]+)",
            r"^\s*Load Port\s*$\n\s*([^|\n]+)",
        ),
    )

    port_of_discharge = _find(
        text,
        (
            r"^\s*Port of Discharge(?:\s*\(POD\))?(?:\s*\([^)]*\))*\s*(?::|\|)\s*([^|\n]+)",
            r"^\s*Discharge Port(?:\s*\([^)]*\))*\s*(?::|\|)\s*([^|\n]+)",
            r"^\s*POD(?:\s*\([^)]*\))*\s*(?::|\|)\s*([^|\n]+)",
            r"^\s*Port of Discharge\s*$\n\s*([^|\n]+)",
        ),
    )

    container_raw = _find(
        text,
        (
            r"^\s*No\.?\s*of Containers(?: or Packages)?(?:\s*\([^)]*\))*\s*(?::|\|)\s*([^|\n]+)",
            r"^\s*Container Count\s*(?::|\|)\s*([^|\n]+)",
            r"^\s*Total Containers\s*(?::|\|)\s*([^|\n]+)",
        ),
    )

    weight_raw = _find(
        text,
        (
            r"^\s*Gross\s*Weight[^\n:]*\s*(?::|\|)\s*([^|\n]+)",
            r"^\s*Total Gross Weight[^\n:]*\s*(?::|\|)\s*([^|\n]+)",
            r"^\s*Gross\s*Wt[^\n:]*\s*(?::|\|)\s*([^|\n]+)",
        ),
    )

    result = ShipmentFields(
        shipper=shipper,
        consignee=consignee,
        notify_party=notify_party,
        port_of_loading=port_of_loading,
        port_of_discharge=port_of_discharge,
        container_count=_safe_count(container_raw),
        gross_weight_kg=_safe_weight(weight_raw),
    )

    missing_fields = [
        field_name
        for field_name, value in result.model_dump().items()
        if value is None
    ]

    if not missing_fields:
        return result

    llm_result = extract_with_llm(text)

    if llm_result is None:
        return result

    merged = result.model_dump()
    llm_values = llm_result.model_dump()

    for field_name in missing_fields:
        if llm_values[field_name] is not None:
            merged[field_name] = llm_values[field_name]

    return ShipmentFields(**merged)