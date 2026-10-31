"""Secure upload handling helpers."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from app.exceptions import (
    FileTooLargeError,
    FileValidationError,
    UnsupportedFileTypeError,
)

logger = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF-"
_CHUNK_SIZE = 1024 * 1024
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class SavedUpload:
    path: Path
    original_name: str
    size_bytes: int


def sanitize_filename(filename: str | None) -> str:
    """Reduce a client-provided filename to a safe display name.

    The returned value is *never* used as a filesystem path; files are stored
    under a random UUID name.
    """
    if not filename:
        return "invoice.pdf"
    base = filename.replace("\\", "/").split("/")[-1]
    base = _CONTROL_CHARS.sub("", base).strip()
    base = base[:200].strip()
    return base or "invoice.pdf"


def _validate_pdf_name(filename: str) -> None:
    if Path(filename).suffix.lower() != ".pdf":
        raise UnsupportedFileTypeError(f"Unsupported file type: {filename}")


def save_upload(upload: UploadFile, dest_dir: Path, max_bytes: int) -> SavedUpload:
    """Validate and persist an uploaded PDF.

    This function performs blocking disk I/O and must be called from a worker
    thread (or a synchronous endpoint), never directly from the event loop.
    """
    original_name = sanitize_filename(upload.filename)
    _validate_pdf_name(original_name)

    dest_dir.mkdir(parents=True, exist_ok=True)
    destination = dest_dir / f"{uuid.uuid4().hex}.pdf"

    size = 0
    try:
        with destination.open("wb") as buffer:
            first_chunk = True
            while True:
                chunk = upload.file.read(_CHUNK_SIZE)
                if not chunk:
                    break

                if first_chunk:
                    first_chunk = False
                    if PDF_MAGIC not in chunk[:1024]:
                        raise UnsupportedFileTypeError(
                            f"{original_name} does not look like a PDF file."
                        )

                size += len(chunk)
                if size > max_bytes:
                    raise FileTooLargeError(
                        f"{original_name} exceeds the maximum allowed size.",
                        public_message=(
                            f"'{original_name}' is too large. "
                            f"Maximum size is {max_bytes / (1024 * 1024):.0f} MB."
                        ),
                    )
                buffer.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    if size == 0:
        destination.unlink(missing_ok=True)
        raise FileValidationError(
            f"{original_name} is empty.",
            public_message=f"'{original_name}' is empty.",
        )

    return SavedUpload(path=destination, original_name=original_name, size_bytes=size)


def remove_file(path: Path | str | None) -> None:
    """Best-effort removal of a temporary file."""
    if path is None:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError as exc:  # pragma: no cover - filesystem specific
        logger.warning("Could not delete temporary file %s: %s", path, exc)
