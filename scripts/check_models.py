"""Check which configured Gemini models are available.

Usage:
    .\\venv\\Scripts\\python.exe scripts\\check_models.py
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

    available = {model.name for model in client.models.list()}
    print(f"Available models: {len(available)}\n")

    failures = 0
    for model in settings.model_list:
        print(f"Testing {model} ... ", end="")
        if model not in available:
            print("NOT AVAILABLE")
            failures += 1
            continue
        try:
            response = client.models.generate_content(
                model=model, contents="Reply with the word OK."
            )
            print(f"OK ({response.text!r})")
        except Exception as exc:  # noqa: BLE001 - diagnostic script
            print(f"FAILED: {exc}")
            failures += 1

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
