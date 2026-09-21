import logging

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import database
import orchestration
from config import settings
from models import ReviewCorrectionRequest

logger = logging.getLogger("sdoc.backend")

app = FastAPI(title="Shipping Document Verification Backend")

allowed_origins = ["http://localhost:5173"]
if settings.FRONTEND_URL:
    allowed_origins.append(settings.FRONTEND_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled error while serving %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/emails")
def list_emails(
    status: str | None = None,
    category: str | None = None,
    processing_status: str | None = None,
    limit: int = 100,
):
    items = database.list_emails(
        status=status,
        category=category,
        processing_status=processing_status,
        limit=limit,
    )
    return {"items": items, "count": len(items)}


@app.get("/api/emails/{email_id}")
def get_email(email_id: str):
    email = database.get_email(email_id)
    if email is None:
        raise HTTPException(status_code=404, detail=f"email not found: {email_id}")
    return email


@app.get("/api/emails/{email_id}/attachments")
def list_email_attachments(email_id: str):
    items = database.list_attachments(email_id)
    return {"items": items, "count": len(items)}


@app.get("/api/documents/signed-url")
def get_signed_document_url(path: str = Query(..., min_length=1)):
    cleaned = path.strip()
    if not cleaned or ".." in cleaned:
        raise HTTPException(status_code=400, detail="invalid document path")
    url = database.create_signed_document_url(cleaned)
    return {"url": url, "expires_in": database.DEFAULT_SIGNED_URL_EXPIRY_SECONDS}


@app.post("/api/emails/{email_id}/process")
def process_email_endpoint(email_id: str):
    result = orchestration.process_and_persist_email(email_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"email not found: {email_id}")
    return result


@app.patch("/api/emails/{email_id}/review")
def review_email_endpoint(email_id: str, body: ReviewCorrectionRequest):
    updated = orchestration.apply_review_correction(
        email_id,
        si=body.si,
        bl=body.bl,
        reviewer_notes=body.reviewer_notes,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"email not found: {email_id}")
    return updated
