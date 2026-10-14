"""Android ingress into the existing Call -> process_call -> ERPNext pipeline."""
import hashlib
import hmac
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from app.config import settings
from app.database import get_db
from app.models import Call, Caller, Customer, MobileRecording
from app.services.mobile_dispatch import dispatch_recording

router = APIRouter(prefix="/api/mobile", tags=["mobile"])


class Metadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    recording_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    phone_number: str = Field(min_length=1, max_length=64)
    contact_name: str | None = Field(default=None, max_length=256)
    direction: str = Field(pattern=r"^(incoming|outgoing)$")
    call_start_timestamp: datetime
    call_duration_seconds: int = Field(ge=0)
    recording_duration_seconds: int | None = Field(default=None, ge=0)
    recording_creation_timestamp: datetime | None = None
    recording_modification_timestamp: datetime
    original_filename: str = Field(min_length=1, max_length=512)
    proposed_filename: str = Field(min_length=1, max_length=512)
    match_status: str = Field(pattern=r"^(matched|manual)$")
    match_confidence: float | None = Field(default=None, ge=0, le=1)
    timezone: str = Field(pattern=r"^UTC$")
    upload_status: str = Field(pattern=r"^pending$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("call_start_timestamp", "recording_creation_timestamp", "recording_modification_timestamp")
    @classmethod
    def aware(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("An explicit timezone offset is required")
        return value


def device_auth(authorization: str = Header(default="")):
    if not settings.mobile_enabled:
        raise HTTPException(503, "Mobile uploads are not configured")
    supplied = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
    for device, token in settings.mobile_devices.items():
        if token.get_secret_value() and hmac.compare_digest(supplied.encode(), token.get_secret_value().encode()):
            return device
    raise HTTPException(401, "Invalid device credentials")


def valid_container(prefix, extension):
    return {"wav": prefix[:4] == b"RIFF" and prefix[8:12] == b"WAVE", "m4a": prefix[4:8] == b"ftyp", "3gp": prefix[4:8] == b"ftyp", "amr": prefix.startswith(b"#!AMR"), "ogg": prefix.startswith(b"OggS"), "mp3": prefix.startswith(b"ID3") or len(prefix) >= 2 and prefix[0] == 255 and prefix[1] & 224 == 224, "aac": len(prefix) >= 2 and prefix[0] == 255 and prefix[1] & 246 == 240}.get(extension, False)


def acknowledgement(receipt, call):
    status = {"queued": "accepted", "processing": "processing", "completed": "completed", "failed": "failed"}.get(call.status, "accepted")
    return {"device_id": receipt.device_id, "recording_id": receipt.recording_id, "server_recording_id": str(call.id), "sha256": receipt.sha256, "status": status}


@router.get("/health")
async def health(device=Depends(device_auth), db=Depends(get_db)):
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.post("/recordings", status_code=201)
async def upload(audio: UploadFile = File(...), metadata: str = Form(...), idempotency_key: str = Header(alias="Idempotency-Key"), device=Depends(device_auth), db=Depends(get_db)):
    if len(metadata.encode()) > 16 * 1024:
        raise HTTPException(413, "Metadata too large")
    try:
        data = Metadata.model_validate_json(metadata)
    except ValidationError:
        raise HTTPException(422, "Invalid recording metadata")
    if device != data.device_id:
        raise HTTPException(403, "Device mismatch")
    if idempotency_key != f"{device}:{data.recording_id}":
        raise HTTPException(422, "Invalid idempotency key")
    canonical = data.model_dump(mode="json")
    metadata_hash = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    extension = Path(data.proposed_filename).suffix.lower().lstrip(".")
    directory = Path(settings.audio_dir) / "mobile"
    directory.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="upload-", suffix=".tmp", dir=directory)
    temporary = Path(temporary)
    digest, prefix, size = hashlib.sha256(), b"", 0
    try:
        with os.fdopen(fd, "wb") as output:
            while chunk := await audio.read(64 * 1024):
                size += len(chunk)
                if size > settings.max_upload_mb * 1024 * 1024:
                    raise HTTPException(413, "Audio exceeds upload limit")
                digest.update(chunk)
                if len(prefix) < 64:
                    prefix = (prefix + chunk)[:64]
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if not size or not valid_container(prefix, extension):
            raise HTTPException(415, "Unsupported audio container")
        actual = digest.hexdigest()
        if actual != data.sha256:
            raise HTTPException(422, "Checksum mismatch")
        destination = directory / f"{actual}.{extension}"
        try:
            os.link(temporary, destination)
        except FileExistsError:
            pass
        query = select(MobileRecording).where(MobileRecording.device_id == device, MobileRecording.recording_id == data.recording_id)
        receipt = (await db.execute(query)).scalar_one_or_none()
        if receipt:
            if receipt.sha256 != actual or receipt.metadata_hash != metadata_hash:
                raise HTTPException(409, "Recording identifier conflicts with a previous upload")
            call = await db.get(Call, receipt.call_id)
            return acknowledgement(receipt, call)
        # Preserve the phone number in dedicated metadata and use it as the customer
        # identity. Contact display names never replace that actual identifier.
        caller_name = f"Mobile device {device}"[:200]
        customer_name = data.phone_number
        caller = (await db.execute(select(Caller).where(Caller.name == caller_name).limit(1))).scalar_one_or_none()
        customer = (await db.execute(select(Customer).where(Customer.name == customer_name).limit(1))).scalar_one_or_none()
        if caller is None:
            caller = Caller(name=caller_name); db.add(caller); await db.flush()
        if customer is None:
            customer = Customer(name=customer_name); db.add(customer); await db.flush()
        call = Call(audio_path=str(destination), caller_id=caller.id, customer_id=customer.id, external_call_id=f"mobile:{hashlib.sha256(idempotency_key.encode()).hexdigest()}", status="queued")
        db.add(call)
        await db.flush()
        receipt = MobileRecording(id=str(uuid.uuid4()), device_id=device, recording_id=data.recording_id, idempotency_key=idempotency_key, sha256=actual, metadata_hash=metadata_hash, metadata_json=canonical, call_id=call.id, received_at=datetime.now(timezone.utc), dispatch_state="pending", dispatch_attempts=0)
        db.add(receipt)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            receipt = (await db.execute(query)).scalar_one_or_none()
            if receipt is None or receipt.sha256 != actual or receipt.metadata_hash != metadata_hash:
                raise HTTPException(409, "Conflicting duplicate upload")
            call = await db.get(Call, receipt.call_id)
        # Commit receipt, existing Call and dispatch intent together before touching Redis.
        # Broker failure leaves pending work for Celery beat and does not lose the upload.
        await dispatch_recording(receipt.id)
        return acknowledgement(receipt, call)
    finally:
        temporary.unlink(missing_ok=True)
        await audio.close()


@router.get("/recordings/{recording_id}/status")
async def status(recording_id: str, device_id: str, device=Depends(device_auth), db=Depends(get_db)):
    if device_id != device:
        raise HTTPException(403, "Device mismatch")
    receipt = (await db.execute(select(MobileRecording).where(MobileRecording.device_id == device, MobileRecording.recording_id == recording_id))).scalar_one_or_none()
    if receipt is None:
        raise HTTPException(404, "Recording not found")
    return acknowledgement(receipt, await db.get(Call, receipt.call_id))
