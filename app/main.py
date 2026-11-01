"""FastAPI application factory and entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import APP_DIR, Settings, get_settings
from app.exceptions import AppError
from app.logging_config import configure_logging
from app.services.gemini_client import GeminiClient
from app.services.ocr_service import configure_tesseract, is_tesseract_available
from app.services.queue_manager import QueueManager

logger = logging.getLogger(__name__)

DESCRIPTION = """
Extract structured invoice data from digital and scanned PDFs.

* **Approach 1** sends the PDF directly to Gemini Vision.
* **Approach 2** extracts embedded text with PyMuPDF and uses Tesseract OCR
  for pages without text, then sends the text to Gemini.

Both endpoints are asynchronous: they return job ids, and results are polled
from `GET /jobs/{job_id}`.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    configure_logging(settings.log_level)

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    configure_tesseract(settings)

    logger.info("Starting %s v%s", settings.app_name, settings.app_version)
    if not settings.gemini_configured:
        logger.warning("GEMINI_API_KEY is not configured; uploads will be rejected.")
    if settings.ocr_enabled and not is_tesseract_available():
        logger.warning(
            "Tesseract OCR is not available. Scanned PDFs will fall back to Gemini Vision. "
            "Install Tesseract or set TESSERACT_CMD in .env."
        )

    try:
        yield
    finally:
        app.state.queue_manager.shutdown()
        logger.info("Application shutdown complete.")


def create_app(
    settings: Settings | None = None,
    gemini_client: GeminiClient | None = None,
    queue_manager: QueueManager | None = None,
) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title=settings.app_name,
        description=DESCRIPTION,
        version=settings.app_version,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.gemini_client = gemini_client or GeminiClient(settings)
    app.state.queue_manager = queue_manager or QueueManager(settings)

    app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
    app.include_router(router)

    @app.middleware("http")
    async def _no_store_for_ui(request: Request, call_next):
        """Always revalidate the HTML and static assets during development.

        Without this, browsers can keep an older ``app.js`` cached after an
        upgrade and post to the API with an outdated response contract.
        """
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        logger.warning(
            "Handled error on %s %s: [%s] %s",
            request.method,
            request.url.path,
            type(exc).__name__,
            exc,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"success": False, "error": exc.public_message},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "error": "Invalid request.",
                "details": jsonable_encoder(exc.errors()),
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "Unhandled error on %s %s", request.method, request.url.path
        )
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "Internal server error."},
        )

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
