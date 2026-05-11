from __future__ import annotations

import math
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging_config import get_logger
from app.core.security import generate_secure_filename, validate_file_safety
from app.dependencies import get_current_user, get_db, validate_file
from app.models.conversion import Conversion
from app.models.user import User
from app.schemas.conversion import (
    ConversionListResponse,
    ConversionResponse,
    ConversionStats,
    ConversionStatus,
    UploadResponse,
)
from app.services.conversion_pipeline import ConversionPipeline

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/convert", tags=["conversion"])

_UPLOAD_DIR = settings.storage.upload_path


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_pdf(
    request: Request,
    file: UploadFile,
    language: str = Query("ara", regex=r"^(ara|eng|ara\+eng)$"),
    force_ocr: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    if not current_user.can_convert():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Daily conversion limit reached. Upgrade to premium for unlimited conversions.",
        )

    safe_name, ext = await validate_file(
        filename=file.filename or "document.pdf",
        content_type=file.content_type,
        file_size=None,
    )

    file_path = _UPLOAD_DIR / safe_name

    content = await file.read()
    if len(content) > settings.storage.max_file_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum size of {settings.storage.max_file_size_mb} MB",
        )

    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    with open(file_path, "wb") as f:
        f.write(content)

    if not validate_file_safety(file_path):
        file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File failed safety validation. Only valid PDF files are allowed.",
        )

    conversion = Conversion(
        user_id=current_user.id,
        original_filename=file.filename or safe_name,
        original_size=len(content),
        status="pending",
        language=language,
        file_path=str(file_path),
    )
    db.add(conversion)
    await db.flush()

    current_user.increment_conversion()
    db.add(current_user)
    await db.flush()

    logger.info(
        "File uploaded: user=%s, file=%s, size=%d",
        current_user.email,
        safe_name,
        len(content),
    )

    try:
        pipeline = ConversionPipeline(
            file_path=file_path,
            conversion_id=conversion.id,
            language=language,
            force_ocr=force_ocr,
        )
        result = pipeline.run()

        conversion.mark_completed(
            output_path=result["output_path"],
            output_size=result["output_size"],
        )
        conversion.page_count = result["page_count"]
        conversion.ocr_used = result["ocr_used"]
        conversion.ocr_engine = result.get("ocr_engine")
        db.add(conversion)
        await db.flush()

        logger.info("Conversion completed: id=%s", conversion.id)
    except Exception as e:
        conversion.mark_failed(str(e))
        db.add(conversion)
        await db.flush()
        logger.error("Conversion failed: id=%s, error=%s", conversion.id, str(e))

        return UploadResponse(
            conversion_id=conversion.id,
            filename=file.filename or safe_name,
            size=len(content),
            status="failed",
            message=f"Conversion failed: {str(e)}",
        )

    return UploadResponse(
        conversion_id=conversion.id,
        filename=file.filename or safe_name,
        size=len(content),
        status="completed",
        message="File uploaded and converted successfully.",
    )


@router.get("/status/{conversion_id}", response_model=ConversionStatus)
async def get_conversion_status(
    conversion_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversionStatus:
    result = await db.execute(
        select(Conversion).where(
            Conversion.id == conversion_id,
            Conversion.user_id == current_user.id,
        )
    )
    conversion = result.scalar_one_or_none()

    if not conversion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversion not found",
        )

    return ConversionStatus(
        id=conversion.id,
        status=conversion.status,
        progress=conversion.progress,
        page_count=conversion.page_count,
        ocr_used=conversion.ocr_used,
        error_message=conversion.error_message,
    )


