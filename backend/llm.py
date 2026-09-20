from typing import Literal

from google import genai
from google.genai import types
from pydantic import BaseModel

from config import settings
from models import Category, ShipmentFields
from prompts import CLASSIFICATION_PROMPT, EXTRACTION_PROMPT


MODEL_NAME = "gemini-2.5-flash"


class ClassificationResponse(BaseModel):
    category: Category


def _client() -> genai.Client | None:
    if not settings.GEMINI_API_KEY:
        return None

    return genai.Client(api_key=settings.GEMINI_API_KEY)


def classify_with_llm(email: dict) -> Category | None:
    client = _client()

    if client is None:
        return None

    content = f"""
{CLASSIFICATION_PROMPT}

Subject:
{email.get("subject", "")}

Body:
{email.get("body", "")}
"""

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=content,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ClassificationResponse,
                temperature=0,
            ),
        )

        result = ClassificationResponse.model_validate_json(response.text)
        return result.category

    except Exception:
        return None


def extract_with_llm(text: str) -> ShipmentFields | None:
    client = _client()

    if client is None:
        return None

    content = f"""
{EXTRACTION_PROMPT}

DOCUMENT:
{text}
"""

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=content,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ShipmentFields,
                temperature=0,
            ),
        )

        return ShipmentFields.model_validate_json(response.text)

    except Exception:
        return None