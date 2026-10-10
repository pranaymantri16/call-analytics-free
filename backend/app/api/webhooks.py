import os, uuid
from pathlib import Path
import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.database import get_db
from app.api.calls import create_call
from app.services.audio_utils import SUPPORTED_AUDIO_EXTENSIONS, get_audio_suffix

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

class CallCompletedPayload(BaseModel):
    audio_url: HttpUrl
    caller_name: str = "Caller"
    customer_name: str = "Customer"
    external_call_id: str | None = None

@router.post("/call-completed")
async def call_completed(payload: CallCompletedPayload, x_webhook_secret: str | None = Header(None),
                         db: AsyncSession = Depends(get_db)):
    if settings.webhook_secret and x_webhook_secret != settings.webhook_secret:
        raise HTTPException(401, "Invalid webhook secret")
    # For production, restrict destinations to an allowlist to prevent SSRF.
    suffix = get_audio_suffix(str(payload.audio_url))
    if suffix not in SUPPORTED_AUDIO_EXTENSIONS:
        supported = ", ".join(sorted(ext.lstrip(".") for ext in SUPPORTED_AUDIO_EXTENSIONS))
        raise HTTPException(400, f"audio_url must end in a supported audio extension. Supported formats include: {supported}.")
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            response = await client.get(str(payload.audio_url))
            response.raise_for_status()
            if len(response.content) > settings.max_upload_mb * 1024 * 1024:
                raise HTTPException(413, "Audio file too large")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"Could not download audio: {exc}")
    directory = Path(settings.audio_dir); directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{uuid.uuid4().hex}{suffix}"
    path.write_bytes(response.content)
    call = await create_call(db, str(path), payload.caller_name, payload.customer_name, payload.external_call_id)
    return {"id": call.id, "status": call.status}
