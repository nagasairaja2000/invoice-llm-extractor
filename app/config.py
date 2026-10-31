"""Application configuration loaded from environment variables / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root: .../invoice-llm-extractor
BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """Typed application settings.

    Every value can be overridden with an environment variable of the same
    name (case-insensitive) or through the ``.env`` file in the project root.
    """

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Invoice LLM Extractor"
    app_version: str = "2.0.0"
    log_level: str = "INFO"

    # --- Gemini -----------------------------------------------------------
    gemini_api_key: SecretStr | None = None
    gemini_models: str = (
        "models/gemini-3.1-flash-lite,"
        "models/gemini-3.8-flash,"
        "models/gemini-flash-lite-latest,"
        "models/gemini-flash-latest"
    )
    gemini_timeout_seconds: float = 120.0
    gemini_max_retries: int = 3
    gemini_retry_base_seconds: float = 1.5
    gemini_retry_max_seconds: float = 8.0
    gemini_use_response_schema: bool = True
    gemini_max_output_tokens: int = 8192

    # --- Uploads ----------------------------------------------------------
    max_upload_mb: float = 10.0
    max_files_per_request: int = 10
    max_pdf_pages: int = 50
    max_text_chars: int = 150_000
    upload_dir: Path = BASE_DIR / "uploads"
    keep_uploads: bool = False
    job_ttl_seconds: int = 3600
    max_jobs: int = 200
    worker_threads: int = 3

    # --- OCR --------------------------------------------------------------
    ocr_enabled: bool = True
    tesseract_cmd: str | None = None
    ocr_languages: str = "eng"
    ocr_dpi: int = 300
    ocr_psm: int = 3
    ocr_timeout_seconds: int = 60
    min_chars_per_page: int = 40
    min_ocr_chars: int = 40

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        return value.upper()

    @field_validator("upload_dir")
    @classmethod
    def _absolute_upload_dir(cls, value: Path) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = BASE_DIR / path
        return path

    @field_validator("tesseract_cmd")
    @classmethod
    def _empty_tesseract_cmd(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("gemini_max_retries", "worker_threads", "max_pdf_pages")
    @classmethod
    def _positive_int(cls, value: int) -> int:
        if value < 1:
            raise ValueError("must be greater than zero")
        return value

    @field_validator("max_upload_mb")
    @classmethod
    def _positive_size(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("must be greater than zero")
        return value

    @property
    def api_key(self) -> str | None:
        """Return the API key as plain text, or ``None`` when not configured."""
        if self.gemini_api_key is None:
            return None
        value = self.gemini_api_key.get_secret_value().strip()
        return value or None

    @property
    def gemini_configured(self) -> bool:
        return self.api_key is not None

    @property
    def model_list(self) -> list[str]:
        models: list[str] = []
        for raw in self.gemini_models.split(","):
            name = raw.strip()
            if name and name not in models:
                models.append(name)
        return models

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance (cached)."""
    return Settings()
