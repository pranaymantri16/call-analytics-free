from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select, or_, func, case
from sqlalchemy.orm import defer, load_only
from app.api.erpnext import require_admin
from app.database import get_db
from app.models import Call, MobileRecording, ERPNextSync, RecordingAudit
from app.services.recording_audit import redact, analysis_snapshot

router = APIRouter(prefix="/api/v1/recording-audit", tags=["recording-audit"],
                   dependencies=[Depends(require_admin)])


def no_cache(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def summary(row):
    return {key: getattr(row, key) for key in (
        "id", "call_id", "device_id", "recording_id", "correlation_id", "stage",
        "event", "outcome", "attempt", "created_at",
    )}


def filtered_history(call_id=None, device_id=None, recording_id=None, stage=None, outcome=None):
    query = select(RecordingAudit)
    for name, value in (("call_id", call_id), ("stage", stage), ("outcome", outcome)):
        if value is not None:
            query = query.where(getattr(RecordingAudit, name) == value)
    mobile_calls = select(MobileRecording.call_id)
    if device_id is not None:
        mobile_calls = mobile_calls.where(MobileRecording.device_id == device_id)
    if recording_id is not None:
        mobile_calls = mobile_calls.where(MobileRecording.recording_id == recording_id)
    for name, value in (("device_id", device_id), ("recording_id", recording_id)):
        if value is not None:
            query = query.where(or_(getattr(RecordingAudit, name) == value,
                                    RecordingAudit.call_id.in_(mobile_calls)))
    return query


@router.get("/groups")
async def grouped_history(response: Response, call_id: int | None = Query(None, ge=1),
                          device_id: str | None = None, recording_id: str | None = None,
                          stage: str | None = None, outcome: str | None = None,
                          before_call_id: int | None = Query(None, ge=1),
                          limit: int = Query(30, ge=1, le=100), db=Depends(get_db)):
    no_cache(response)
    matching = filtered_history(call_id, device_id, recording_id, stage, outcome)
    matching_ids = matching.with_only_columns(RecordingAudit.id)
    counts = select(
        RecordingAudit.call_id.label("call_id"), func.count().label("event_count"),
        func.sum(case((RecordingAudit.outcome == "failed", 1), else_=0)).label("failure_count"),
        func.max(RecordingAudit.id).label("last_event_id"),
    ).where(RecordingAudit.id.in_(matching_ids), RecordingAudit.call_id.is_not(None))\
        .group_by(RecordingAudit.call_id).subquery()
    query = select(Call, ERPNextSync.status, MobileRecording.device_id, MobileRecording.recording_id,
                   counts.c.event_count, counts.c.failure_count,
                   RecordingAudit.created_at, RecordingAudit.event, RecordingAudit.outcome)\
        .join(counts, counts.c.call_id == Call.id)\
        .join(RecordingAudit, RecordingAudit.id == counts.c.last_event_id)\
        .outerjoin(ERPNextSync, ERPNextSync.call_id == Call.id)\
        .outerjoin(MobileRecording, MobileRecording.call_id == Call.id)
    if before_call_id is not None:
        query = query.where(Call.id < before_call_id)
    query = query.options(load_only(Call.id, Call.status, Call.call_summary))
    rows = (await db.execute(query.order_by(Call.id.desc()).limit(limit + 1))).all()
    unassigned = await db.scalar(select(func.count()).select_from(RecordingAudit).where(
        RecordingAudit.id.in_(matching_ids), RecordingAudit.call_id.is_(None)))
    items = [{"call_id": call.id, "status": call.status, "summary": call.call_summary,
              "crm_status": crm_status, "device_id": device, "recording_id": recording,
              "event_count": count, "failure_count": failures, "last_event_at": timestamp,
              "last_event": event, "last_outcome": last_outcome}
             for call, crm_status, device, recording, count, failures, timestamp, event, last_outcome in rows[:limit]]
    return redact({"items": items, "unassigned_count": unassigned,
                   "next_before_call_id": items[-1]["call_id"] if len(rows) > limit else None})


@router.get("")
async def history(response: Response, call_id: int | None = Query(None, ge=1), device_id: str | None = None,
                  recording_id: str | None = None, stage: str | None = None,
                  outcome: str | None = None, before_id: int | None = Query(None, ge=1),
                  limit: int = Query(50, ge=1, le=100), unassigned: bool = False, db=Depends(get_db)):
    no_cache(response)
    query = filtered_history(call_id, device_id, recording_id, stage, outcome).options(defer(RecordingAudit.details))
    if unassigned:
        query = query.where(RecordingAudit.call_id.is_(None))
    if before_id is not None:
        query = query.where(RecordingAudit.id < before_id)
    rows = (await db.execute(query.order_by(RecordingAudit.id.desc()).limit(limit + 1))).scalars().all()
    return {"items": [summary(row) for row in rows[:limit]],
            "next_before_id": rows[limit - 1].id if len(rows) > limit else None}


@router.get("/events/{event_id}")
async def event_detail(event_id: int, response: Response, db=Depends(get_db)):
    no_cache(response)
    row = await db.get(RecordingAudit, event_id)
    if row is None:
        raise HTTPException(404, "Audit event not found")
    return {**summary(row), "details": redact(row.details)}


@router.get("/calls/{call_id}")
async def call_snapshot(call_id: int, response: Response, db=Depends(get_db)):
    """Existing data remains inspectable even for calls predating audit logging."""
    no_cache(response)
    call = await db.get(Call, call_id)
    if call is None:
        raise HTTPException(404, "Call not found")
    mobile = (await db.execute(select(MobileRecording).where(MobileRecording.call_id == call_id))).scalar_one_or_none()
    sync = await db.get(ERPNextSync, call_id)
    return redact({"call_id": call_id, "analysis": analysis_snapshot(call),
                   "mobile_metadata": mobile.metadata_json if mobile else None,
                   "mobile_receipt": {"device_id": mobile.device_id, "recording_id": mobile.recording_id,
                       "sha256": mobile.sha256, "received_at": mobile.received_at,
                       "dispatch_state": mobile.dispatch_state} if mobile else None,
                   "crm_sync": {name: getattr(sync, name) for name in (
                       "status", "attempt_count", "last_error", "last_attempt_at", "last_success_at", "next_retry_at",
                   )} if sync else None,
                   "history_note": "Snapshots show current persisted data; event history starts when audit logging is installed."})
