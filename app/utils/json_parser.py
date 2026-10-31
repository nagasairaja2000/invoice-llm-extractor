"""Robust extraction of a JSON object from an LLM response."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.exceptions import ExtractionParseError

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


def _loads(candidate: str) -> Any | None:
    try:
        return json.loads(candidate)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _find_balanced_object(text: str) -> str | None:
    """Return the first complete top-level ``{...}`` block.

    Handles braces inside JSON strings and escaped quotes.
    """
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        start = text.find("{", start + 1)
    return None


def parse_json_object(text: str | None) -> dict[str, Any]:
    """Parse a JSON object from model output, tolerating fences and prose.

    Raises:
        ExtractionParseError: when no JSON object can be recovered.
    """
    if text is None:
        raise ExtractionParseError("The AI model returned an empty response.")

    cleaned = text.strip().lstrip("\ufeff").strip()
    if not cleaned:
        raise ExtractionParseError("The AI model returned an empty response.")

    candidates: list[str] = [cleaned]
    candidates.extend(match.group(1).strip() for match in _FENCE_RE.finditer(cleaned))
    balanced = _find_balanced_object(cleaned)
    if balanced:
        candidates.append(balanced)

    for candidate in candidates:
        if not candidate:
            continue
        parsed = _loads(candidate)
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
            return parsed[0]

    logger.debug("Unparseable model response (first 500 chars): %s", cleaned[:500])
    raise ExtractionParseError("The AI model returned invalid JSON.")
