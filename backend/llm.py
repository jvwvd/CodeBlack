import base64
import hashlib

import httpx
from pydantic import BaseModel

from config import settings
from models import Category, ShipmentFields
from prompts import CLASSIFICATION_PROMPT, EXTRACTION_PROMPT


DEFAULT_MODEL = "glm-5.3-flash"
CHAT_URL = "https://opencode.ai/zen/go/v1/chat/completions"
USER_AGENT = "codeblack-hackathon/1.0"


class ClassificationResponse(BaseModel):
    category: Category


def _api_key() -> str | None:
    return settings.OPENCODE_API_KEY or None


def _model_name() -> str:
    return settings.OPENCODE_MODEL or DEFAULT_MODEL


def _session_id(prefix: str, value: str | bytes) -> str:
    """
    Build a stable OpenCode Go session ID without changing
    the existing public pipeline function signatures.
    """

    if isinstance(value, str):
        raw = value.encode("utf-8")
    else:
        raw = value

    digest = hashlib.sha256(raw).hexdigest()[:32]

    return f"codeblack-{prefix}-{digest}"


def _clean_json(text: str) -> str:
    """
    Remove optional Markdown fences before Pydantic validation.
    """

    value = text.strip()

    if value.startswith("```json"):
        value = value[len("```json"):]

    elif value.startswith("```"):
        value = value[len("```"):]

    if value.endswith("```"):
        value = value[:-3]

    return value.strip()


def _response_text(result: dict) -> str | None:
    """
    Extract assistant text from the OpenAI-compatible response.
    """

    choices = result.get("choices", [])

    if not choices:
        return None

    message = choices[0].get("message", {})
    content = message.get("content")

    if isinstance(content, str):
        return content.strip() or None

    if isinstance(content, list):
        chunks: list[str] = []

        for part in content:
            if not isinstance(part, dict):
                continue

            text = part.get("text")

            if text:
                chunks.append(str(text))

        combined = "\n".join(chunks).strip()

        return combined or None

    return None


def _chat(
    content: str | list[dict],
    session_id: str,
    max_tokens: int = 2048,
) -> str | None:
    """
    Send one request through OpenCode Go.
    """

    api_key = _api_key()

    if not api_key:
        return None

    payload = {
        "model": _model_name(),
        "messages": [
            {
                "role": "user",
                "content": content,
            }
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "x-opencode-session": session_id,
    }

    try:
        response = httpx.post(
            CHAT_URL,
            headers=headers,
            json=payload,
            timeout=90.0,
        )

        response.raise_for_status()

        return _response_text(response.json())

    except Exception:
        return None


def classify_with_llm(
    email: dict,
) -> Category | None:
    content = f"""
{CLASSIFICATION_PROMPT}

Subject:
{email.get("subject", "")}

Body:
{email.get("body", "")}

Return exactly one JSON object in this format:

{{
  "category": "BL_COMPARISON"
}}

The category value must be exactly one of:
BL_COMPARISON
SI_REQUEST
INVOICE_QUERY
GENERAL
SPAM

Do not return Markdown or additional explanation.
"""

    session_source = (
        email.get("email_id")
        or f"{email.get('subject', '')}\n{email.get('body', '')}"
    )

    text = _chat(
        content,
        session_id=_session_id(
            "classification",
            session_source,
        ),
        max_tokens=256,
    )

    if text is None:
        return None

    try:
        result = ClassificationResponse.model_validate_json(
            _clean_json(text)
        )

        return result.category

    except Exception:
        return None


def extract_with_llm(
    text: str,
) -> ShipmentFields | None:
    content = f"""
{EXTRACTION_PROMPT}

DOCUMENT:
{text}

Return exactly one JSON object containing all seven keys:

{{
  "shipper": null,
  "consignee": null,
  "notify_party": null,
  "port_of_loading": null,
  "port_of_discharge": null,
  "container_count": null,
  "gross_weight_kg": null
}}

Use null when a value cannot be reliably found.
Do not return Markdown or additional explanation.
"""

    response_text = _chat(
        content,
        session_id=_session_id(
            "extraction",
            text,
        ),
        max_tokens=1024,
    )

    if response_text is None:
        return None

    try:
        return ShipmentFields.model_validate_json(
            _clean_json(response_text)
        )

    except Exception:
        return None


def read_scanned_pdf_with_vision(
    data: bytes,
) -> str | None:
    """
    Read an image-only/scanned PDF through OpenCode Go.

    This function performs document reading only.
    It must never decide OK/MISMATCH/NEEDS_REVIEW.
    """

    prompt = """
Read this scanned shipping document and transcribe the visible text.

Rules:
- Do not invent or infer missing text.
- Preserve labels, company names, ports, container quantities, and weights.
- If text is unreadable, omit it rather than guessing.
- Return plain extracted text only.
"""

    encoded_pdf = base64.b64encode(
        data
    ).decode("utf-8")

    content = [
        {
            "type": "file",
            "file": {
                "filename": "scanned_document.pdf",
                "file_data": (
                    "data:application/pdf;base64,"
                    + encoded_pdf
                ),
            },
        },
        {
            "type": "text",
            "text": prompt,
        },
    ]

    text = _chat(
        content,
        session_id=_session_id(
            "vision",
            data,
        ),
        max_tokens=4096,
    )

    if text is None:
        return None

    text = text.strip()

    if len(text) < 20:
        return None

    return text