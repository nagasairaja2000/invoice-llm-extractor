"""PDF validation, classification and text extraction using PyMuPDF."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.config import Settings
from app.exceptions import (
    CorruptPdfError,
    PasswordProtectedPdfError,
    PdfError,
    PdfLimitError,
)

logger = logging.getLogger(__name__)

DIGITAL = "Digital"
SCANNED = "Scanned"
MIXED = "Mixed"


@dataclass(frozen=True)
class PageInfo:
    number: int
    text: str
    char_count: int
    has_text: bool


@dataclass(frozen=True)
class PdfAnalysis:
    pdf_type: str
    page_count: int
    pages: tuple[PageInfo, ...]
    text: str
    text_extraction_seconds: float

    @property
    def pages_without_text(self) -> list[int]:
        return [page.number for page in self.pages if not page.has_text]


def _open_pdf(file_path: Path | str) -> pymupdf.Document:
    try:
        document = pymupdf.open(file_path)
    except Exception as exc:  # PyMuPDF raises several low-level error types
        raise CorruptPdfError(f"Could not open PDF: {exc}") from exc

    if not document.is_pdf:
        document.close()
        raise CorruptPdfError("The uploaded file is not a PDF document.")
    if document.needs_pass:
        document.close()
        raise PasswordProtectedPdfError("The PDF is password-protected.")
    if document.page_count == 0:
        document.close()
        raise PdfError("The PDF contains no pages.")
    return document


def analyze_pdf(file_path: Path | str, settings: Settings) -> PdfAnalysis:
    """Open a PDF once and classify every page.

    A page counts as "digital" when it contains at least
    ``settings.min_chars_per_page`` characters of embedded text. Pages that
    fail this check are candidates for OCR.
    """
    started = time.perf_counter()
    document = _open_pdf(file_path)

    try:
        page_count = document.page_count
        if page_count > settings.max_pdf_pages:
            raise PdfLimitError(
                f"PDF has {page_count} pages; limit is {settings.max_pdf_pages}.",
                public_message=(
                    f"The PDF has {page_count} pages. "
                    f"Maximum allowed is {settings.max_pdf_pages}."
                ),
            )

        pages: list[PageInfo] = []
        parts: list[str] = []
        for index in range(page_count):
            page = document.load_page(index)
            text = page.get_text("text").strip()
            has_text = len(text) >= settings.min_chars_per_page
            pages.append(
                PageInfo(
                    number=index + 1,
                    text=text if has_text else "",
                    char_count=len(text),
                    has_text=has_text,
                )
            )
            if has_text:
                parts.append(f"--- Page {index + 1} ---\n{text}")
    except PdfError:
        raise
    except Exception as exc:
        raise CorruptPdfError(f"Failed to read PDF pages: {exc}") from exc
    finally:
        document.close()

    text = "\n\n".join(parts)
    if len(text) > settings.max_text_chars:
        logger.warning(
            "Extracted text is %s chars; truncating to %s chars.",
            len(text),
            settings.max_text_chars,
        )
        text = text[: settings.max_text_chars] + "\n\n[Text truncated]"

    digital_pages = sum(1 for page in pages if page.has_text)
    if digital_pages == page_count:
        pdf_type = DIGITAL
    elif digital_pages == 0:
        pdf_type = SCANNED
    else:
        pdf_type = MIXED

    elapsed = round(time.perf_counter() - started, 3)
    return PdfAnalysis(
        pdf_type=pdf_type,
        page_count=page_count,
        pages=tuple(pages),
        text=text,
        text_extraction_seconds=elapsed,
    )


def build_combined_text(analysis: PdfAnalysis, ocr_text: dict[int, str]) -> str:
    """Combine embedded and OCR text in page order."""
    parts: list[str] = []
    for page in analysis.pages:
        text = page.text if page.has_text else ocr_text.get(page.number, "").strip()
        if text:
            parts.append(f"--- Page {page.number} ---\n{text}")
    combined = "\n\n".join(parts)
    return combined.strip()


def extract_text_from_pdf(file_path: Path | str, settings: Settings) -> str:
    """Return embedded text only (convenience helper for tests/tools)."""
    return analyze_pdf(file_path, settings).text
