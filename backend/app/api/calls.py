from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.database import get_db
from app.models.caller import Caller
from app.models.customer import Customer
from app.models.call import Call
from app.tasks.celery_tasks import process_call
from app.services.audio_utils import SUPPORTED_AUDIO_EXTENSIONS, get_audio_suffix

router = APIRouter(prefix="/api/v1/calls", tags=["calls"])
def serialize(call: Call):
    return {
        "id": call.id, "external_call_id": call.external_call_id, "status": call.status,
        "caller_name": call.caller.name if call.caller else "Unknown caller",
        "customer_name": call.customer.name if call.customer else "Unknown customer",
        "call_summary": call.call_summary, "customer_interest_level": call.customer_interest_level,
        "key_topics": call.key_topics or [], "action_items": call.action_items or [],
        "agent_performance_score": call.agent_performance_score,
        "duration_seconds": call.duration_seconds, "transcript": call.transcript,
        "segments": call.segments or [], "error_message": call.error_message,
        "created_at": call.created_at.isoformat() if call.created_at else None,
        "processed_at": call.processed_at.isoformat() if call.processed_at else None,
    }

async def create_call(db, audio_path, caller_name, customer_name, external_call_id=None):
    caller = (await db.execute(select(Caller).where(Caller.name == caller_name))).scalar_one_or_none()
    if caller is None:
        caller = Caller(name=caller_name); db.add(caller); await db.flush()
    customer = (await db.execute(select(Customer).where(Customer.name == customer_name))).scalar_one_or_none()
    if customer is None:
        customer = Customer(name=customer_name); db.add(customer); await db.flush()
    call = Call(audio_path=audio_path, caller_id=caller.id, customer_id=customer.id,
                external_call_id=external_call_id, status="queued")
    db.add(call); await db.commit(); await db.refresh(call)
    process_call.delay(call.id)
    return call

@router.post("/upload")
async def upload_call(file: UploadFile = File(...), caller_name: str = Form("Caller"),
                      customer_name: str = Form("Customer"), db: AsyncSession = Depends(get_db)):
    suffix = get_audio_suffix(file.filename or "")
    if suffix not in SUPPORTED_AUDIO_EXTENSIONS:
        supported = ", ".join(sorted(ext.lstrip(".") for ext in SUPPORTED_AUDIO_EXTENSIONS))
        raise HTTPException(400, f"Unsupported audio format. Supported formats include: {supported}.")
    data = await file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {settings.max_upload_mb} MB limit.")
    directory = Path(settings.audio_dir); directory.mkdir(parents=True, exist_ok=True)
    import uuid
    path = directory / f"{uuid.uuid4().hex}{suffix}"
    path.write_bytes(data)
    call = await create_call(db, str(path), caller_name, customer_name)
    return {"id": call.id, "status": call.status}

@router.get("")
async def list_calls(search: str = "", status: str = "", limit: int = 50, offset: int = 0,
                     db: AsyncSession = Depends(get_db)):
    limit = max(1, min(limit, 100)); offset = max(0, offset)
    stmt = select(Call).options(selectinload(Call.caller), selectinload(Call.customer))
    if status:
        stmt = stmt.where(Call.status == status)
    if search:
        stmt = stmt.join(Caller, Call.caller_id == Caller.id).join(Customer, Call.customer_id == Customer.id)
        term = f"%{search}%"
        stmt = stmt.where(or_(Caller.name.ilike(term), Customer.name.ilike(term),
                              Call.call_summary.ilike(term), Call.transcript.ilike(term)))
    stmt = stmt.order_by(Call.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().unique().all()
    return [serialize(row) for row in rows]

@router.get("/{call_id}")
async def get_call(call_id: int, db: AsyncSession = Depends(get_db)):
    stmt = select(Call).options(selectinload(Call.caller), selectinload(Call.customer)).where(Call.id == call_id)
    call = (await db.execute(stmt)).scalar_one_or_none()
    if not call: raise HTTPException(404, "Call not found")
    return serialize(call)
