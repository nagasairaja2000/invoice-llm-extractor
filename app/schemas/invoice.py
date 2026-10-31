"""Pydantic models describing the invoice JSON contract."""

from __future__ import annotations

import math
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_PLACEHOLDERS = {
    "",
    "-",
    "--",
    "—",
    "n/a",
    "na",
    "none",
    "null",
    "not available",
    "not specified",
    "unknown",
}
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
_CURRENCY_SYMBOLS = {"₹": "INR", "$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}


def clean_text(value: Any) -> str | None:
    """Normalise a free-text field; placeholders become ``None``."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).replace("\u00a0", " ").strip()
    if text.lower() in _PLACEHOLDERS:
        return None
    return text


def parse_number(value: Any) -> float | None:
    """Parse money/quantity values such as ``"₹ 1,234.50"`` into a float.

    Returns ``None`` when the value is missing or cannot be interpreted. This
    intentionally keeps unknown values as ``None`` instead of inventing data.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None

    text = str(value).replace("\u00a0", " ").strip()
    if text.lower() in _PLACEHOLDERS:
        return None

    negative = text.startswith("(") and text.endswith(")")
    text = text.replace(",", "")
    text = re.sub(r"(?i)\b(?:inr|usd|eur|gbp|jpy|rs\.?|rupees?|dollars?)\b", "", text)
    for symbol in _CURRENCY_SYMBOLS:
        text = text.replace(symbol, "")

    match = _NUMBER_RE.search(text)
    if not match:
        return None
    try:
        number = float(match.group(0))
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    return -number if negative else number


def parse_currency(value: Any) -> str | None:
    """Normalise a currency to an ISO-4217 code when possible."""
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if raw.upper() in {"RS", "RS.", "RUPEE", "RUPEES"}:
        return "INR"
    for symbol, code in _CURRENCY_SYMBOLS.items():
        if symbol in raw:
            return code
    code = raw.upper()
    if re.fullmatch(r"[A-Z]{3}", code):
        return code
    return clean_text(raw)


class LineItem(BaseModel):
    """One invoice line item."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    description: str | None = Field(
        default=None, description="Product or service description printed on the invoice."
    )
    hsn_sac: str | None = Field(default=None, description="HSN or SAC code, if printed.")
    quantity: float | None = Field(default=None, description="Quantity. Do not calculate it.")
    unit_price: float | None = Field(default=None, description="Price per unit. Do not calculate it.")
    tax_percentage: float | None = Field(
        default=None, description="Tax/GST percentage for this line, if printed."
    )
    amount: float | None = Field(
        default=None, description="Final line amount as printed. Do not calculate it."
    )

    @field_validator("description", "hsn_sac", mode="before")
    @classmethod
    def _clean_text_fields(cls, value: Any) -> str | None:
        return clean_text(value)

    @field_validator("quantity", "unit_price", "tax_percentage", "amount", mode="before")
    @classmethod
    def _parse_numeric_fields(cls, value: Any) -> float | None:
        return parse_number(value)


class ExtractedInvoice(BaseModel):
    """The exact JSON structure requested from Gemini.

    All fields are optional. A missing value must stay ``None``; the model is
    explicitly instructed not to guess.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    supplier_name: str | None = Field(
        default=None, description="Vendor/seller name that issued the invoice."
    )
    supplier_address: str | None = Field(default=None, description="Vendor/seller address.")
    supplier_gstin: str | None = Field(default=None, description="Vendor/seller GSTIN.")
    customer_name: str | None = Field(default=None, description="Buyer/customer name.")
    customer_address: str | None = Field(default=None, description="Buyer/customer address.")
    customer_gstin: str | None = Field(default=None, description="Buyer/customer GSTIN.")
    invoice_number: str | None = Field(default=None, description="Invoice number.")
    invoice_date: str | None = Field(
        default=None,
        description="Invoice date. Use YYYY-MM-DD only when unambiguous, otherwise copy as printed.",
    )
    due_date: str | None = Field(
        default=None,
        description="Payment due date. Use YYYY-MM-DD only when unambiguous.",
    )
    currency: str | None = Field(
        default=None, description="ISO 4217 currency code such as INR, USD or EUR."
    )
    subtotal: float | None = Field(
        default=None, description="Amount before tax, if printed. Do not calculate."
    )
    total_tax: float | None = Field(default=None, description="Total tax amount, if printed.")
    cgst: float | None = Field(default=None, description="CGST amount, if printed.")
    sgst: float | None = Field(default=None, description="SGST amount, if printed.")
    igst: float | None = Field(default=None, description="IGST amount, if printed.")
    invoice_total: float | None = Field(
        default=None, description="Grand total / amount payable, if printed."
    )
    bank_details: str | None = Field(
        default=None, description="Bank name, account number, IFSC or UPI, if printed."
    )
    line_items: list[LineItem] = Field(
        default_factory=list, description="One object per invoice line item."
    )

    @field_validator(
        "supplier_name",
        "supplier_address",
        "supplier_gstin",
        "customer_name",
        "customer_address",
        "customer_gstin",
        "invoice_number",
        "invoice_date",
        "due_date",
        "bank_details",
        mode="before",
    )
    @classmethod
    def _clean_text_fields(cls, value: Any) -> str | None:
        return clean_text(value)

    @field_validator("currency", mode="before")
    @classmethod
    def _clean_currency(cls, value: Any) -> str | None:
        return parse_currency(value)

    @field_validator(
        "subtotal",
        "total_tax",
        "cgst",
        "sgst",
        "igst",
        "invoice_total",
        mode="before",
    )
    @classmethod
    def _parse_numeric_fields(cls, value: Any) -> float | None:
        return parse_number(value)


def _format_amount(value: float) -> str:
    return f"{value:,.2f}"


def _format_line_item(item: LineItem, index: int) -> str | None:
    description = item.description or (f"Item {index}" if item.amount is not None else None)
    if description is None:
        return None
    extras: list[str] = []
    if item.hsn_sac:
        extras.append(f"HSN/SAC: {item.hsn_sac}")
    if item.quantity is not None:
        extras.append(f"Qty: {item.quantity:g}")
    if item.unit_price is not None:
        extras.append(f"Unit: {_format_amount(item.unit_price)}")
    if item.tax_percentage is not None:
        extras.append(f"Tax: {item.tax_percentage:g}%")
    if item.amount is not None:
        extras.append(f"Amount: {_format_amount(item.amount)}")
    if extras:
        return f"{description} ({', '.join(extras)})"
    return description


class InvoiceData(ExtractedInvoice):
    """Invoice data enriched with a display-friendly ``items_purchased`` list.

    ``items_purchased`` exists for backwards compatibility with the existing
    frontend, which renders it as a simple bullet list.
    """

    items_purchased: list[str] = Field(
        default_factory=list, description="Display strings derived from line_items."
    )

    @field_validator("items_purchased", mode="before")
    @classmethod
    def _clean_items(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, (list, tuple)):
            return []
        cleaned: list[str] = []
        for entry in value:
            if isinstance(entry, dict):
                text = clean_text(
                    entry.get("description")
                    or entry.get("item")
                    or entry.get("name")
                    or entry.get("particulars")
                )
            else:
                text = clean_text(entry)
            if text:
                cleaned.append(text)
        return cleaned

    @model_validator(mode="after")
    def _derive_items_purchased(self) -> InvoiceData:
        if self.items_purchased:
            return self
        derived = [
            text
            for index, item in enumerate(self.line_items, start=1)
            if (text := _format_line_item(item, index)) is not None
        ]
        self.items_purchased = derived
        return self
