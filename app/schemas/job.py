"""Schemas for background jobs and API responses."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobPublic(BaseModel):
    """A job as exposed by the API (no file paths, no callbacks)."""

    id: str
    filename: str
    approach: str
    status: JobStatus
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str
    updated_at: str


class UploadResponse(BaseModel):
    success: bool = True
    job_ids: list[str]


class JobsResponse(BaseModel):
    success: bool = True
    jobs: list[JobPublic]


class JobResponse(BaseModel):
    success: bool = True
    job: JobPublic


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    gemini_configured: bool
    tesseract_available: bool
    ocr_enabled: bool


class ErrorResponse(BaseModel):
    success: bool = False
    error: str = Field(description="A client-safe error message.")
