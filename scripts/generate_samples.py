"""Generate synthetic sample invoices for demos and manual testing.

The generated PDFs contain no real company or personal data.

Usage:
    .\\venv\\Scripts\\python.exe scripts\\generate_samples.py
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DIR = PROJECT_ROOT / "sample_data"

INVOICE_LINES = [
    "TAX INVOICE",
    "ABC Technologies Pvt Ltd",
    "12 MG Road, Bengaluru, Karnataka 560001",
    "GSTIN: 29ABCDE1234F1Z5",
    "",
    "Invoice No: INV-2026-0042",
    "Invoice Date: 2026-04-01",
    "Due Date: 2026-04-30",
    "Currency: INR",
    "",
    "Bill To:",
    "XYZ Retail Solutions",
    "45 Park Street, Kolkata, West Bengal 700016",
    "GSTIN: 19XYZAB5678C1Z2",
    "",
    "Description                    HSN      Qty   Unit Price   Tax %    Amount",
    "Cloud Hosting - April 2026     998315   2     15000.00     18       30000.00",
    "Support Services               998313   10    2500.00      18       25000.00",
    "",
    "Subtotal: 55000.00",
    "CGST: 4950.00",
    "SGST: 4950.00",
    "Total Tax: 9900.00",
    "Invoice Total: 64900.00",
    "",
    "Bank: HDFC Bank, A/c 1234567890, IFSC HDFC0001234",
]


def _find_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path(r"C:\Windows\Fonts\calibri.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default(size=size)


def build_digital_pdf(destination: Path) -> None:
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)  # A4

    y = 50
    for line in INVOICE_LINES:
        if line:
            page.insert_text((50, y), line, fontsize=10, fontname="helv")
        y += 18

    document.set_metadata({"title": "Synthetic digital invoice"})
    document.save(destination)
    document.close()


def build_scanned_pdf(destination: Path) -> None:
    image = Image.new("RGB", (1240, 1754), "white")  # A4 at ~150 DPI
    draw = ImageDraw.Draw(image)
    font = _find_font(26)
    small = _find_font(22)

    y = 70
    for line in INVOICE_LINES:
        if line:
            draw.text((70, y), line, fill="black", font=font if line == "TAX INVOICE" else small)
        y += 42

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    png_bytes = buffer.getvalue()

    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_image(pymupdf.Rect(0, 0, 595, 842), stream=png_bytes)
    document.set_metadata({"title": "Synthetic scanned invoice"})
    document.save(destination)
    document.close()


def main() -> int:
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    digital = SAMPLE_DIR / "sample_digital_invoice.pdf"
    scanned = SAMPLE_DIR / "sample_scanned_invoice.pdf"

    build_digital_pdf(digital)
    build_scanned_pdf(scanned)

    print(f"Created {digital}")
    print(f"Created {scanned}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
