from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Conversion(Base):
    __tablename__ = "conversions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    original_size: Mapped[int] = mapped_column(Integer, nullable=False)
    output_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    output_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
    )
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ocr_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ocr_engine: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String(10), default="ara", nullable=False)
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    output_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user = relationship("User", back_populates="conversions")

    @property
    def duration_seconds(self) -> float | None:
        if self.completed_at and self.created_at:
            delta = self.completed_at - self.created_at
            return delta.total_seconds()
        return None

    def mark_completed(self, output_path: str, output_size: int) -> None:
        self.status = "completed"
        self.output_path = output_path
        self.output_size = output_size
        self.progress = 100.0
        self.completed_at = datetime.now(timezone.utc)

    def mark_failed(self, error_message: str) -> None:
        self.status = "failed"
        self.error_message = error_message
        self.completed_at = datetime.now(timezone.utc)

    def update_progress(self, progress: float) -> None:
        self.progress = min(progress, 99.0)

    def __repr__(self) -> str:
        return f"<Conversion(id={self.id}, status={self.status})>"
