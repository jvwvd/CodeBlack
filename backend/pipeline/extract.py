import re

from models import ShipmentFields
from pipeline.normalize import norm_count, norm_weight


def _find(text: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)

        if match:
            value = match.group(1).strip()
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
    """Deterministic extraction for structured/plain-text documents."""

    shipper = _find(
        text,
        (
            r"^\s*Shipper(?:/Exporter|\s*\([^)]*\))?\s*:\s*(.+)$",
        ),
    )

    consignee = _find(
        text,
        (
            r"^\s*Consignee(?:\s*\([^)]*\))?\s*:\s*(.+)$",
        ),
    )

    notify_party = _find(
        text,
        (
            r"^\s*Notify Party(?:/Intermediate Consignee)?\s*:\s*(.+)$",
            r"^\s*Notify\s*:\s*(.+)$",
        ),
    )

    port_of_loading = _find(
        text,
        (
            r"^\s*Port of Loading(?:\s*\(POL\))?\s*:\s*(.+)$",
            r"^\s*POL\s*:\s*(.+)$",
        ),
    )

    port_of_discharge = _find(
        text,
        (
            r"^\s*Port of Discharge(?:\s*\(POD\))?\s*:\s*(.+)$",
            r"^\s*Discharge Port\s*:\s*(.+)$",
            r"^\s*POD\s*:\s*(.+)$",
        ),
    )

    container_raw = _find(
        text,
        (
            r"^\s*No\.?\s*of Containers(?: or Packages)?\s*:\s*(.+)$",
            r"^\s*Container Count\s*:\s*(.+)$",
            r"^\s*Total Containers\s*:\s*(.+)$",
        ),
    )

    weight_raw = _find(
        text,
        (
            r"^\s*Gross\s*Weight[^\n:]*\s*:\s*(.+)$",
        ),
    )

    return ShipmentFields(
        shipper=shipper,
        consignee=consignee,
        notify_party=notify_party,
        port_of_loading=port_of_loading,
        port_of_discharge=port_of_discharge,
        container_count=_safe_count(container_raw),
        gross_weight_kg=_safe_weight(weight_raw),
    )