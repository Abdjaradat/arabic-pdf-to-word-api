from __future__ import annotations

import io
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from app.config import settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)

_paddle_ocr = None
_tesseract_available: bool | None = None


def _get_paddle_ocr():
    global _paddle_ocr
    if _paddle_ocr is None and settings.ocr.paddleocr_enabled:
        try:
            from paddleocr import PaddleOCR

            _paddle_ocr = PaddleOCR(
                use_angle_cls=True,
                lang="arabic",
                use_gpu=False,
                show_log=False,
            )
            logger.info("PaddleOCR initialized successfully")
        except ImportError:
            logger.warning("PaddleOCR not available, will use Tesseract fallback")
            _paddle_ocr = False
        except Exception as e:
            logger.warning("Failed to initialize PaddleOCR: %s", str(e))
            _paddle_ocr = False
    return _paddle_ocr if _paddle_ocr else None


def _is_tesseract_available() -> bool:
    global _tesseract_available
    if _tesseract_available is not None:
        return _tesseract_available

    if settings.ocr.tesseract_cmd:
        tesseract_path = settings.ocr.tesseract_cmd
        if os.path.exists(tesseract_path):
            _tesseract_available = True
            return True

    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        _tesseract_available = True
        return True
    except Exception:
        _tesseract_available = False
        return False


def enhance_image(image: Image.Image | np.ndarray) -> np.ndarray:
    if isinstance(image, Image.Image):
        img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    else:
        img = image.copy()

    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img

    denoised = cv2.fastNlMeansDenoising(gray, h=30)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    contrasted = clahe.apply(denoised)

    _, threshold = cv2.threshold(contrasted, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    coords = np.column_stack(np.where(threshold > 0))
    if len(coords) > 0:
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = 90 + angle
        if abs(angle) > 1.0:
            (h, w) = threshold.shape[:2]
            center = (w // 2, h // 2)
            matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
            threshold = cv2.warpAffine(
                threshold,
                matrix,
                (w, h),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE,
            )

    kernel = np.ones((1, 1), np.uint8)
    cleaned = cv2.morphologyEx(threshold, cv2.MORPH_CLOSE, kernel)

    return cv2.cvtColor(cleaned, cv2.COLOR_GRAY2RGB)


def detect_arabic_regions(image: Image.Image | np.ndarray) -> list[dict[str, Any]]:
    if isinstance(image, Image.Image):
        img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    else:
        img = image.copy()

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
    horizontal_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel)

    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40))
    vertical_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel)

    text_mask = binary - horizontal_lines - vertical_lines
    text_mask = cv2.morphologyEx(text_mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))

    contours, _ = cv2.findContours(text_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    regions = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        if area > 100 and w > 20 and h > 8:
            regions.append(
                {
                    "x": int(x),
                    "y": int(y),
                    "width": int(w),
                    "height": int(h),
                    "area": int(area),
                }
            )

    regions.sort(key=lambda r: (r["y"], r["x"]))
    return regions


def post_process_arabic(text: str) -> str:
    if not text:
        return text

    replacements = {
        r"\b(\w)l(\w)": r"\1ل\2",
        r"(\S)l(\S)": r"\1ل\2",
        r"￿": "",
        r"￾": "",
    }

    for pattern, repl in replacements.items():
        text = re.sub(pattern, repl, text)

    text = re.sub(r"(\S)\1{2,}", r"\1\1", text)

    text = re.sub(r"\s*([\.\,\!\?\:\;\)\]\}])\s*", r"\1 ", text)
    text = re.sub(r"\s*([\(\[\{])\s*", r" \1", text)

    text = re.sub(r"\s{3,}", "  ", text)
    text = text.strip()

    return text


def perform_paddle_ocr(image: Image.Image | np.ndarray) -> str:
    ocr = _get_paddle_ocr()
    if ocr is None:
        logger.warning("PaddleOCR not available")
        return ""

    try:
        if isinstance(image, Image.Image):
            img_array = np.array(image)
            if len(img_array.shape) == 3:
                img_array = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
        else:
            img_array = image

        result = ocr.ocr(img_array, cls=True)

        if not result or not result[0]:
            return ""

        text_lines: list[str] = []
        for line in result[0]:
            if line and len(line) >= 2:
                text = line[1][0] if isinstance(line[1], (list, tuple)) else str(line[1])
                confidence = line[1][1] if isinstance(line[1], (list, tuple)) and len(line[1]) > 1 else 0
                if confidence > 0.3:
                    text_lines.append(text)

        return "\n".join(text_lines)
    except Exception as e:
        logger.error("PaddleOCR error: %s", str(e))
        return ""


def perform_tesseract_ocr(
    image: Image.Image | np.ndarray,
    lang: str = "ara",
) -> str:
    if not _is_tesseract_available():
        logger.error("Tesseract is not available")
        return ""

    try:
        import pytesseract

        if settings.ocr.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = settings.ocr.tesseract_cmd

        if isinstance(image, np.ndarray):
            pil_image = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        else:
            pil_image = image

        custom_config = r"--oem 3 --psm 6 -c preserve_interword_spaces=1"
        text = pytesseract.image_to_string(
            pil_image,
            lang=lang,
            config=custom_config,
        )

        return text.strip()
    except Exception as e:
        logger.error("Tesseract error: %s", str(e))
        return ""


def perform_ocr(
    image: Image.Image | np.ndarray,
    lang: str = "ara",
    enhance: bool = True,
) -> tuple[str, str]:
    try:
        if enhance:
            processed = enhance_image(image)
        else:
            if isinstance(image, Image.Image):
                processed = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
            else:
                processed = image

        text = perform_paddle_ocr(processed)
        ocr_engine = "paddle"

        if not text or len(text.strip()) < 10:
            tesseract_text = perform_tesseract_ocr(processed, lang=lang)
            if tesseract_text and len(tesseract_text.strip()) > len(text.strip()):
                text = tesseract_text
                ocr_engine = "tesseract"

        text = post_process_arabic(text)
        return text, ocr_engine
    except Exception as e:
        logger.error("OCR failed: %s", str(e))
        return "", "none"
