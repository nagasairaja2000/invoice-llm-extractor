"""Tests for PDF validation, classification and text extraction."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.exceptions import (
    CorruptPdfError,
    PasswordProtectedPdfError,
    PdfLimitError,
)
from app.services.pdf_service import (
    DIGITAL,
    MIXED,
    SCANNED,
    analyze_pdf,
    build_combined_text,
    extract_text_from_pdf,
)
from tests.helpers import make_corrupt_pdf, make_image_file


def test_digital_pdf_is_classified_and_extracted(digital_pdf: Path, settings):
    analysis = analyze_pdf(digital_pdf, settings)

    assert analysis.pdf_type == DIGITAL
    assert analysis.page_count == 1
    assert "INVOICE PAGE 1" in analysis.text
    assert "--- Page 1 ---" in analysis.text
    assert analysis.pages_without_text == []
    assert analysis.text_extraction_seconds >= 0


def test_multi_page_pdf_extracts_every_page(multi_page_pdf: Path, settings):
    analysis = analyze_pdf(multi_page_pdf, settings)

    assert analysis.page_count == 3
    assert analysis.pdf_type == DIGITAL
    for page_number in (1, 2, 3):
        assert f"--- Page {page_number} ---" in analysis.text
        assert f"INVOICE PAGE {page_number}" in analysis.text


def test_scanned_pdf_is_classified(scanned_pdf: Path, settings):
    analysis = analyze_pdf(scanned_pdf, settings)

    assert analysis.pdf_type == SCANNED
    assert analysis.pages_without_text == [1]
    assert analysis.text == ""


def test_mixed_pdf_is_classified(mixed_pdf: Path, settings):
    analysis = analyze_pdf(mixed_pdf, settings)

    assert analysis.pdf_type == MIXED
    assert analysis.page_count == 2
    assert analysis.pages_without_text == [2]


def test_combined_text_uses_ocr_for_missing_pages(mixed_pdf: Path, settings):
    analysis = analyze_pdf(mixed_pdf, settings)
    combined = build_combined_text(analysis, {2: "OCR PAGE TWO TEXT"})

    assert "INVOICE PAGE 1" in combined
    assert "OCR PAGE TWO TEXT" in combined


def test_password_protected_pdf_raises(encrypted_pdf: Path, settings):
    with pytest.raises(PasswordProtectedPdfError):
        analyze_pdf(encrypted_pdf, settings)


def test_corrupt_pdf_raises(tmp_path: Path, settings):
    bad = make_corrupt_pdf(tmp_path / "bad.pdf")
    with pytest.raises(CorruptPdfError):
        analyze_pdf(bad, settings)


def test_non_pdf_file_raises(tmp_path: Path, settings):
    image = make_image_file(tmp_path / "image.png")
    with pytest.raises(CorruptPdfError):
        analyze_pdf(image, settings)


def test_page_limit_is_enforced(multi_page_pdf: Path, settings):
    limited = settings.model_copy(update={"max_pdf_pages": 1})
    with pytest.raises(PdfLimitError):
        analyze_pdf(multi_page_pdf, limited)


def test_text_is_truncated(multi_page_pdf: Path, settings):
    limited = settings.model_copy(update={"max_text_chars": 20})
    analysis = analyze_pdf(multi_page_pdf, limited)
    assert analysis.text.endswith("[Text truncated]")
    assert len(analysis.text) < 100


def test_extract_text_helper(digital_pdf: Path, settings):
    assert "INVOICE PAGE 1" in extract_text_from_pdf(digital_pdf, settings)


def test_empty_pdf_is_rejected(tmp_path: Path, settings):
    # PyMuPDF refuses to save a document with zero pages, so build a minimal
    # valid PDF header/trailer that declares an empty page tree.
    path = tmp_path / "empty.pdf"
    path.write_bytes(
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n"
        b"trailer\n<< /Size 3 /Root 1 0 R >>\n%%EOF\n"
    )

    from app.exceptions import PdfError

    with pytest.raises(PdfError):
        analyze_pdf(path, settings)
