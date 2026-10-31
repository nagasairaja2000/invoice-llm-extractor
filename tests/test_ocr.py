"""Tests for Tesseract OCR integration."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.exceptions import OcrUnavailableError
from app.services import ocr_service
from app.services.ocr_service import (
    configure_tesseract,
    is_tesseract_available,
    ocr_pdf_pages,
)


def _require_tesseract(settings) -> None:
    """Skip the test when no Tesseract binary can be found on this machine."""
    configure_tesseract(settings)
    is_tesseract_available.cache_clear()
    if not is_tesseract_available():
        pytest.skip("Tesseract binary is not installed.")


def test_real_ocr_reads_scanned_page(scanned_pdf: Path, settings):
    _require_tesseract(settings)

    texts, elapsed = ocr_pdf_pages(scanned_pdf, [1], settings)

    assert 1 in texts
    assert "INVOICE" in texts[1].upper()
    assert elapsed >= 0


def test_ocr_uses_pytesseract(monkeypatch, scanned_pdf: Path, settings):
    monkeypatch.setattr(ocr_service, "is_tesseract_available", lambda: True)
    monkeypatch.setattr(
        ocr_service.pytesseract,
        "image_to_string",
        lambda *args, **kwargs: "MOCK OCR TEXT",
    )

    texts, elapsed = ocr_pdf_pages(scanned_pdf, [1], settings)

    assert texts == {1: "MOCK OCR TEXT"}
    assert elapsed >= 0


def test_missing_tesseract_raises(monkeypatch, scanned_pdf: Path, settings):
    monkeypatch.setattr(ocr_service, "is_tesseract_available", lambda: False)

    with pytest.raises(OcrUnavailableError):
        ocr_pdf_pages(scanned_pdf, [1], settings)


def test_disabled_ocr_raises(scanned_pdf: Path, settings):
    disabled = settings.model_copy(update={"ocr_enabled": False})

    with pytest.raises(OcrUnavailableError):
        ocr_pdf_pages(scanned_pdf, [1], disabled)


def test_ocr_timeout_is_handled(monkeypatch, scanned_pdf: Path, settings):
    monkeypatch.setattr(ocr_service, "is_tesseract_available", lambda: True)

    def _timeout(*args, **kwargs):
        raise RuntimeError("Tesseract process timeout")

    monkeypatch.setattr(ocr_service.pytesseract, "image_to_string", _timeout)

    texts, _ = ocr_pdf_pages(scanned_pdf, [1], settings)
    assert texts == {1: ""}
