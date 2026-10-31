"""Normalise LLM-produced JSON before Pydantic validation.

Models occasionally return slightly different key names (``vendor_name``
instead of ``supplier_name``, ``qty`` instead of ``quantity``). Mapping them
here keeps the Pydantic models and the Gemini response schema clean.
"""

from __future__ import annotations

from typing import Any

_INVOICE_ALIASES = {
    # supplier / vendor
    "vendor_name": "supplier_name",
    "seller_name": "supplier_name",
    "supplier": "supplier_name",
    "vendor_address": "supplier_address",
    "seller_address": "supplier_address",
    "vendor_gstin": "supplier_gstin",
    "seller_gstin": "supplier_gstin",
    "gstin": "supplier_gstin",
    "supplier_gst": "supplier_gstin",
    # customer / buyer
    "buyer_name": "customer_name",
    "bill_to_name": "customer_name",
    "buyer_address": "customer_address",
    "bill_to_address": "customer_address",
    "buyer_gstin": "customer_gstin",
    "customer_gst": "customer_gstin",
    # document
    "invoice_no": "invoice_number",
    "invoice_id": "invoice_number",
    "bill_number": "invoice_number",
    "date": "invoice_date",
    "invoice_dt": "invoice_date",
    "payment_due_date": "due_date",
    "due": "due_date",
    "invoice_currency": "currency",
    "currency_code": "currency",
    # amounts
    "sub_total": "subtotal",
    "net_amount": "subtotal",
    "tax_total": "total_tax",
    "tax_amount": "total_tax",
    "grand_total": "invoice_total",
    "total_amount": "invoice_total",
    "amount_due": "invoice_total",
    "total": "invoice_total",
    # misc
    "bank_detail": "bank_details",
    "bank_info": "bank_details",
    "payment_details": "bank_details",
    "items": "line_items",
    "invoice_items": "line_items",
    "lineitems": "line_items",
    "line_item": "line_items",
}

_ITEM_ALIASES = {
    "item": "description",
    "item_name": "description",
    "name": "description",
    "particulars": "description",
    "product": "description",
    "hsn": "hsn_sac",
    "hsn_code": "hsn_sac",
    "sac": "hsn_sac",
    "sac_code": "hsn_sac",
    "qty": "quantity",
    "rate": "unit_price",
    "price": "unit_price",
    "tax_rate": "tax_percentage",
    "gst_rate": "tax_percentage",
    "tax_percent": "tax_percentage",
    "tax": "tax_percentage",
    "total": "amount",
    "line_total": "amount",
    "final_amount": "amount",
}

_CANONICAL_INVOICE_KEYS = {
    "supplier_name",
    "supplier_address",
    "supplier_gstin",
    "customer_name",
    "customer_address",
    "customer_gstin",
    "invoice_number",
    "invoice_date",
    "due_date",
    "currency",
    "subtotal",
    "total_tax",
    "cgst",
    "sgst",
    "igst",
    "invoice_total",
    "bank_details",
    "line_items",
    "items_purchased",
}


def _normalise_keys(data: dict[str, Any], aliases: dict[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in data.items():
        normalised = str(key).strip().lower().replace(" ", "_").replace("-", "_")
        target = aliases.get(normalised, normalised)
        result[target] = value
    return result


def normalize_invoice_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict with canonical invoice/line-item keys."""
    if not isinstance(payload, dict):
        return {}

    data = _normalise_keys(payload, _INVOICE_ALIASES)

    line_items = data.get("line_items")
    if isinstance(line_items, dict):
        line_items = [line_items]
    if not isinstance(line_items, list):
        line_items = []

    normalized_items: list[Any] = []
    for item in line_items:
        if isinstance(item, dict):
            normalized_items.append(_normalise_keys(item, _ITEM_ALIASES))
        elif isinstance(item, str) and item.strip():
            normalized_items.append({"description": item.strip()})
    data["line_items"] = normalized_items

    items_purchased = data.get("items_purchased")
    if isinstance(items_purchased, str):
        data["items_purchased"] = [items_purchased]
    elif isinstance(items_purchased, list):
        cleaned: list[str] = []
        for entry in items_purchased:
            if isinstance(entry, dict):
                text = (
                    entry.get("description")
                    or entry.get("item")
                    or entry.get("name")
                    or entry.get("particulars")
                )
                if isinstance(text, str) and text.strip():
                    cleaned.append(text.strip())
            elif isinstance(entry, str) and entry.strip():
                cleaned.append(entry.strip())
        data["items_purchased"] = cleaned
    else:
        data.pop("items_purchased", None)

    # Drop completely unknown keys; Pydantic ignores extras anyway, but this
    # makes the normalised payload easier to inspect and test.
    return {key: value for key, value in data.items() if key in _CANONICAL_INVOICE_KEYS}
