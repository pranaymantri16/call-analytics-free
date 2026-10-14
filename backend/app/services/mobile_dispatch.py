"""Durable mobile dispatch with fenced claims and periodic broker recovery."""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import or_, select, update
from app.database import AsyncSessionLocal
from app.models.mobile import MobileRecording
from app.models.call import Call


def due(now):
    return or_(
        (MobileRecording.dispatch_state == "pending") & or_(MobileRecording.next_dispatch_at.is_(None), MobileRecording.next_dispatch_at <= now),
        (MobileRecording.dispatch_state == "sending") & (MobileRecording.next_dispatch_at <= now),
        (MobileRecording.dispatch_state == "sent") & (MobileRecording.last_dispatch_at < now - timedelta(minutes=15)),
    )


async def dispatch_recording(receipt_id, session_factory=None, submit=None):
    factory = session_factory or AsyncSessionLocal
    now = datetime.now(timezone.utc)
    token = str(uuid.uuid4())
    async with factory() as db:
        # SQL conditional update also guards concurrent claimers in tests without row locks.
        claim = await db.execute(update(MobileRecording).where(MobileRecording.id == receipt_id, due(now), MobileRecording.call_id.in_(select(Call.id).where(Call.status.in_(["queued", "processing"])))).values(dispatch_state="sending", lease_token=token, next_dispatch_at=now+timedelta(seconds=60), dispatch_attempts=MobileRecording.dispatch_attempts+1))
        if claim.rowcount != 1:
            await db.rollback()
            return False
        row = await db.get(MobileRecording, receipt_id)
        call_id, attempt = row.call_id, row.dispatch_attempts
        await db.commit()
    try:
        if submit is None:
            from app.tasks.celery_tasks import process_call
            submit = lambda cid, key: process_call.apply_async(args=[cid], task_id=key, retry=False)
        await asyncio.to_thread(submit, call_id, f"mobile-{receipt_id}")
        values = dict(dispatch_state="sent", lease_token=None, next_dispatch_at=None, last_dispatch_at=now, last_error=None)
    except Exception:
        values = dict(dispatch_state="pending", lease_token=None, next_dispatch_at=now+timedelta(seconds=min(300, 5 * 2**min(attempt, 6))), last_error="broker_unavailable")
    async with factory() as db:
        await db.execute(update(MobileRecording).where(MobileRecording.id == receipt_id, MobileRecording.lease_token == token).values(**values))
        await db.commit()
    return values["dispatch_state"] == "sent"


async def recover_mobile(session_factory=None, submit=None):
    factory = session_factory or AsyncSessionLocal
    async with factory() as db:
        ids = (await db.execute(select(MobileRecording.id).join(Call, MobileRecording.call_id == Call.id).where(due(datetime.now(timezone.utc)), Call.status.in_(["queued", "processing"])).limit(100))).scalars().all()
    for receipt_id in ids:
        await dispatch_recording(receipt_id, factory, submit)
