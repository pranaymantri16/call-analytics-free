from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class RecordingAudit(Base):
    """Append-only recording history. Payloads are only exposed to administrators."""
    __tablename__ = "recording_audit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    call_id: Mapped[int | None] = mapped_column(ForeignKey("calls.id"), index=True)
    device_id: Mapped[str | None] = mapped_column(String(128), index=True)
    recording_id: Mapped[str | None] = mapped_column(String(128), index=True)
    correlation_id: Mapped[str] = mapped_column(String(36), index=True)
    stage: Mapped[str] = mapped_column(String(30), index=True)
    event: Mapped[str] = mapped_column(String(60), index=True)
    outcome: Mapped[str] = mapped_column(String(20), index=True)
    attempt: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True,
    )
