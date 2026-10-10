import asyncio
from datetime import datetime, timezone
from celery import Celery
from sqlalchemy import select
from app.config import settings
from app.database import AsyncSessionLocal, engine
from app.models import Call
from app.services.stt_service import transcribe_and_diarize
from app.services.llm_service import summarize_call

celery_app = Celery("call_analytics", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(task_serializer="json", result_serializer="json",
                       accept_content=["json"], task_track_started=True)

@celery_app.task(name="process_call", autoretry_for=(ConnectionError,), retry_backoff=True, max_retries=2)
def process_call(call_id: int):
    asyncio.run(_process_call_async(call_id))

async def _process_call_async(call_id: int):
    try:
        async with AsyncSessionLocal() as db:
            call = await db.get(Call, call_id)
            if not call:
                return
            call.status = "processing"
            call.error_message = None
            await db.commit()
            try:
                stt = await asyncio.to_thread(transcribe_and_diarize, call.audio_path)
                summary = await summarize_call(stt["transcript"])
                call.transcript = stt["transcript"]
                call.segments = stt["segments"]
                call.duration_seconds = stt["duration_seconds"]
                call.call_summary = summary["call_summary"]
                call.customer_interest_level = summary["customer_interest_level"]
                call.key_topics = summary["key_topics"]
                call.action_items = summary["action_items"]
                call.agent_performance_score = summary["agent_performance_score"]
                call.status = "completed"
                call.processed_at = datetime.now(timezone.utc)
            except Exception as exc:
                call.status = "failed"
                call.error_message = str(exc)[:4000]
            await db.commit()
    finally:
        # Celery uses a new event loop per task; dispose so the next task
        # does not reuse asyncpg connections bound to a closed loop.
        await engine.dispose()
