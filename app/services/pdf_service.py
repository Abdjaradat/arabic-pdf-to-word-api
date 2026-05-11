from __future__ import annotations

import io
import tempfile
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import pdfplumber
from PIL import Image

from app.core.logging_config import get_logger

logger = get_logger(__name__)


class PDFAnalysis:
    def __init__(
        self,
        page_count: int,
        file_size: int,
        is_scanned: bool,
        has_text: bool,
        has_images: bool,
        has_tables: bool,
        pages: list[dict[str, Any]],
    ):
        self.page_count = page_count
        self.file_size = file_size
        self.is_scanned = is_scanned
        self.has_text = has_text
        self.has_images = has_images
        self.has_tables = has_tables
        self.pages = pages

    @property
    def text_ratio(self) -> float:
        if not self.pages:
            return 0.0
        text_pages = sum(1 for p in self.pages if p.get("text_length", 0) > 50)
        return text_pages / len(self.pages)


def analyze_pdf(file_path: str | Path) -> PDFAnalysis:
    pdf_path = Path(file_path)
    file_size = pdf_path.stat().st_size

    doc = fitz.open(str(pdf_path))
    page_count = len(doc)

    pages_info = []
    total_text_length = 0
    has_images = False

    for page_num in range(page_count):
        page = doc[page_num]
        text = page.get_text("text")
        text_length = len(text.strip())
        total_text_length += text_length

        image_list = page.get_images()
        if image_list:
            has_images = True

        pages_info.append(
            {
                "page_num": page_num + 1,
                "text_length": text_length,
                "image_count": len(image_list),
                "width": page.rect.width,
                "height": page.rect.height,
            }
        )

    doc.close()

    has_text = total_text_length > 0

    with pdfplumber.open(str(pdf_path)) as pdf:
        tables_found = 0
        for page in pdf.pages:
            tables = page.find_tables()
            tables_found += len(tables)

    is_scanned = not has_text or (total_text_length < page_count * 20)

    return PDFAnalysis(
        page_count=page_count,
        file_size=file_size,
        is_scanned=is_scanned,
        has_text=has_text,
        has_images=has_images,
        has_tables=tables_found > 0,
        pages=pages_info,
    )


def extract_text_pdfplumber(file_path: str | Path) -> str:
    text_parts: list[str] = []

    with pdfplumber.open(str(file_path)) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            page_text = page.extract_text() or ""
            if page_text.strip():
                text_parts.append(f"\n\n--- Page {page_num} ---\n\n{page_text}")

    return "\n".join(text_parts)


def extract_text_pymupdf(file_path: str | Path, sort: bool = True) -> str:
    doc = fitz.open(str(file_path))
    text_parts: list[str] = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        blocks = page.get_text("dict", sort=sort)["blocks"]
        page_text_parts: list[str] = []

        for block in blocks:
            if block["type"] == 0:
                for line in block.get("lines", []):
                    line_text = ""
                    for span in line.get("spans", []):
                        span_text = span.get("text", "")
                        if span_text.strip():
                            flags = span.get("flags", 0)
                            if flags & 2:
                                span_text = f"**{span_text}**"
                            if flags & 16:
                                span_text = f"__{span_text}__"
                        line_text += span_text
                    if line_text.strip():
                        page_text_parts.append(line_text)
                page_text_parts.append("")

        if page_text_parts:
            text_parts.append(f"\n\n--- Page {page_num + 1} ---\n\n")
            text_parts.extend(page_text_parts)

    doc.close()
    return "\n".join(text_parts)


def extract_images(file_path: str | Path, max_size: tuple[int, int] = (1024, 1024)) -> list[dict[str, Any]]:
    doc = fitz.open(str(file_path))
    images: list[dict[str, Any]] = []
    image_counter = 0

    for page_num in range(len(doc)):
        page = doc[page_num]
        image_list = page.get_images(full=True)

        for img_index, img in enumerate(image_list):
            xref = img[0]
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            image_ext = base_image["ext"]

            image_counter += 1
            pil_image = Image.open(io.BytesIO(image_bytes))
            pil_image.thumbnail(max_size, Image.Resampling.LANCZOS)

            images.append(
                {
                    "page_num": page_num + 1,
                    "index": image_counter,
                    "width": pil_image.width,
                    "height": pil_image.height,
                    "ext": image_ext,
                    "image": pil_image,
                    "bytes": image_bytes,
                }
            )

    doc.close()
    return images


def get_page_thumbnails(
    file_path: str | Path,
    max_width: int = 200,
    max_height: int = 280,
) -> list[Image.Image]:
    doc = fitz.open(str(file_path))
    thumbnails: list[Image.Image] = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        mat = fitz.Matrix(max_width / page.rect.width, max_height / page.rect.height)
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        thumbnails.append(img)

    doc.close()
    return thumbnails


def get_pdf_metadata(file_path: str | Path) -> dict[str, Any]:
    doc = fitz.open(str(file_path))
    metadata = doc.metadata or {}
    doc.close()
    return {
        "title": metadata.get("title", ""),
        "author": metadata.get("author", ""),
        "subject": metadata.get("subject", ""),
        "keywords": metadata.get("keywords", ""),
        "creator": metadata.get("creator", ""),
        "producer": metadata.get("producer", ""),
    }


def extract_tables(file_path: str | Path) -> list[dict[str, Any]]:
    tables_data: list[dict[str, Any]] = []

    with pdfplumber.open(str(file_path)) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            tables = page.find_tables()
            for table in tables:
                rows = []
                for row in table.extract():
                    clean_row = [str(cell).strip() if cell else "" for cell in row]
                    rows.append(clean_row)

                bbox = table.bbox if hasattr(table, "bbox") else None
                tables_data.append(
                    {
                        "page_num": page_num,
                        "rows": rows,
                        "bbox": bbox,
                    }
                )

    return tables_data
