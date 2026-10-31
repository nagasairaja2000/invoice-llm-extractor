"""Invoice extraction pipelines for both UI approaches."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.config import Settings
from app.exceptions import ExtractionParseError, OcrUnavailableError
from app.schemas.invoice import ExtractedInvoice, InvoiceData
from app.services.gemini_client import GeminiClient, GeminiResult
from app.services.ocr_service import ocr_pdf_pages
from app.services.pdf_service import (
    SCANNED,
    PdfAnalysis,
    analyze_pdf,
    build_combined_text,
)
from app.services.prompt import INVOICE_PROMPT
from app.utils.json_parser import parse_json_object
from app.utils.normalize import normalize_invoice_payload

logger = logging.getLogger(__name__)

APPROACH_VISION = "Gemini Vision"
APPROACH_DIGITAL = "PyMuPDF + Gemini Text"
APPROACH_OCR = "Tesseract OCR + Gemini Text"
APPROACH_MIXED = "PyMuPDF + OCR + Gemini Text"
APPROACH_VISION_FALLBACK = "Gemini Vision (OCR fallback)"


def _round(value: float | None) -> float | None:
    return round(value, 3) if value is not None else None


def _finalize(
    result: GeminiResult,
    analysis: PdfAnalysis,
    approach: str,
    *,
    upload_time: float | None,
    text_extraction_time: float | None,
    ocr_time: float | None,
    gemini_time: float,
    total_time: float,
) -> dict[str, Any]:
    payload = parse_json_object(result.text)
    normalized = normalize_invoice_payload(payload)
    try:
        invoice = InvoiceData.model_validate(normalized)
    except ValidationError as exc:
        logger.warning("Invoice JSON failed validation: %s", exc)
        raise ExtractionParseError("The AI response did not match the invoice schema.") from exc

    logger.info(
        "Extraction complete: pdf_type=%s approach=%s pages=%s gemini=%.2fs total=%.2fs",
        analysis.pdf_type,
        approach,
        analysis.page_count,
        gemini_time,
        total_time,
    )

    return {
        "invoice": invoice.model_dump(mode="json"),
        "pdf_type": analysis.pdf_type,
        "approach": approach,
        "page_count": analysis.page_count,
        "upload_time": _round(upload_time),
        "text_extraction_time": _round(text_extraction_time),
        "ocr_time": _round(ocr_time),
        "gemini_time": _round(gemini_time),
        "total_time": _round(total_time),
        "input_tokens": result.prompt_tokens,
        "output_tokens": result.output_tokens,
        "total_tokens": result.total_tokens,
        "model": result.model,
    }


def _generate_from_text(
    client: GeminiClient, text: str
) -> tuple[GeminiResult, float]:
    started = time.perf_counter()
    result = client.generate(
        f"{INVOICE_PROMPT}\n\nInvoice content:\n\n{text}",
        schema=ExtractedInvoice,
    )
    return result, time.perf_counter() - started


def _generate_from_upload(
    client: GeminiClient, file_path: Path | str
) -> tuple[GeminiResult, float | None, float]:
    """Upload a PDF, generate from vision, and always delete the remote file."""
    uploaded: Any = None
    upload_time: float | None = None
    try:
        uploaded, upload_time = client.upload_pdf(file_path)
        started = time.perf_counter()
        result = client.generate(
            [uploaded, INVOICE_PROMPT],
            schema=ExtractedInvoice,
        )
        gemini_time = time.perf_counter() - started
        return result, upload_time, gemini_time
    finally:
        if uploaded is not None:
            client.delete_file(uploaded)


def extract_approach_1(
    file_path: Path | str,
    client: GeminiClient,
    settings: Settings,
) -> dict[str, Any]:
    """Approach 1: send the PDF directly to Gemini Vision."""
    started = time.perf_counter()
    analysis = analyze_pdf(file_path, settings)
    result, upload_time, gemini_time = _generate_from_upload(client, file_path)
    return _finalize(
        result,
        analysis,
        APPROACH_VISION,
        upload_time=upload_time,
        text_extraction_time=None,
        ocr_time=None,
        gemini_time=gemini_time,
        total_time=time.perf_counter() - started,
    )


def extract_approach_2(
    file_path: Path | str,
    client: GeminiClient,
    settings: Settings,
) -> dict[str, Any]:
    """Approach 2: PyMuPDF text first, Tesseract OCR for scanned pages.

    When OCR is unavailable or produces too little text, the PDF is sent to
    Gemini Vision instead so the invoice is still processed.
    """
    started = time.perf_counter()
    analysis = analyze_pdf(file_path, settings)
    text_extraction_time = analysis.text_extraction_seconds
    ocr_time: float | None = None
    upload_time: float | None = None

    text = analysis.text
    approach = APPROACH_DIGITAL
    fallback_to_vision = False

    missing_pages = analysis.pages_without_text
    if missing_pages:
        ocr_text: dict[int, str] = {}
        try:
            ocr_text, ocr_time = ocr_pdf_pages(file_path, missing_pages, settings)
        except OcrUnavailableError as exc:
            logger.warning("OCR unavailable, falling back to Gemini Vision: %s", exc)

        ocr_characters = sum(len(value) for value in ocr_text.values())
        if ocr_characters >= settings.min_ocr_chars:
            text = build_combined_text(analysis, ocr_text)
            approach = APPROACH_OCR if analysis.pdf_type == SCANNED else APPROACH_MIXED
        else:
            logger.info(
                "OCR produced %s characters for %s page(s); using Gemini Vision.",
                ocr_characters,
                len(missing_pages),
            )
            fallback_to_vision = True

    if fallback_to_vision:
        approach = APPROACH_VISION_FALLBACK
        result, upload_time, gemini_time = _generate_from_upload(client, file_path)
    else:
        result, gemini_time = _generate_from_text(client, text)

    return _finalize(
        result,
        analysis,
        approach,
        upload_time=upload_time,
        text_extraction_time=text_extraction_time,
        ocr_time=ocr_time,
        gemini_time=gemini_time,
        total_time=time.perf_counter() - started,
    )
