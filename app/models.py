from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.constants import JobStatus
from app.db import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    status: Mapped[str] = mapped_column(String(16), default=JobStatus.QUEUED)
    media_type: Mapped[str] = mapped_column(String(16))
    input_storage_key: Mapped[str] = mapped_column(String(255))
    normalized_audio_storage_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    result_storage_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    style_mode: Mapped[str] = mapped_column(String(16))
    style_value: Mapped[str] = mapped_column(String(80))
    input_language_hint: Mapped[str | None] = mapped_column(String(16), nullable=True)
    detected_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    duration_seconds: Mapped[float] = mapped_column(Float)
    include_raw_transcript: Mapped[bool] = mapped_column(Boolean, default=True)
    include_timestamps: Mapped[bool] = mapped_column(Boolean, default=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
