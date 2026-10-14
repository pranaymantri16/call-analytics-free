"""Prevent concurrent/replayed analysis tasks using a PostgreSQL session lock."""
from contextlib import asynccontextmanager
from sqlalchemy import text


@asynccontextmanager
async def processing_guard(engine, call_id):
    if engine.dialect.name != "postgresql":
        # SQLite is used only by the isolated test harness.
        yield True
        return
    async with engine.connect() as connection:
        acquired = bool(await connection.scalar(text("SELECT pg_try_advisory_lock(1128352844, :call_id)"), {"call_id": call_id}))
        await connection.commit()  # Session lock survives commit; avoid an idle transaction during STT.
        try:
            yield acquired
        finally:
            if acquired:
                await connection.execute(text("SELECT pg_advisory_unlock(1128352844, :call_id)"), {"call_id": call_id})
                await connection.commit()
