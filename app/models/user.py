from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    hashed_password: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    premium_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    conversion_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    daily_conversion_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    last_conversion_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    conversions = relationship(
        "Conversion", back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def is_premium_active(self) -> bool:
        if not self.is_premium or not self.premium_until:
            return False
        return self.premium_until >= date.today()

    def can_convert(self) -> bool:
        if self.is_premium_active:
            return True
        today = date.today()
        if self.last_conversion_date != today:
            return True
        return self.daily_conversion_count < 5

    def increment_conversion(self) -> None:
        today = date.today()
        self.conversion_count += 1
        if self.last_conversion_date != today:
            self.daily_conversion_count = 1
            self.last_conversion_date = today
        else:
            self.daily_conversion_count += 1

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email})>"
