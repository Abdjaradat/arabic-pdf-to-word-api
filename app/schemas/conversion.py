from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ConversionRequest(BaseModel):
    language: str = Field(default="ara", pattern=r"^(ara|eng|ara\+eng)$")
    force_ocr: bool = False


class ConversionResponse(BaseModel):
    id: str
    user_id: str
    original_filename: str
    original_size: int
    output_filename: str | None = None
    output_size: int | None = None
    status: str
    page_count: int | None = None
    ocr_used: bool = False
    ocr_engine: str | None = None
    error_message: str | None = None
    language: str = "ara"
    progress: float = 0.0
    created_at: datetime
    completed_at: datetime | None = None
    duration_seconds: float | None = None

    model_config = {"from_attributes": True}


class ConversionStatus(BaseModel):
    id: str
    status: str
    progress: float
    page_count: int | None = None
    ocr_used: bool = False
    error_message: str | None = None
    estimated_remaining_seconds: int | None = None


class ConversionListResponse(BaseModel):
    items: list[ConversionResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class UploadResponse(BaseModel):
    conversion_id: str
    filename: str
    size: int
    status: str = "pending"
    message: str = "File uploaded successfully. Conversion started."


class ConversionStats(BaseModel):
    total_conversions: int
    successful_conversions: int
    failed_conversions: int
    total_pages_processed: int
    total_size_saved: int
    average_duration_seconds: float | None = None
    ocr_percentage: float = 0.0


class ConversionDailyStats(BaseModel):
    date: str
    count: int
    successful: int
    failed: int
