"""Tesseract OCR integration.

Only pages without embedded text are rasterised and OCR'd, which keeps
processing fast and avoids unnecessary OCR work.
"""

from __future__ import annotations

import functools
import logging
import os
import shutil
import time
from pathlib import Path

import pymupdf
import pytesseract
from PIL import Image, ImageOps

from app.config import Settings
from app.exceptions import OcrUnavailableError

logger = logging.getLogger(__name__)

_WINDOWS_TESSERACT_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Tesseract-OCR" / "tesseract.exe"),
)


def configure_tesseract(settings: Settings) -> None:
    """Point pytesseract at the Tesseract binary when needed."""
    if settings.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
        return
    if not settings.ocr_enabled:
        return
    if shutil.which("tesseract"):
        return
    for candidate in _WINDOWS_TESSERACT_PATHS:
        if Path(candidate).is_file():
            pytesseract.pytesseract.tesseract_cmd = candidate
            return


@functools.lru_cache(maxsize=1)
def is_tesseract_available() -> bool:
    """Return True when the Tesseract executable can be executed."""
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:  # TesseractNotFoundError, OSError, ...
        return False


def ocr_pdf_pages(
    file_path: Path | str,
    page_numbers: list[int],
    settings: Settings,
) -> tuple[dict[int, str], float]:
    """OCR the requested 1-based page numbers.

    Returns a mapping ``{page_number: text}`` and the elapsed time in seconds.

    Raises:
        OcrUnavailableError: when OCR is disabled or Tesseract is missing.
    """
    configure_tesseract(settings)
    if not settings.ocr_enabled:
        raise OcrUnavailableError("OCR is disabled in configuration.")
    if not is_tesseract_available():
        raise OcrUnavailableError()

    started = time.perf_counter()
    results: dict[int, str] = {}

    try:
        document = pymupdf.open(file_path)
    except Exception as exc:
        raise OcrUnavailableError(f"Could not open PDF for OCR: {exc}") from exc

    try:
        for page_number in page_numbers:
            page = document.load_page(page_number - 1)
            pixmap = page.get_pixmap(dpi=settings.ocr_dpi, colorspace=pymupdf.csGRAY)
            image = Image.frombytes("L", (pixmap.width, pixmap.height), pixmap.samples)
            image = ImageOps.autocontrast(image)

            try:
                text = pytesseract.image_to_string(
                    image,
                    lang=settings.ocr_languages,
                    config=f"--psm {settings.ocr_psm}",
                    timeout=settings.ocr_timeout_seconds,
                )
            except RuntimeError as exc:
                # pytesseract raises RuntimeError when the timeout is exceeded.
                logger.warning("OCR timed out on page %s: %s", page_number, exc)
                text = ""
            except pytesseract.TesseractError as exc:
                logger.warning("OCR failed on page %s: %s", page_number, exc)
                text = ""

            results[page_number] = text.strip()
            logger.debug(
                "OCR page %s: %s characters", page_number, len(results[page_number])
            )
    finally:
        document.close()

    elapsed = round(time.perf_counter() - started, 3)
    return results, elapsed
