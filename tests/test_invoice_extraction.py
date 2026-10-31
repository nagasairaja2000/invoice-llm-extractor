"""Tests for the two invoice extraction pipelines."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.exceptions import ExtractionParseError, GeminiServiceError, OcrUnavailableError
from app.schemas.invoice import InvoiceData
from app.services import invoice_service
from app.services.invoice_service import (
    APPROACH_DIGITAL,
    APPROACH_OCR,
    APPROACH_VISION,
    APPROACH_VISION_FALLBACK,
    extract_approach_1,
    extract_approach_2,
)
from tests.helpers import FakeGeminiClient, invoice_json


def test_approach_2_digital_uses_embedded_text(settings, digital_pdf: Path):
    client = FakeGeminiClient()

    result = extract_approach_2(digital_pdf, client, settings)

    assert result["pdf_type"] == "Digital"
    assert result["approach"] == APPROACH_DIGITAL
    assert result["upload_time"] is None
    assert result["ocr_time"] is None
    assert result["text_extraction_time"] is not None
    assert result["invoice"]["invoice_total"] == 64900.0
    assert result["invoice"]["currency"] == "INR"
    assert len(result["invoice"]["line_items"]) == 2
    assert len(result["invoice"]["items_purchased"]) == 2
    assert "Cloud Hosting" in result["invoice"]["items_purchased"][0]
    assert client.uploaded_paths == []
    assert client.generate_calls
    assert "INVOICE PAGE 1" in client.generate_calls[0]


def test_approach_1_uses_gemini_vision(settings, digital_pdf: Path):
    client = FakeGeminiClient()

    result = extract_approach_1(digital_pdf, client, settings)

    assert result["approach"] == APPROACH_VISION
    assert result["pdf_type"] == "Digital"
    assert result["upload_time"] is not None
    assert result["text_extraction_time"] is None
    assert result["invoice"]["invoice_number"] == "INV-2026-0042"
    assert client.uploaded_paths == [digital_pdf]
    assert client.deleted_files == ["files/fake-upload"]


def test_approach_1_deletes_upload_when_generation_fails(settings, digital_pdf: Path):
    client = FakeGeminiClient(error=GeminiServiceError("boom"))

    with pytest.raises(GeminiServiceError):
        extract_approach_1(digital_pdf, client, settings)

    assert client.deleted_files == ["files/fake-upload"]


def test_approach_2_scanned_uses_ocr(monkeypatch, settings, scanned_pdf: Path):
    monkeypatch.setattr(
        invoice_service,
        "ocr_pdf_pages",
        lambda path, pages, s: (
            {1: "TAX INVOICE from OCR\nInvoice No: INV-001\nTotal: 100.00"},
            0.25,
        ),
    )
    client = FakeGeminiClient()

    result = extract_approach_2(scanned_pdf, client, settings)

    assert result["pdf_type"] == "Scanned"
    assert result["approach"] == APPROACH_OCR
    assert result["ocr_time"] == 0.25
    assert client.uploaded_paths == []
    assert "TAX INVOICE from OCR" in client.generate_calls[0]


def test_approach_2_scanned_falls_back_to_vision(monkeypatch, settings, scanned_pdf: Path):
    def _unavailable(*args, **kwargs):
        raise OcrUnavailableError()

    monkeypatch.setattr(invoice_service, "ocr_pdf_pages", _unavailable)
    client = FakeGeminiClient()

    result = extract_approach_2(scanned_pdf, client, settings)

    assert result["approach"] == APPROACH_VISION_FALLBACK
    assert result["upload_time"] is not None
    assert client.uploaded_paths == [scanned_pdf]
    assert client.deleted_files


def test_approach_2_mixed_pdf_combines_text_and_ocr(monkeypatch, settings, mixed_pdf: Path):
    monkeypatch.setattr(
        invoice_service,
        "ocr_pdf_pages",
        lambda path, pages, s: (
            {2: "TAX INVOICE page two\nInvoice No: INV-002\nTotal: 200.00"},
            0.1,
        ),
    )
    client = FakeGeminiClient()

    result = extract_approach_2(mixed_pdf, client, settings)

    assert result["pdf_type"] == "Mixed"
    assert result["approach"] == "PyMuPDF + OCR + Gemini Text"
    prompt = client.generate_calls[0]
    assert "INVOICE PAGE 1" in prompt
    assert "TAX INVOICE page two" in prompt


def test_invalid_json_raises(settings, digital_pdf: Path):
    client = FakeGeminiClient(text="this is not json")

    with pytest.raises(ExtractionParseError):
        extract_approach_2(digital_pdf, client, settings)


def test_gemini_failure_propagates(settings, digital_pdf: Path):
    client = FakeGeminiClient(error=GeminiServiceError("quota"))

    with pytest.raises(GeminiServiceError):
        extract_approach_2(digital_pdf, client, settings)


def test_missing_values_stay_null(settings, digital_pdf: Path):
    client = FakeGeminiClient(
        text=invoice_json(invoice_total=None, cgst=None, bank_details=None, due_date=None)
    )

    invoice = extract_approach_2(digital_pdf, client, settings)["invoice"]

    assert invoice["invoice_total"] is None
    assert invoice["cgst"] is None
    assert invoice["bank_details"] is None
    assert invoice["due_date"] is None


def test_alias_keys_are_normalised(settings, digital_pdf: Path):
    payload = {
        "vendor_name": "Vendor Ltd",
        "grand_total": "₹ 1,180.00",
        "items": [{"item": "Widget", "qty": "2", "rate": "500", "total": "1180"}],
    }
    client = FakeGeminiClient(text=json.dumps(payload))

    result = extract_approach_2(digital_pdf, client, settings)

    assert result["invoice"]["supplier_name"] == "Vendor Ltd"
    assert result["invoice"]["invoice_total"] == 1180.0
    assert result["invoice"]["line_items"][0]["description"] == "Widget"
    assert result["invoice"]["line_items"][0]["quantity"] == 2.0
    assert result["invoice"]["items_purchased"]


def test_empty_model_response_gives_all_nulls(settings, digital_pdf: Path):
    client = FakeGeminiClient(text="{}")

    invoice = extract_approach_2(digital_pdf, client, settings)["invoice"]

    assert invoice["supplier_name"] is None
    assert invoice["invoice_total"] is None
    assert invoice["line_items"] == []
    assert invoice["items_purchased"] == []


def test_result_envelope_has_consistent_keys(settings, digital_pdf: Path):
    result = extract_approach_2(digital_pdf, FakeGeminiClient(), settings)

    expected = {
        "invoice",
        "pdf_type",
        "approach",
        "page_count",
        "upload_time",
        "text_extraction_time",
        "ocr_time",
        "gemini_time",
        "total_time",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "model",
    }
    assert set(result) == expected
    assert set(result["invoice"]) == set(InvoiceData.model_fields)
    assert result["total_tokens"] == 1520
