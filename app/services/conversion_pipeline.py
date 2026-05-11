from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np
from pdf2image import convert_from_path
from PIL import Image

from app.config import settings
from app.core.logging_config import get_logger
from app.core.security import generate_secure_filename
from app.services.docx_service import create_docx
from app.services.ocr_service import detect_arabic_regions, perform_ocr
from app.services.pdf_service import (
    PDFAnalysis,
    analyze_pdf,
    extract_tables,
    extract_text_pdfplumber,
    extract_text_pymupdf,
    get_page_thumbnails,
)

logger = get_logger(__name__)

ProgressCallback = Callable[[float, str], None]


class ConversionPipeline:
    def __init__(
        self,
        file_path: str | Path,
        conversion_id: str | None = None,
        language: str = "ara",
        force_ocr: bool = False,
        progress_callback: ProgressCallback | None = None,
    ):
        self.file_path = Path(file_path)
        self.conversion_id = conversion_id or str(uuid.uuid4())
        self.language = language
        self.force_ocr = force_ocr
        self.progress_callback = progress_callback
        self.temp_dir: Path | None = None
        self.analysis: PDFAnalysis | None = None
        self.text_content: str = ""
        self.ocr_used: bool = False
        self.ocr_engine: str | None = None
        self.text_blocks: list[dict[str, Any]] = []
        self.images: list[dict[str, Any]] = []
        self.tables: list[list[list[str]]] = []

    def _update_progress(self, progress: float, message: str = "") -> None:
        logger.info("Pipeline [%s]: %.1f%% - %s", self.conversion_id, progress, message)
        if self.progress_callback:
            self.progress_callback(progress, message)

    def _setup_temp_dir(self) -> Path:
        temp_dir = Path(tempfile.mkdtemp(prefix=f"conv_{self.conversion_id}_"))
        self.temp_dir = temp_dir
        return temp_dir

    def _cleanup_temp(self) -> None:
        if self.temp_dir and self.temp_dir.exists():
            try:
                shutil.rmtree(self.temp_dir)
                logger.debug("Cleaned up temp dir: %s", self.temp_dir)
            except Exception as e:
                logger.warning("Failed to clean up temp dir: %s", str(e))

    def _step_validate(self) -> None:
        self._update_progress(5, "Validating PDF file")

        if not self.file_path.exists():
            raise FileNotFoundError(f"PDF file not found: {self.file_path}")

        file_size = self.file_path.stat().st_size
        max_size = settings.storage.max_file_size_bytes
        if file_size > max_size:
            raise ValueError(
                f"File size ({file_size / 1024 / 1024:.1f} MB) exceeds "
                f"maximum allowed size ({max_size / 1024 / 1024:.1f} MB)"
            )

        with open(self.file_path, "rb") as f:
            header = f.read(4)
        if not header.startswith(b"%PDF"):
            raise ValueError("File is not a valid PDF")

    def _step_analyze(self) -> None:
        self._update_progress(10, "Analyzing PDF structure")

        self.analysis = analyze_pdf(self.file_path)
        logger.info(
            "Analysis: pages=%d, scanned=%s, text=%s, images=%s, tables=%s",
            self.analysis.page_count,
            self.analysis.is_scanned,
            self.analysis.has_text,
            self.analysis.has_images,
            self.analysis.has_tables,
        )

    def _step_extract_text(self) -> None:
        if not self.analysis:
            raise RuntimeError("Analysis not performed")

        if self.force_ocr or self.analysis.is_scanned:
            self._update_progress(20, "Scanned PDF detected, preparing OCR")
            self.text_content = ""
            return

        self._update_progress(20, "Extracting text from PDF")

        try:
            self.text_content = extract_text_pymupdf(self.file_path, sort=True)
            if not self.text_content.strip():
                self.text_content = extract_text_pdfplumber(self.file_path)

            if self.text_content.strip():
                self._update_progress(30, f"Extracted {len(self.text_content)} characters")
            else:
                logger.info("No text extracted, will use OCR")
                self.text_content = ""
        except Exception as e:
            logger.warning("Text extraction failed: %s, falling back to OCR", str(e))
            self.text_content = ""

    def _step_ocr(self) -> None:
        if self.text_content.strip() and not self.force_ocr:
            return

        if not self.analysis:
            raise RuntimeError("Analysis not performed")

        self._update_progress(30, "Starting OCR process")

        temp_dir = self._setup_temp_dir()
        images_dir = temp_dir / "pages"
        images_dir.mkdir(parents=True, exist_ok=True)

        try:
            ocr_images = convert_from_path(
                str(self.file_path),
                dpi=300,
                output_folder=str(images_dir),
                fmt="png",
                thread_count=4,
            )
        except Exception as e:
            logger.warning("pdf2image conversion failed, trying alternate method: %s", str(e))
            ocr_images = []
            doc = __import__("fitz").open(str(self.file_path))
            for page_num in range(len(doc)):
                page = doc[page_num]
                mat = __import__("fitz").Matrix(300 / 72, 300 / 72)
                pix = page.get_pixmap(matrix=mat)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                ocr_images.append(img)
            doc.close()

        if not ocr_images:
            raise RuntimeError("Failed to convert PDF to images for OCR")

        total_pages = len(ocr_images)
        ocr_text_parts: list[str] = []

        for page_num, pil_image in enumerate(ocr_images):
            progress_base = 30.0
            progress_range = 60.0
            page_progress = progress_base + (progress_range * (page_num / total_pages))
            self._update_progress(
                page_progress,
                f"OCR processing page {page_num + 1}/{total_pages}",
            )

            try:
                page_text, engine = perform_ocr(
                    pil_image,
                    lang=self.language,
                    enhance=True,
                )

                if not self.ocr_used:
                    self.ocr_used = True
                    self.ocr_engine = engine

                if page_text.strip():
                    ocr_text_parts.append(f"\n\n--- Page {page_num + 1} ---\n\n{page_text}")

                regions = detect_arabic_regions(pil_image)
                logger.debug(
                    "Page %d: OCR chars=%d, regions=%d",
                    page_num + 1,
                    len(page_text),
                    len(regions),
                )
            except Exception as e:
                logger.error("OCR failed on page %d: %s", page_num + 1, str(e))
                ocr_text_parts.append(f"\n\n--- Page {page_num + 1} ---\n\n[OCR failed]")

        self.text_content = "\n".join(ocr_text_parts)
        self._update_progress(90, f"OCR completed: {total_pages} pages processed")

    def _step_detect_layout(self) -> None:
        self._update_progress(75, "Detecting document layout")

        if not self.text_content.strip():
            self.text_blocks = [{"type": "paragraph", "text": "[No content extracted]"}]
            return

        if self.analysis and self.analysis.has_images:
            try:
                from app.services.pdf_service import extract_images as ext_img

                self.images = ext_img(self.file_path)
            except Exception as e:
                logger.warning("Image extraction failed: %s", str(e))

        if self.analysis and self.analysis.has_tables:
            try:
                raw_tables = extract_tables(self.file_path)
                self.tables = [t["rows"] for t in raw_tables]
            except Exception as e:
                logger.warning("Table extraction failed: %s", str(e))

        lines = self.text_content.split("\n")
        current_block: dict[str, Any] = {"type": "paragraph", "text": ""}

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if current_block["text"].strip():
                    self.text_blocks.append(current_block)
                    current_block = {"type": "paragraph", "text": ""}
                continue

            if len(stripped) < 80 and not stripped.endswith(".") and not stripped.endswith("؟"):
                if current_block["text"].strip():
                    self.text_blocks.append(current_block)
                current_block = {"type": "heading", "text": stripped, "level": 1}
                self.text_blocks.append(current_block)
                current_block = {"type": "paragraph", "text": ""}
                continue

            if current_block["text"]:
                current_block["text"] += "\n" + stripped
            else:
                current_block["text"] = stripped

        if current_block["text"].strip():
            self.text_blocks.append(current_block)

        self._update_progress(
            80,
            f"Layout detected: {len(self.text_blocks)} blocks, "
            f"{len(self.images)} images, {len(self.tables)} tables",
        )

    def _step_generate_docx(self) -> Path:
        self._update_progress(85, "Generating DOCX document")

        output_filename = f"{self.conversion_id}.docx"
        output_path = settings.storage.output_path / output_filename

        font_name = "Traditional Arabic" if self.language.startswith("ara") else "Arial"

        create_docx(
            text_content=self.text_content,
            output_path=output_path,
            font_name=font_name,
            title=f"Converted Document - {self.conversion_id}",
            text_blocks=self.text_blocks,
            images=self.images if self.images else None,
            tables_data=self.tables if self.tables else None,
        )

        self._update_progress(98, "DOCX generated successfully")
        return output_path

    def run(self) -> dict[str, Any]:
        try:
            self._update_progress(0, "Starting conversion pipeline")
            self._step_validate()
            self._step_analyze()
            self._step_extract_text()
            self._step_ocr()
            self._step_detect_layout()
            output_path = self._step_generate_docx()

            self._update_progress(100, "Conversion complete")

            return {
                "conversion_id": self.conversion_id,
                "output_path": str(output_path),
                "output_size": output_path.stat().st_size if output_path.exists() else 0,
                "page_count": self.analysis.page_count if self.analysis else 0,
                "ocr_used": self.ocr_used,
                "ocr_engine": self.ocr_engine,
                "text_length": len(self.text_content),
            }
        except Exception as e:
            logger.error("Pipeline failed: %s", str(e))
            raise
        finally:
            self._cleanup_temp()
