import secrets
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from app.config import settings
from app.database import get_db
from app.models import Call, ERPNextSync
from app.services.erpnext import ERPNextClient, IntegrationError
from app.services.erpnext_sync import add_pending, enqueue, now, sync_metrics


async def require_admin(authorization: str | None = Header(default=None)):
    token = settings.erpnext_admin_token.get_secret_value()
    if not token:
        raise HTTPException(503, "ERPNext admin authentication is not configured")
    if authorization is None or not secrets.compare_digest(
        authorization.encode("utf8"), ("Bearer " + token).encode("utf8"),
    ):
        raise HTTPException(401, "Invalid admin credentials", headers={"WWW-Authenticate": "Bearer"})


router = APIRouter(prefix="/api/v1/integrations/erpnext", tags=["erpnext"],
                   dependencies=[Depends(require_admin)])


@router.get("/status")
async def status(check_connectivity: bool = False, db=Depends(get_db)):
    result = {"enabled": settings.erpnext_enabled, "metrics": await sync_metrics(db)}
    if check_connectivity and settings.erpnext_enabled:
        try:
            result["connectivity"] = await ERPNextClient(settings).health()
        except IntegrationError as exc:
            result["connectivity"] = {"reachable": False, "error_code": exc.code}
    return result


@router.get("/calls/{call_id}")
async def call_status(call_id: int, db=Depends(get_db)):
    if await db.get(Call, call_id) is None:
        raise HTTPException(404, "Call not found")
    row = await db.get(ERPNextSync, call_id)
    if row is None:
        return {"call_id": call_id, "status": "not_queued"}
    return {"call_id": row.call_id, "status": row.status, "attempt_count": row.attempt_count,
            "last_attempt_at": row.last_attempt_at, "last_error": row.last_error,
            "last_success_at": row.last_success_at, "next_retry_at": row.next_retry_at,
            "http_category": row.http_category}


@router.post("/calls/{call_id}/retry", status_code=202)
async def retry(call_id: int, db=Depends(get_db)):
    if not settings.erpnext_enabled:
        raise HTTPException(409, "ERPNext integration is disabled")
    call = await db.get(Call, call_id)
    if call is None:
        raise HTTPException(404, "Call not found")
    if call.status != "completed":
        raise HTTPException(409, "Call analysis is not completed")
    await add_pending(db, call_id)
    row = (await db.execute(select(ERPNextSync).where(ERPNextSync.call_id == call_id)
                           .with_for_update())).scalar_one()
    if row.status == "processing" and row.lease_until and row.lease_until > now():
        raise HTTPException(409, "Synchronization is already processing")
    row.status, row.attempt_count, row.last_error = "pending", 0, None
    row.next_retry_at = now()
    row.lease_until = row.lease_token = None
    await db.commit()
    enqueue(call_id)
    return {"call_id": call_id, "status": "pending"}
