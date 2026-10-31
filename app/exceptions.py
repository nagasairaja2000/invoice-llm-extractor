"""Typed application exceptions with client-safe messages."""

from __future__ import annotations


class AppError(Exception):
    """Base class for expected application errors.

    ``public_message`` is safe to show to an API client; the exception text
    itself is intended for logs only.
    """

    status_code: int = 500
    public_message: str = "An unexpected error occurred."

    def __init__(self, message: str | None = None, *, public_message: str | None = None):
        super().__init__(message or self.public_message)
        if public_message is not None:
            self.public_message = public_message


class FileValidationError(AppError):
    status_code = 400
    public_message = "The uploaded file is invalid."


class FileTooLargeError(FileValidationError):
    status_code = 413
    public_message = "The uploaded file is too large."


class UnsupportedFileTypeError(FileValidationError):
    status_code = 400
    public_message = "Only PDF files are supported."


class PdfError(AppError):
    status_code = 400
    public_message = "The uploaded PDF could not be processed."


class CorruptPdfError(PdfError):
    public_message = "The uploaded file is not a valid PDF or is corrupted."


class PasswordProtectedPdfError(PdfError):
    public_message = "This PDF is password-protected. Please upload an unlocked copy."


class PdfLimitError(PdfError):
    status_code = 413
    public_message = "The PDF has too many pages or too much text to process."


class OcrError(AppError):
    status_code = 503
    public_message = "OCR is currently unavailable."


class OcrUnavailableError(OcrError):
    public_message = (
        "Tesseract OCR is not installed or not configured. "
        "Install Tesseract or set TESSERACT_CMD in .env."
    )


class GeminiConfigurationError(AppError):
    status_code = 503
    public_message = "Gemini API key is not configured. Set GEMINI_API_KEY in .env."


class GeminiServiceError(AppError):
    status_code = 502
    public_message = "The AI service could not process this invoice. Please try again."


class ExtractionParseError(GeminiServiceError):
    public_message = "The AI service returned an invalid response. Please try again."
