"""FastAPI routes."""

from __future__ import annotations

import logging
from functools import partial
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import APP_DIR, Settings
from app.exceptions import (
    FileValidationError,
    GeminiConfigurationError,
)
from app.schemas.job import (
    HealthResponse,
    JobResponse,
    JobsResponse,
    UploadResponse,
)
from app.services.gemini_client import GeminiClient
from app.services.invoice_service import extract_approach_1, extract_approach_2
from app.services.ocr_service import configure_tesseract, is_tesseract_available
from app.services.queue_manager import QueueManager
from app.utils.files import remove_file, save_upload

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
def app_settings(request: Request) -> Settings:
    return request.app.state.settings


def job_queue(request: Request) -> QueueManager:
    return request.app.state.queue_manager


def gemini_client(request: Request) -> GeminiClient:
    return request.app.state.gemini_client


SettingsDep = Annotated[Settings, Depends(app_settings)]
QueueDep = Annotated[QueueManager, Depends(job_queue)]
GeminiDep = Annotated[GeminiClient, Depends(gemini_client)]


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"results": None, "result": None},
    )


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------
async def _queue_uploads(
    invoices: list[UploadFile],
    approach: str,
    queue: QueueManager,
    settings: Settings,
    client: GeminiClient,
) -> UploadResponse:
    if not settings.gemini_configured:
        raise GeminiConfigurationError()
    if not invoices:
        raise FileValidationError(
            "No files were uploaded.",
            public_message="Please select at least one PDF file.",
        )
    if len(invoices) > settings.max_files_per_request:
        raise FileValidationError(
            "Too many files.",
            public_message=(
                f"You can upload at most {settings.max_files_per_request} PDFs at a time."
            ),
        )

    saved = []
    submitted_paths: set = set()
    try:
        for upload in invoices:
            saved.append(
                await run_in_threadpool(
                    save_upload,
                    upload,
                    settings.upload_dir,
                    settings.max_upload_bytes,
                )
            )

        callback = extract_approach_1 if approach == "approach1" else extract_approach_2
        job_ids: list[str] = []
        for item in saved:
            job_id = queue.submit(
                filename=item.original_name,
                file_path=item.path,
                callback=partial(callback, client=client, settings=settings),
                approach="Approach 1" if approach == "approach1" else "Approach 2",
            )
            submitted_paths.add(item.path)
            job_ids.append(job_id)

        return UploadResponse(job_ids=job_ids)
    except Exception:
        for item in saved:
            if item.path not in submitted_paths:
                remove_file(item.path)
        raise


@router.post(
    "/upload",
    response_model=UploadResponse,
    tags=["Extraction"],
    summary="Approach 1 - Gemini Vision",
    description=(
        "Upload one or more invoice PDFs. The PDF is sent directly to Gemini "
        "Vision. Returns job ids that can be polled via `GET /jobs/{job_id}`."
    ),
)
async def upload_approach1(
    invoices: Annotated[
        list[UploadFile],
        File(description="One or more invoice PDF files."),
    ],
    queue: QueueDep,
    settings: SettingsDep,
    client: GeminiDep,
) -> UploadResponse:
    return await _queue_uploads(invoices, "approach1", queue, settings, client)


@router.post(
    "/upload-approach2",
    response_model=UploadResponse,
    tags=["Extraction"],
    summary="Approach 2 - PyMuPDF + OCR text",
    description=(
        "Upload one or more invoice PDFs. Embedded text is extracted with "
        "PyMuPDF; pages without text are OCR'd with Tesseract. Falls back to "
        "Gemini Vision when OCR is unavailable. Returns job ids."
    ),
)
async def upload_approach2(
    invoices: Annotated[
        list[UploadFile],
        File(description="One or more invoice PDF files."),
    ],
    queue: QueueDep,
    settings: SettingsDep,
    client: GeminiDep,
) -> UploadResponse:
    return await _queue_uploads(invoices, "approach2", queue, settings, client)


# ---------------------------------------------------------------------------
# Jobs / health
# ---------------------------------------------------------------------------
@router.get(
    "/jobs",
    response_model=JobsResponse,
    tags=["Jobs"],
    summary="List all extraction jobs",
)
def get_jobs(queue: QueueDep) -> JobsResponse:
    return JobsResponse(jobs=queue.get_jobs())


@router.get(
    "/jobs/{job_id}",
    response_model=JobResponse,
    tags=["Jobs"],
    summary="Get one extraction job",
)
def get_job(job_id: str, queue: QueueDep) -> JobResponse:
    job = queue.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return JobResponse(job=job)


@router.get(
    "/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="Health and configuration status",
)
def health(settings: SettingsDep) -> HealthResponse:
    configure_tesseract(settings)
    return HealthResponse(
        version=settings.app_version,
        gemini_configured=settings.gemini_configured,
        tesseract_available=bool(settings.ocr_enabled and is_tesseract_available()),
        ocr_enabled=settings.ocr_enabled,
    )
