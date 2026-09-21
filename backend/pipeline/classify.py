import re

from llm import classify_with_llm
from models import Category


def classify_email(email: dict) -> tuple[Category, str]:
    """Rules first; AI fallback only when rules are insufficient."""

    subject = email.get("subject", "")
    body = email.get("body", "")
    text = f"{subject}\n{body}".lower()

    spam_terms = (
        "congratulations",
        "gift card",
        "bitcoin investment",
        "guaranteed 300%",
        "click here to claim",
        "limited time offer",
        "verify account immediately",
    )

    if any(term in text for term in spam_terms):
        return "SPAM", "rule"

    mentions_si = (
        "shipping instruction" in text
        or "attached si" in text
        or "the si" in text
    )

    mentions_bl = (
        "draft bl" in text
        or "draft b/l" in text
        or "bill of lading" in text
    )

    comparison_terms = (
        "compare",
        "check",
        "confirm",
        "verify",
        "discrepancy",
        "checking",
    )

    # Do NOT require two attachments here.
    # Missing attachments must still reach reliability.py.
    if (
        mentions_si
        and mentions_bl
        and any(term in text for term in comparison_terms)
    ):
        return "BL_COMPARISON", "rule"

    subject_upper = subject.upper()
    normalized_subject = " ".join(
        subject_upper.replace("_", " ").split()
    )

    # Strong organizer SI_REQUEST subject signals.
    # Deliberately do not match bare "SI".
    si_subject_signal = (
        "CUST SI" in normalized_subject
        or "REQUEST SI" in normalized_subject
        or "SI NEEDED" in normalized_subject
    )

    # Handles:
    # SI - ...
    # RE_ SI - ...
    # RE: SI - ...
    si_dash_subject = re.match(
        r"^\s*(?:(?:RE|FW|FWD)\s*[:_-]\s*)*SI\s*-\s*",
        subject,
        flags=re.IGNORECASE,
    )

    if si_subject_signal or si_dash_subject:
        return "SI_REQUEST", "rule"

    invoice_subject_signals = (
        "REQUEST TO CANCEL INVOICE",
        "LOCAL CHARGES FOB",
        "RAK BILLING",
        "SD BILLING PROCESS COMPLETED",
        "MILL D & D CHARGES",
    )

    if any(
        signal in normalized_subject
        for signal in invoice_subject_signals
    ):
        return "INVOICE_QUERY", "rule"

    si_terms = (
        "request si",
        "prepare si",
        "new si",
        "shipping instruction for",
    )

    if any(term in text for term in si_terms):
        return "SI_REQUEST", "rule"

    # Rules are uncertain: ask the configured AI provider.
    llm_category = classify_with_llm(email)

    if llm_category is not None:
        return llm_category, "llm"

    # Safe deterministic fallback if AI is unavailable/fails.
    return "GENERAL", "rule"