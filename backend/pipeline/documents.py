from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]


def _resolve_path(path: str) -> Path | None:
    supplied = Path(path)

    candidates = [
        supplied,
        Path.cwd() / supplied,
        _REPO_ROOT / supplied,
        _REPO_ROOT / "data" / supplied,
    ]

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    return None


def read_attachment(path: str) -> str | None:
    """Read a plain-text attachment. Binary parsers are added next."""

    resolved = _resolve_path(path)

    if resolved is None:
        return None

    if resolved.suffix.lower() != ".txt":
        return None

    try:
        return resolved.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def identify_doc_type(text: str) -> str:
    if not text or len(text.strip()) < 20:
        return "UNREADABLE"

    upper = text.upper()

    if "SHIPPING INSTRUCTION" in upper:
        return "SI"

    if "BILL OF LADING" in upper:
        return "BL"

    return "OTHER"


def load_pair(email: dict) -> tuple[str | None, str | None]:
    """Load and identify one SI and one BL using document content."""

    si_text = None
    bl_text = None
    unreadable_found = False

    for attachment in email.get("attachments", []):
        text = read_attachment(attachment)

        if text is None:
            unreadable_found = True
            continue

        doc_type = identify_doc_type(text)

        if doc_type == "SI" and si_text is None:
            si_text = text
        elif doc_type == "BL" and bl_text is None:
            bl_text = text

    if unreadable_found:
        if si_text is None:
            si_text = ""
        if bl_text is None:
            bl_text = ""

    return si_text, bl_text