"""Shared test helpers and fake Gemini client."""

from __future__ import annotations

import io
import json
import time
from pathlib import Path
from typing import Any

import pymupdf
from PIL import Image, ImageDraw, ImageFont

from app.services.gemini_client import GeminiResult

SAMPLE_INVOICE: dict[str, Any] = {
    "supplier_name": "ABC Technologies Pvt Ltd",
    "supplier_address": "12 MG Road, Bengaluru, Karnataka 560001",
    "supplier_gstin": "29ABCDE1234F1Z5",
    "customer_name": "XYZ Retail Solutions",
    "customer_address": "45 Park Street, Kolkata, West Bengal 700016",
    "customer_gstin": "19XYZAB5678C1Z2",
    "invoice_number": "INV-2026-0042",
    "invoice_date": "2026-04-01",
    "due_date": "2026-04-30",
    "currency": "INR",
    "subtotal": 55000.0,
    "total_tax": 9900.0,
    "cgst": 4950.0,
    "sgst": 4950.0,
    "igst": None,
    "invoice_total": 64900.0,
    "bank_details": "HDFC Bank, A/c 1234567890, IFSC HDFC0001234",
    "line_items": [
        {
            "description": "Cloud Hosting - April 2026",
            "hsn_sac": "998315",
            "quantity": 2,
            "unit_price": 15000.0,
            "tax_percentage": 18,
            "amount": 30000.0,
        },
        {
            "description": "Support Services",
            "hsn_sac": "998313",
            "quantity": 10,
            "unit_price": 2500.0,
            "tax_percentage": 18,
            "amount": 25000.0,
        },
    ],
}


def invoice_json(**overrides: Any) -> str:
    payload = dict(SAMPLE_INVOICE)
    payload.update(overrides)
    return json.dumps(payload)


class FakeUploadedFile:
    def __init__(self, name: str = "files/fake-upload"):
        self.name = name
        self.state = "ACTIVE"


class FakeGeminiClient:
    """Drop-in replacement for ``GeminiClient`` used by tests."""

    def __init__(
        self,
        text: str | None = None,
        error: Exception | None = None,
    ):
        self.text = text if text is not None else invoice_json()
        self.error = error
        self.generate_calls: list[Any] = []
        self.uploaded_paths: list[Any] = []
        self.deleted_files: list[str] = []

    def generate(self, contents: Any, schema: Any = None) -> GeminiResult:
        self.generate_calls.append(contents)
        if self.error is not None:
            raise self.error
        return GeminiResult(
            text=self.text,
            model="fake-model",
            prompt_tokens=1200,
            output_tokens=320,
            total_tokens=1520,
        )

    def upload_pdf(self, file_path: Path | str) -> tuple[FakeUploadedFile, float]:
        self.uploaded_paths.append(Path(file_path))
        return FakeUploadedFile(), 0.01

    def delete_file(self, uploaded: Any) -> None:
        self.deleted_files.append(getattr(uploaded, "name", "unknown"))


def make_digital_pdf(
    path: Path,
    pages: int = 1,
    text: str = "TAX INVOICE\nInvoice No: INV-001\nTotal: 100.00",
) -> Path:
    document = pymupdf.open()
    for index in range(pages):
        page = document.new_page(width=595, height=842)
        page.insert_text((50, 50), f"INVOICE PAGE {index + 1}", fontsize=14)
        y = 80
        for line in text.splitlines():
            page.insert_text((50, y), line, fontsize=9)
            y += 16
    document.save(str(path))
    document.close()
    return path


def _render_text_image(text: str) -> bytes:
    image = Image.new("RGB", (1000, 700), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 26)
    except OSError:
        font = ImageFont.load_default(size=26)

    y = 40
    for line in text.splitlines():
        draw.text((40, y), line, fill="black", font=font)
        y += 34

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def make_scanned_pdf(
    path: Path,
    text: str = "TAX INVOICE\nInvoice No: INV-001\nTotal: 100.00",
) -> Path:
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_image(pymupdf.Rect(0, 0, 595, 842), stream=_render_text_image(text))
    document.save(str(path))
    document.close()
    return path


def make_mixed_pdf(path: Path) -> Path:
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((50, 50), "INVOICE PAGE 1 with plenty of embedded text", fontsize=12)
    page2 = document.new_page(width=595, height=842)
    page2.insert_image(
        pymupdf.Rect(0, 0, 595, 842),
        stream=_render_text_image("SCANNED PAGE 2\nTotal: 100.00"),
    )
    document.save(str(path))
    document.close()
    return path


def make_encrypted_pdf(path: Path) -> Path:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((50, 50), "Secret invoice", fontsize=12)
    document.save(
        str(path),
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="owner-password",
        user_pw="user-password",
    )
    document.close()
    return path


def make_corrupt_pdf(path: Path) -> Path:
    path.write_bytes(b"this is definitely not a pdf file")
    return path


def make_image_file(path: Path) -> Path:
    path.write_bytes(_render_text_image("not a pdf"))
    return path


def wait_for_job(client: Any, job_id: str, timeout: float = 20.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/jobs/{job_id}")
        assert response.status_code == 200, response.text
        job = response.json()["job"]
        if job["status"] in {"COMPLETED", "FAILED"}:
            return job
        time.sleep(0.05)
    raise AssertionError(f"Job {job_id} did not finish within {timeout} seconds.")