@router.get("/download/{conversion_id}")
async def download_conversion(
    conversion_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(Conversion).where(
            Conversion.id == conversion_id,
            Conversion.user_id == current_user.id,
        )
    )
    conversion = result.scalar_one_or_none()

    if not conversion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversion not found",
        )

    if conversion.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Conversion is not completed yet. Current status: {conversion.status}",
        )

    if not conversion.output_path or not Path(conversion.output_path).exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Output file not found on disk",
        )

    from fastapi.responses import FileResponse

    output_path = Path(conversion.output_path)
    original_stem = Path(conversion.original_filename).stem
    download_name = f"{original_stem}.docx"

    return FileResponse(
        path=str(output_path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=download_name,
        headers={
            "Content-Disposition": f'attachment; filename="{download_name}"',
        },
    )


@router.delete("/{conversion_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversion(
    conversion_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(Conversion).where(
            Conversion.id == conversion_id,
            Conversion.user_id == current_user.id,
        )
    )
    conversion = result.scalar_one_or_none()

    if not conversion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversion not found",
        )

    if conversion.file_path:
        Path(conversion.file_path).unlink(missing_ok=True)
    if conversion.output_path:
        Path(conversion.output_path).unlink(missing_ok=True)

    await db.delete(conversion)
    await db.flush()

    logger.info("Conversion deleted: id=%s", conversion_id)


@router.get("/history", response_model=ConversionListResponse)
async def get_conversion_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversionListResponse:
    offset = (page - 1) * page_size

    count_result = await db.execute(
        select(func.count(Conversion.id)).where(Conversion.user_id == current_user.id)
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        select(Conversion)
        .where(Conversion.user_id == current_user.id)
        .order_by(Conversion.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    conversions = result.scalars().all()

    total_pages = max(1, math.ceil(total / page_size))

    return ConversionListResponse(
        items=[ConversionResponse.model_validate(c) for c in conversions],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/stats", response_model=ConversionStats)
async def get_conversion_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversionStats:
    total_result = await db.execute(
        select(func.count(Conversion.id)).where(Conversion.user_id == current_user.id)
    )
    total = total_result.scalar() or 0

    success_result = await db.execute(
        select(func.count(Conversion.id)).where(
            Conversion.user_id == current_user.id,
            Conversion.status == "completed",
        )
    )
    successful = success_result.scalar() or 0

    failed_result = await db.execute(
        select(func.count(Conversion.id)).where(
            Conversion.user_id == current_user.id,
            Conversion.status == "failed",
        )
    )
    failed = failed_result.scalar() or 0

    pages_result = await db.execute(
        select(func.coalesce(func.sum(Conversion.page_count), 0)).where(
            Conversion.user_id == current_user.id,
            Conversion.status == "completed",
        )
    )
    total_pages = pages_result.scalar() or 0

    ocr_result = await db.execute(
        select(func.count(Conversion.id)).where(
            Conversion.user_id == current_user.id,
            Conversion.ocr_used == True,
        )
    )
    ocr_count = ocr_result.scalar() or 0

    avg_duration_result = await db.execute(
        select(func.avg(
            func.extract("epoch", Conversion.completed_at - Conversion.created_at)
        )).where(
            Conversion.user_id == current_user.id,
            Conversion.status == "completed",
            Conversion.completed_at.isnot(None),
        )
    )
    avg_duration = avg_duration_result.scalar()

    input_size_result = await db.execute(
        select(func.coalesce(func.sum(Conversion.original_size), 0)).where(
            Conversion.user_id == current_user.id,
            Conversion.status == "completed",
        )
    )
    input_size = input_size_result.scalar() or 0

    output_size_result = await db.execute(
        select(func.coalesce(func.sum(Conversion.output_size), 0)).where(
            Conversion.user_id == current_user.id,
            Conversion.status == "completed",
        )
    )
    output_size = output_size_result.scalar() or 0

    ocr_percentage = (ocr_count / total * 100) if total > 0 else 0.0
    size_saved = max(0, input_size - output_size)

    return ConversionStats(
        total_conversions=total,
        successful_conversions=successful,
        failed_conversions=failed,
        total_pages_processed=total_pages,
        total_size_saved=size_saved,
        average_duration_seconds=avg_duration,
        ocr_percentage=round(ocr_percentage, 2),
    )
