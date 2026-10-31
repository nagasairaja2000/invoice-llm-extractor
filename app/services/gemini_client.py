"""Thin wrapper around the Google Gen AI SDK.

Responsibilities:
* lazy client creation (the app must start without a key),
* model fallback and bounded retries,
* request timeouts,
* structured JSON output,
* Gemini file upload lifecycle (wait until ACTIVE, always delete).
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from app.config import Settings
from app.exceptions import (
    ExtractionParseError,
    GeminiConfigurationError,
    GeminiServiceError,
)
from app.services.prompt import SYSTEM_INSTRUCTION

logger = logging.getLogger(__name__)

_RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}
_AUTH_HTTP_CODES = {401, 403}


@dataclass(frozen=True)
class GeminiResult:
    text: str
    model: str
    prompt_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class GeminiClient:
    """Stateful Gemini client shared by all background jobs."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: genai.Client | None = None

    # ------------------------------------------------------------------
    # Client / configuration
    # ------------------------------------------------------------------
    def _get_client(self) -> genai.Client:
        if self._client is None:
            if not self.settings.gemini_configured:
                raise GeminiConfigurationError()
            self._client = genai.Client(
                api_key=self.settings.api_key,
                http_options=types.HttpOptions(
                    timeout=int(self.settings.gemini_timeout_seconds * 1000)
                ),
            )
        return self._client

    def _build_config(
        self, schema: type[BaseModel] | None, use_schema: bool
    ) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            temperature=0,
            max_output_tokens=self.settings.gemini_max_output_tokens,
            response_mime_type="application/json",
            response_schema=schema if (schema is not None and use_schema) else None,
            system_instruction=SYSTEM_INSTRUCTION,
            http_options=types.HttpOptions(
                timeout=int(self.settings.gemini_timeout_seconds * 1000)
            ),
        )

    # ------------------------------------------------------------------
    # Generate
    # ------------------------------------------------------------------
    def generate(
        self,
        contents: Any,
        schema: type[BaseModel] | None = None,
    ) -> GeminiResult:
        """Generate JSON content, trying configured models in order."""
        client = self._get_client()
        models = self.settings.model_list
        if not models:
            raise GeminiConfigurationError("No Gemini models are configured.")

        last_error: Exception | None = None

        for model in models:
            use_schema = schema is not None and self.settings.gemini_use_response_schema
            attempt = 0

            while attempt < self.settings.gemini_max_retries:
                attempt += 1
                try:
                    response = client.models.generate_content(
                        model=model,
                        contents=contents,
                        config=self._build_config(schema, use_schema),
                    )
                except errors.APIError as exc:
                    last_error = exc
                    code = getattr(exc, "code", None)
                    status = getattr(exc, "status", "") or ""
                    message = str(exc)
                    logger.warning(
                        "Gemini error (model=%s attempt=%s code=%s status=%s): %s",
                        model,
                        attempt,
                        code,
                        status,
                        message[:300],
                    )

                    if code in _AUTH_HTTP_CODES or status in {
                        "PERMISSION_DENIED",
                        "UNAUTHENTICATED",
                    }:
                        raise GeminiConfigurationError(
                            "Gemini rejected the API key or permissions."
                        ) from exc

                    if code == 404 or status == "NOT_FOUND":
                        break  # try the next configured model

                    if (
                        code == 400
                        and use_schema
                        and "schema" in message.lower()
                    ):
                        logger.warning(
                            "Model %s rejected the response schema; retrying without it.",
                            model,
                        )
                        use_schema = False
                        continue

                    if code in _RETRYABLE_HTTP_CODES or status in {
                        "RESOURCE_EXHAUSTED",
                        "UNAVAILABLE",
                        "INTERNAL",
                    }:
                        if attempt < self.settings.gemini_max_retries:
                            self._sleep_before_retry(attempt)
                            continue
                        break  # try the next model

                    raise GeminiServiceError(
                        f"Gemini request failed ({code or status}): {message}"
                    ) from exc

                except (httpx.TimeoutException, TimeoutError, ConnectionError, OSError) as exc:
                    last_error = exc
                    logger.warning(
                        "Gemini network error (model=%s attempt=%s): %s",
                        model,
                        attempt,
                        exc,
                    )
                    if attempt < self.settings.gemini_max_retries:
                        self._sleep_before_retry(attempt)
                        continue
                    break

                except Exception as exc:  # unexpected SDK error
                    logger.exception("Unexpected Gemini error (model=%s)", model)
                    raise GeminiServiceError(f"Unexpected Gemini error: {exc}") from exc

                text = self._response_text(response)
                usage = getattr(response, "usage_metadata", None)
                return GeminiResult(
                    text=text,
                    model=model,
                    prompt_tokens=getattr(usage, "prompt_token_count", 0) or 0,
                    output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
                    total_tokens=getattr(usage, "total_token_count", 0) or 0,
                )

        raise GeminiServiceError(
            "All configured Gemini models failed. Please try again later."
        ) from last_error

    def _sleep_before_retry(self, attempt: int) -> None:
        delay = min(
            self.settings.gemini_retry_base_seconds * (2 ** (attempt - 1)),
            self.settings.gemini_retry_max_seconds,
        )
        delay += random.uniform(0, 0.5)
        logger.info("Retrying Gemini request in %.1f seconds.", delay)
        time.sleep(delay)

    @staticmethod
    def _response_text(response: Any) -> str:
        text = getattr(response, "text", None)
        if text and text.strip():
            return text
        finish_reason: Any = None
        try:
            finish_reason = response.candidates[0].finish_reason
        except (AttributeError, IndexError, TypeError):
            pass
        raise ExtractionParseError(
            f"Gemini returned an empty response (finish_reason={finish_reason})."
        )

    # ------------------------------------------------------------------
    # Files API
    # ------------------------------------------------------------------
    def upload_pdf(self, file_path: Path | str) -> tuple[types.File, float]:
        """Upload a PDF and wait until it is ACTIVE.

        Returns the uploaded file and the upload time in seconds.
        """
        client = self._get_client()
        started = time.perf_counter()

        try:
            uploaded = client.files.upload(
                file=str(file_path),
                config=types.UploadFileConfig(
                    mime_type="application/pdf",
                    display_name=Path(file_path).name,
                ),
            )
        except errors.APIError as exc:
            raise GeminiServiceError(f"Gemini file upload failed: {exc}") from exc
        except (httpx.TimeoutException, TimeoutError, ConnectionError, OSError) as exc:
            raise GeminiServiceError(f"Gemini file upload timed out: {exc}") from exc

        deadline = time.monotonic() + self.settings.gemini_timeout_seconds
        state = self._state_name(uploaded)

        while state == "PROCESSING":
            if time.monotonic() > deadline:
                self.delete_file(uploaded)
                raise GeminiServiceError("Gemini file processing timed out. Please retry.")
            time.sleep(1.0)
            try:
                uploaded = client.files.get(name=uploaded.name)
            except errors.APIError as exc:
                raise GeminiServiceError(f"Could not check Gemini file state: {exc}") from exc
            state = self._state_name(uploaded)

        if state != "ACTIVE":
            self.delete_file(uploaded)
            raise GeminiServiceError(
                f"Gemini could not process the uploaded PDF (state={state})."
            )

        elapsed = round(time.perf_counter() - started, 3)
        return uploaded, elapsed

    def delete_file(self, uploaded: Any) -> None:
        """Delete an uploaded Gemini file (best effort)."""
        name = getattr(uploaded, "name", None)
        if not name:
            return
        try:
            self._get_client().files.delete(name=name)
        except Exception as exc:  # pragma: no cover - remote cleanup
            logger.warning("Could not delete Gemini file %s: %s", name, exc)

    @staticmethod
    def _state_name(uploaded: Any) -> str:
        state = getattr(uploaded, "state", None)
        return getattr(state, "name", str(state)) if state is not None else "UNKNOWN"
