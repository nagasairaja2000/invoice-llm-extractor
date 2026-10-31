"""Tests for the invoice Pydantic schema and normalisation."""

from __future__ import annotations

from app.schemas.invoice import (
    ExtractedInvoice,
    InvoiceData,
    LineItem,
    parse_currency,
    parse_number,
)
from app.utils.normalize import normalize_invoice_payload


def test_parse_number_handles_currency_and_commas():
    assert parse_number("₹ 1,234.50") == 1234.50
    assert parse_number("INR 2,000") == 2000.0
    assert parse_number("Rs. 99.99") == 99.99
    assert parse_number("$1,000.00") == 1000.0


def test_parse_number_handles_negative_parentheses():
    assert parse_number("(500.00)") == -500.0


def test_parse_number_returns_none_for_unknown():
    assert parse_number(None) is None
    assert parse_number("") is None
    assert parse_number("N/A") is None
    assert parse_number("not available") is None
    assert parse_number("abc") is None
    assert parse_number(True) is None


def test_parse_number_keeps_numeric_values():
    assert parse_number(12) == 12.0
    assert parse_number(12.5) == 12.5


def test_parse_currency():
    assert parse_currency("₹") == "INR"
    assert parse_currency("Rs.") == "INR"
    assert parse_currency("usd") == "USD"
    assert parse_currency("XAU") == "XAU"
    assert parse_currency(None) is None


def test_missing_fields_default_to_none():
    invoice = ExtractedInvoice.model_validate({})
    assert invoice.supplier_name is None
    assert invoice.invoice_total is None
    assert invoice.line_items == []


def test_extra_fields_are_ignored():
    invoice = ExtractedInvoice.model_validate({"supplier_name": "A", "unknown": "x"})
    assert invoice.supplier_name == "A"
    assert not hasattr(invoice, "unknown")


def test_line_item_coercion():
    item = LineItem.model_validate(
        {
            "description": "Hosting",
            "quantity": "2",
            "unit_price": "₹ 1,500.50",
            "tax_percentage": "18%",
            "amount": "3,001.00",
        }
    )
    assert item.quantity == 2.0
    assert item.unit_price == 1500.50
    assert item.tax_percentage == 18.0
    assert item.amount == 3001.0


def test_items_purchased_is_derived_from_line_items():
    invoice = InvoiceData.model_validate(
        {
            "line_items": [
                {
                    "description": "Hosting",
                    "quantity": 2,
                    "unit_price": 1500,
                    "tax_percentage": 18,
                    "amount": 3000,
                }
            ]
        }
    )
    assert len(invoice.items_purchased) == 1
    text = invoice.items_purchased[0]
    assert "Hosting" in text
    assert "Qty: 2" in text
    assert "Amount: 3,000.00" in text


def test_items_purchased_is_preserved_when_supplied():
    invoice = InvoiceData.model_validate(
        {"items_purchased": ["A", "", "B"], "line_items": [{"description": "C"}]}
    )
    assert invoice.items_purchased == ["A", "B"]


def test_normalise_vendor_aliases():
    payload = {
        "vendor_name": "Vendor Ltd",
        "vendor_gstin": "29ABCDE1234F1Z5",
        "buyer_name": "Buyer Ltd",
        "invoice_no": "INV-9",
        "grand_total": "₹ 1,180.00",
        "tax_total": "180",
        "items": [
            {"item": "Widget", "qty": "2", "rate": "500", "tax_rate": "18", "total": "1180"}
        ],
    }
    normalized = normalize_invoice_payload(payload)
    assert normalized["supplier_name"] == "Vendor Ltd"
    assert normalized["supplier_gstin"] == "29ABCDE1234F1Z5"
    assert normalized["customer_name"] == "Buyer Ltd"
    assert normalized["invoice_number"] == "INV-9"
    assert normalized["invoice_total"] == "₹ 1,180.00"
    assert normalized["line_items"][0] == {
        "description": "Widget",
        "quantity": "2",
        "unit_price": "500",
        "tax_percentage": "18",
        "amount": "1180",
    }

    invoice = InvoiceData.model_validate(normalized)
    assert invoice.invoice_total == 1180.0
    assert invoice.total_tax == 180.0
    assert invoice.line_items[0].description == "Widget"
    assert invoice.line_items[0].quantity == 2.0


def test_normalise_string_line_items():
    normalized = normalize_invoice_payload({"items": ["Item A", "Item B"]})
    assert normalized["line_items"] == [
        {"description": "Item A"},
        {"description": "Item B"},
    ]


def test_unknown_top_level_keys_are_dropped():
    normalized = normalize_invoice_payload({"supplier_name": "A", "random": 1})
    assert normalized == {"supplier_name": "A", "line_items": []}
