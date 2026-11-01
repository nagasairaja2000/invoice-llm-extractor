"""End-to-end API tests using FastAPI's TestClient and a fake Gemini client."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.exceptions import GeminiServiceError
from app.main import create_app
from tests.helpers import (
    FakeGeminiClient,
    make_digital_pdf,
    make_image_file,
    wait_for_job,
)


def _upload(client: TestClient, url: str, path: Path, name: str | None = None):
    with path.open("rb") as handle:
        return client.post(
            url,
            files={"invoices": (name or path.name, handle, "application/pdf")},
        )


def test_home_page_renders_both_approaches(client: TestClient):
    response = client.get("/")

    assert response.status_code == 200
    body = response.text
    assert "Extract - Approach 1" in body
    assert "Extract - Approach 2" in body
    assert "Gemini Vision" in body
    assert "PyMuPDF + OCR" in body


def test_health_reports_configuration(client: TestClient):
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["gemini_configured"] is True
    assert payload["ocr_enabled"] is True
    assert "tesseract_available" in payload


def test_jobs_is_empty_initially(client: TestClient):
    response = client.get("/jobs")

    assert response.status_code == 200
    assert response.json() == {"success": True, "jobs": []}


def test_docs_and_openapi_are_served(client: TestClient):
    assert client.get("/docs").status_code == 200

    schema = client.get("/openapi.json").json()
    assert set(schema["paths"]) == {
        "/upload",
        "/upload-approach2",
        "/jobs",
        "/jobs/{job_id}",
        "/health",
    }
    assert schema["info"]["title"] == "Invoice LLM Extractor"


def test_ui_assets_are_not_cached(client: TestClient):
    page = client.get("/")
    script = client.get("/static/js/app.js")

    assert page.status_code == 200
    assert script.status_code == 200
    assert page.headers["cache-control"] == "no-store, max-age=0"
    assert script.headers["cache-control"] == "no-store, max-age=0"
    assert "app.js?v=2.0.0" in page.text



def test_approach_1_upload_creates_completed_job(client: TestClient, digital_pdf: Path):
    response = _upload(client, "/upload", digital_pdf)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["success"] is True
    assert len(payload["job_ids"]) == 1

    job = wait_for_job(client, payload["job_ids"][0])
    assert job["status"] == "COMPLETED"
    assert job["approach"] == "Approach 1"
    assert job["filename"] == digital_pdf.name
    assert job["result"]["approach"] == "Gemini Vision"
    assert job["result"]["invoice"]["invoice_total"] == 64900.0


def test_approach_2_upload_creates_completed_job(client: TestClient, digital_pdf: Path):
    response = _upload(client, "/upload-approach2", digital_pdf)

    assert response.status_code == 200, response.text
    job = wait_for_job(client, response.json()["job_ids"][0])

    assert job["status"] == "COMPLETED"
    assert job["approach"] == "Approach 2"
    assert job["result"]["approach"] == "PyMuPDF + Gemini Text"


def test_multiple_files_are_queued(client: TestClient, tmp_path: Path):
    first = make_digital_pdf(tmp_path / "first.pdf")
    second = make_digital_pdf(tmp_path / "second.pdf", text="INVOICE\nTotal: 200.00")

    response = client.post(
        "/upload",
        files=[
            ("invoices", (first.name, first.read_bytes(), "application/pdf")),
            ("invoices", (second.name, second.read_bytes(), "application/pdf")),
        ],
    )

    assert response.status_code == 200, response.text
    job_ids = response.json()["job_ids"]
    assert len(job_ids) == 2

    jobs = [wait_for_job(client, job_id) for job_id in job_ids]
    assert {job["status"] for job in jobs} == {"COMPLETED"}
    assert {job["filename"] for job in jobs} == {first.name, second.name}


def test_no_files_returns_validation_error(client: TestClient):
    response = client.post("/upload", data={})

    assert response.status_code == 422
    assert response.json()["success"] is False


def test_non_pdf_extension_is_rejected(client: TestClient, tmp_path: Path):
    note = tmp_path / "notes.txt"
    note.write_text("hello", encoding="utf-8")

    response = _upload(client, "/upload", note)

    assert response.status_code == 400
    assert response.json()["success"] is False
    assert "PDF" in response.json()["error"]


def test_spoofed_pdf_is_rejected(client: TestClient, tmp_path: Path):
    fake = tmp_path / "fake.pdf"
    fake.write_bytes(b"this is not really a pdf")

    response = _upload(client, "/upload", fake)

    assert response.status_code == 400
    assert response.json()["error"] == "Only PDF files are supported."


def test_image_renamed_to_pdf_is_rejected(client: TestClient, tmp_path: Path):
    image = make_image_file(tmp_path / "image.pdf")

    response = _upload(client, "/upload", image)

    assert response.status_code == 400


def test_empty_file_is_rejected(client: TestClient, tmp_path: Path):
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")

    response = _upload(client, "/upload", empty)

    assert response.status_code == 400
    assert "empty" in response.json()["error"].lower()


def test_oversized_file_is_rejected(settings, fake_client: FakeGeminiClient, tmp_path: Path):
    small_limit = settings.model_copy(update={"max_upload_mb": 0.001})
    app = create_app(settings=small_limit, gemini_client=fake_client)

    big = tmp_path / "big.pdf"
    big.write_bytes(b"%PDF-1.4\n" + b"0" * 4096)

    with TestClient(app) as client:
        response = _upload(client, "/upload", big)

    assert response.status_code == 413
    assert "too large" in response.json()["error"].lower()


def test_too_many_files_are_rejected(settings, fake_client: FakeGeminiClient, tmp_path: Path):
    limited = settings.model_copy(update={"max_files_per_request": 1})
    app = create_app(settings=limited, gemini_client=fake_client)

    pdf = make_digital_pdf(tmp_path / "one.pdf")
    content = pdf.read_bytes()

    with TestClient(app) as client:
        response = client.post(
            "/upload",
            files=[
                ("invoices", ("one.pdf", content, "application/pdf")),
                ("invoices", ("two.pdf", content, "application/pdf")),
            ],
        )

    assert response.status_code == 400
    assert "at most 1" in response.json()["error"]


def test_missing_api_key_returns_503(settings, tmp_path: Path):
    no_key = settings.model_copy(update={"gemini_api_key": None})
    app = create_app(settings=no_key, gemini_client=FakeGeminiClient())
    pdf = make_digital_pdf(tmp_path / "invoice.pdf")

    with TestClient(app) as client:
        response = _upload(client, "/upload", pdf)

    assert response.status_code == 503
    assert "GEMINI_API_KEY" in response.json()["error"]


def test_path_traversal_filename_is_sanitised(client: TestClient, settings, digital_pdf: Path):
    response = _upload(client, "/upload", digital_pdf, name="../../../evil.pdf")

    assert response.status_code == 200, response.text
    job = wait_for_job(client, response.json()["job_ids"][0])

    assert job["filename"] == "evil.pdf"
    assert not (settings.upload_dir.parent / "evil.pdf").exists()
    # Uploaded PDFs are deleted after processing.
    assert list(settings.upload_dir.glob("*.pdf")) == []


def test_failed_job_is_sanitised(settings, tmp_path: Path):
    client_stub = FakeGeminiClient(error=GeminiServiceError("secret upstream detail"))
    app = create_app(settings=settings, gemini_client=client_stub)
    pdf = make_digital_pdf(tmp_path / "invoice.pdf")

    with TestClient(app) as client:
        response = _upload(client, "/upload", pdf)
        job = wait_for_job(client, response.json()["job_ids"][0])

    assert job["status"] == "FAILED"
    assert job["error"] == "The AI service could not process this invoice. Please try again."
    assert "secret upstream detail" not in job["error"]


def test_unknown_job_returns_404(client: TestClient):
    response = client.get("/jobs/does-not-exist")

    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found."


def test_keep_uploads_preserves_file(settings, fake_client: FakeGeminiClient, tmp_path: Path):
    keep = settings.model_copy(update={"keep_uploads": True})
    app = create_app(settings=keep, gemini_client=fake_client)
    pdf = make_digital_pdf(tmp_path / "invoice.pdf")

    with TestClient(app) as client:
        response = _upload(client, "/upload", pdf)
        job = wait_for_job(client, response.json()["job_ids"][0])

    assert job["status"] == "COMPLETED"
    assert len(list(keep.upload_dir.glob("*.pdf"))) == 1


@pytest.mark.parametrize("url", ["/upload", "/upload-approach2"])
def test_both_endpoints_accept_the_same_pdf_shape(client: TestClient, digital_pdf: Path, url: str):
    response = _upload(client, url, digital_pdf)

    assert response.status_code == 200, response.text
    job = wait_for_job(client, response.json()["job_ids"][0])
    assert job["status"] == "COMPLETED"
    assert job["result"]["invoice"]["invoice_number"] == "INV-2026-0042"
