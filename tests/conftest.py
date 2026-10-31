"""Pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.helpers import (
    FakeGeminiClient,
    make_digital_pdf,
    make_encrypted_pdf,
    make_mixed_pdf,
    make_scanned_pdf,
)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        gemini_api_key="test-key",
        upload_dir=tmp_path / "uploads",
        gemini_max_retries=1,
        gemini_retry_base_seconds=0.01,
        gemini_retry_max_seconds=0.02,
        worker_threads=2,
        ocr_timeout_seconds=30,
    )


@pytest.fixture
def fake_client() -> FakeGeminiClient:
    return FakeGeminiClient()


@pytest.fixture
def digital_pdf(tmp_path: Path) -> Path:
    return make_digital_pdf(tmp_path / "digital.pdf", pages=1)


@pytest.fixture
def multi_page_pdf(tmp_path: Path) -> Path:
    return make_digital_pdf(tmp_path / "multi.pdf", pages=3)


@pytest.fixture
def scanned_pdf(tmp_path: Path) -> Path:
    return make_scanned_pdf(tmp_path / "scanned.pdf")


@pytest.fixture
def mixed_pdf(tmp_path: Path) -> Path:
    return make_mixed_pdf(tmp_path / "mixed.pdf")


@pytest.fixture
def encrypted_pdf(tmp_path: Path) -> Path:
    return make_encrypted_pdf(tmp_path / "encrypted.pdf")


@pytest.fixture
def app(settings: Settings, fake_client: FakeGeminiClient):
    return create_app(settings=settings, gemini_client=fake_client)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client
