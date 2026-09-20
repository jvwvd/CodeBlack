from models import Category


def classify_email(email: dict) -> tuple[Category, str]:
    """Classify an organizer email using deterministic rules first."""

    subject = email.get("subject", "")
    body = email.get("body", "")
    attachments = email.get("attachments", [])

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

    if (
        len(attachments) >= 2
        and mentions_si
        and mentions_bl
        and any(term in text for term in comparison_terms)
    ):
        return "BL_COMPARISON", "rule"

    invoice_terms = (
        "invoice",
        "billing",
        "local charge",
        "detention charge",
        "d&d",
        "payment",
    )

    if any(term in text for term in invoice_terms):
        return "INVOICE_QUERY", "rule"

    si_terms = (
        "request si",
        "cust si",
        "please find shipping instruction",
        "shipping instruction for",
    )

    if any(term in text for term in si_terms):
        return "SI_REQUEST", "rule"

    return "GENERAL", "rule"