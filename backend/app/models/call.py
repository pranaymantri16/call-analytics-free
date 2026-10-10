from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class Call(Base):
    __tablename__ = "calls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_call_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    caller_id: Mapped[int] = mapped_column(ForeignKey("callers.id"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    audio_path: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    segments: Mapped[list | None] = mapped_column(JSON, nullable=True)
    call_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_interest_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    key_topics: Mapped[list | None] = mapped_column(JSON, nullable=True)
    action_items: Mapped[list | None] = mapped_column(JSON, nullable=True)
    agent_performance_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    caller = relationship("Caller", back_populates="calls")
    customer = relationship("Customer", back_populates="calls")
