"""Tests for robust JSON parsing of model responses."""

from __future__ import annotations

import pytest

from app.exceptions import ExtractionParseError
from app.utils.json_parser import parse_json_object


def test_parses_plain_json_object():
    assert parse_json_object('{"a": 1}') == {"a": 1}


def test_parses_fenced_json():
    text = '```json\n{"invoice_number": "INV-1"}\n```'
    assert parse_json_object(text) == {"invoice_number": "INV-1"}


def test_parses_fenced_json_without_language():
    text = '```\n{"a": 2}\n```'
    assert parse_json_object(text) == {"a": 2}


def test_parses_json_after_prose():
    text = 'Here is the result:\n{"invoice_total": 100.5}\nThank you.'
    assert parse_json_object(text) == {"invoice_total": 100.5}


def test_handles_braces_inside_strings():
    text = '{"note": "a } brace", "value": 1}'
    assert parse_json_object(text) == {"note": "a } brace", "value": 1}


def test_handles_escaped_quotes():
    text = '{"note": "he said \\"hi\\"", "value": 2}'
    assert parse_json_object(text) == {"note": 'he said "hi"', "value": 2}


def test_unwraps_single_item_list():
    assert parse_json_object('[{"a": 3}]') == {"a": 3}


def test_strips_bom():
    assert parse_json_object('\ufeff{"a": 4}') == {"a": 4}


@pytest.mark.parametrize("value", [None, "", "   ", "not json at all", "```json\n{bad}\n```"])
def test_invalid_responses_raise(value):
    with pytest.raises(ExtractionParseError):
        parse_json_object(value)
