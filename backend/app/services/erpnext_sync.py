"""PostgreSQL outbox with leases, fencing tokens and periodic reconciliation."""
import logging
import json
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, or_, func
from sqlalchemy.dialects.postgresql import insert
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Call, ERPNextSync
from app.services.erpnext import ERPNextClient, IntegrationError, build_payload

logger = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc)


def event(name, **fields):
    data = {"erpnext_event": name, **fields}
    logger.info(json.dumps(data, sort_keys=True), extra=data)


async def add_pending(db, call_id):
    await db.execute(insert(ERPNextSync).values(
        call_id=call_id, status="pending", attempt_count=0, next_retry_at=now(),
    ).on_conflict_do_nothing(index_elements=[ERPNextSync.call_id]))


def enqueue(call_id):
    if not settings.erpnext_enabled:
        return
    try:
        from app.tasks.celery_tasks import sync_erpnext
        sync_erpnext.delay(call_id)
    except Exception:
        event("dispatch_deferred", call_id=call_id, error_code="broker_unavailable")


def due(at):
    return or_(
        (ERPNextSync.status == "pending") &
        or_(ERPNextSync.next_retry_at.is_(None), ERPNextSync.next_retry_at <= at),
        (ERPNextSync.status == "processing") & (ERPNextSync.lease_until <= at),
    )


async def sync_call(call_id, session_factory=AsyncSessionLocal, config=settings, client=None):
    if not config.erpnext_enabled:
        return
    token = str(uuid.uuid4())
    async with session_factory() as db:
        row = (await db.execute(select(ERPNextSync).where(
            ERPNextSync.call_id == call_id, due(now()),
        ).with_for_update(skip_locked=True))).scalar_one_or_none()
        if row is None:
            return
        if row.attempt_count >= config.erpnext_max_retries + 1:
            row.status, row.last_error = "failed", "retry_limit_exhausted"
            row.lease_until = row.lease_token = row.next_retry_at = None
            await db.commit()
            event("permanent_failure", call_id=call_id, error_code="retry_limit_exhausted")
            return
        row.status = "processing"
        row.attempt_count += 1
        attempt = row.attempt_count
        row.last_attempt_at = now()
        row.lease_until = now() + timedelta(seconds=config.erpnext_request_timeout + 60)
        row.lease_token = token
        row.next_retry_at = None
        call = await db.get(Call, call_id)
        try:
            payload = build_payload(call)
            failure = None
        except IntegrationError as exc:
            payload, failure = None, exc
        completed_at = call.processed_at if call else None
        await db.commit()
    age = max(0, (now() - completed_at).total_seconds()) if completed_at else None
    event("attempt", call_id=call_id, attempt=attempt, analysis_age_seconds=age)
    if failure is None:
        try:
            await (client or ERPNextClient(config)).send(payload)
        except IntegrationError as exc:
            failure = exc
        except Exception:
            failure = IntegrationError("internal_sync_failure")
    async with session_factory() as db:
        row = (await db.execute(select(ERPNextSync).where(
            ERPNextSync.call_id == call_id,
        ).with_for_update())).scalar_one()
        if row.lease_token != token:
            return  # An expired worker cannot overwrite a newer attempt.
        row.lease_token = row.lease_until = None
        if failure is None:
            row.status, row.last_error, row.http_category = "synced", None, "2xx"
            row.last_success_at, row.next_retry_at = now(), None
            name = "success"
        else:
            row.last_error, row.http_category = failure.code, failure.category
            if failure.retryable and attempt <= config.erpnext_max_retries:
                row.status = "pending"
                row.next_retry_at = now() + timedelta(seconds=min(3600, 30 * 2 ** (attempt - 1)))
                name = "retry"
            else:
                row.status, row.next_retry_at = "failed", None
                name = "permanent_failure"
        await db.commit()
        event(name, call_id=call_id, attempt=attempt, http_category=row.http_category,
              error_code=row.last_error, analysis_age_seconds=age)


async def recover(session_factory=AsyncSessionLocal, dispatch=enqueue, config=settings):
    if not config.erpnext_enabled:
        return
    async with session_factory() as db:
        # Reconcile broker/DB failures and analyses completed while disabled.
        missing = (await db.execute(select(Call.id).outerjoin(
            ERPNextSync, Call.id == ERPNextSync.call_id,
        ).where(Call.status == "completed", ERPNextSync.call_id.is_(None))
            .order_by(Call.id).limit(200))).scalars().all()
        for call_id in missing:
            await add_pending(db, call_id)
        await db.commit()
        ids = (await db.execute(select(ERPNextSync.call_id).where(due(now()))
                               .order_by(ERPNextSync.last_attempt_at.asc().nullsfirst(), ERPNextSync.call_id)
                               .limit(200))).scalars().all()
        metrics = await sync_metrics(db)
    event("backlog", **metrics)
    for call_id in ids:
        dispatch(call_id)


async def sync_metrics(db):
    counts = dict((await db.execute(select(ERPNextSync.status, func.count())
                                   .group_by(ERPNextSync.status))).all())
    oldest = (await db.execute(select(func.min(Call.processed_at)).join(
        ERPNextSync, ERPNextSync.call_id == Call.id,
    ).where(ERPNextSync.status.in_(["pending", "processing"])))).scalar()
    return {"pending": counts.get("pending", 0), "processing": counts.get("processing", 0),
            "synced": counts.get("synced", 0), "failed": counts.get("failed", 0),
            "oldest_pending_age_seconds": max(0, (now() - oldest).total_seconds()) if oldest else 0}
