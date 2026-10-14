from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class MobileRecording(Base):
    __tablename__ = "mobile_recordings"
    __table_args__ = (UniqueConstraint("device_id", "recording_id"), UniqueConstraint("device_id", "idempotency_key"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(128))
    recording_id: Mapped[str] = mapped_column(String(128))
    idempotency_key: Mapped[str] = mapped_column(String(256))
    sha256: Mapped[str] = mapped_column(String(64))
    metadata_hash: Mapped[str] = mapped_column(String(64))
    metadata_json: Mapped[dict] = mapped_column(JSON)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id"), unique=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    dispatch_state: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    dispatch_attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_dispatch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_dispatch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
