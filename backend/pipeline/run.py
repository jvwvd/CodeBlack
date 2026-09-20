from models import EmailResult

from pipeline import classify
from pipeline import compare
from pipeline import documents
from pipeline import extract
from pipeline import normalize
from pipeline import reliability


def process_email(email: dict) -> EmailResult:
    category, decided_by = classify.classify_email(email)

    if category != "BL_COMPARISON":
        return EmailResult(
            email_id=email["email_id"],
            category=category,
            decided_by=decided_by,
        )

    si_text, bl_text = documents.load_pair(email)

    review_reason = reliability.check(
        email,
        si_text,
        bl_text,
    )

    if review_reason:
        return EmailResult(
            email_id=email["email_id"],
            category=category,
            status="NEEDS_REVIEW",
            review_reason=review_reason,
            decided_by=decided_by,
        )

    si = extract.extract_fields(si_text)
    bl = extract.extract_fields(bl_text)

    normalized_si = normalize.normalize_fields(si)
    normalized_bl = normalize.normalize_fields(bl)

    defects = compare.compare(
        normalized_si,
        normalized_bl,
    )

    missing_reason = reliability.check_missing_values(si, bl)

    if missing_reason:
        return EmailResult(
            email_id=email["email_id"],
            category=category,
            status="NEEDS_REVIEW",
            si=si,
            bl=bl,
            defect_fields=defects,
            has_defect=bool(defects),
            review_reason=missing_reason,
            decided_by=decided_by,
        )

    return EmailResult(
        email_id=email["email_id"],
        category=category,
        status="MISMATCH" if defects else "OK",
        si=si,
        bl=bl,
        defect_fields=defects,
        has_defect=bool(defects),
        decided_by=decided_by,
        notes=None if defects else "No mismatch detected.",
    )