"""List every Gemini model available to the configured API key.

Usage:
    .\\venv\\Scripts\\python.exe scripts\\list_models.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google import genai  # noqa: E402

from app.config import get_settings  # noqa: E402


def main() -> int:
    settings = get_settings()
    if not settings.gemini_configured:
        print("GEMINI_API_KEY is not set. Add it to .env first.")
        return 1

    client = genai.Client(api_key=settings.api_key)
    for model in sorted(client.models.list(), key=lambda item: item.name):
        print(model.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
