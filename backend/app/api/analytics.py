from fastapi import APIRouter, Depends
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.call import Call
from app.models.caller import Caller

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])

@router.get("/summary")
async def summary(db: AsyncSession = Depends(get_db)):
    total = await db.scalar(select(func.count(Call.id))) or 0
    completed = await db.scalar(select(func.count(Call.id)).where(Call.status == "completed")) or 0
    processing = await db.scalar(select(func.count(Call.id)).where(Call.status.in_(["queued", "processing"]))) or 0
    failed = await db.scalar(select(func.count(Call.id)).where(Call.status == "failed")) or 0
    avg_score = await db.scalar(select(func.avg(Call.agent_performance_score)).where(Call.status == "completed"))
    interest_rows = (await db.execute(select(Call.customer_interest_level, func.count(Call.id))
                    .where(Call.status == "completed").group_by(Call.customer_interest_level))).all()
    caller_rows = (await db.execute(
        select(Caller.name, func.count(Call.id).label("calls"),
               func.avg(Call.agent_performance_score).label("avg_score"))
        .join(Call, Call.caller_id == Caller.id).where(Call.status == "completed")
        .group_by(Caller.id, Caller.name).order_by(func.count(Call.id).desc()).limit(10)
    )).all()
    return {
        "total_calls": total, "completed_calls": completed, "processing_calls": processing,
        "failed_calls": failed, "average_agent_score": round(float(avg_score), 1) if avg_score is not None else None,
        "interest_breakdown": {str(k or "Unknown"): v for k, v in interest_rows},
        "caller_performance": [{"caller_name": r.name, "calls": r.calls,
                                "average_score": round(float(r.avg_score), 1) if r.avg_score is not None else None}
                               for r in caller_rows]
    }
