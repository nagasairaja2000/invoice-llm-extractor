"""Tests for the background queue manager."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.exceptions import GeminiServiceError
from app.schemas.job import JobStatus
from app.services.queue_manager import QueueManager


def _wait(queue: QueueManager, job_id: str, timeout: float = 10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = queue.get_job(job_id)
        if job and job.status in {JobStatus.COMPLETED, JobStatus.FAILED}:
            return job
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def _upload(tmp_path: Path) -> Path:
    path = tmp_path / "temp.pdf"
    path.write_bytes(b"%PDF-1.4 fake")
    return path


def test_successful_job(tmp_path: Path, settings):
    queue = QueueManager(settings)
    path = _upload(tmp_path)
    try:
        job_id = queue.submit("temp.pdf", path, lambda p: {"invoice": {"x": 1}}, "Approach 1")
        job = _wait(queue, job_id)

        assert job.status == JobStatus.COMPLETED
        assert job.result == {"invoice": {"x": 1}}
        assert job.error is None
        assert job.filename == "temp.pdf"
        # Uploaded files are deleted after processing by default.
        assert not path.exists()
    finally:
        queue.shutdown()


def test_failed_job_returns_safe_message(tmp_path: Path, settings):
    queue = QueueManager(settings)
    path = _upload(tmp_path)

    def _fail(_path):
        raise GeminiServiceError("internal details that must not leak")

    try:
        job_id = queue.submit("temp.pdf", path, _fail, "Approach 2")
        job = _wait(queue, job_id)

        assert job.status == JobStatus.FAILED
        assert job.error == "The AI service could not process this invoice. Please try again."
        assert "internal details" not in (job.error or "")
    finally:
        queue.shutdown()


def test_unexpected_error_is_sanitised(tmp_path: Path, settings):
    queue = QueueManager(settings)
    path = _upload(tmp_path)

    def _fail(_path):
        raise ValueError("secret stack info")

    try:
        job_id = queue.submit("temp.pdf", path, _fail, "Approach 1")
        job = _wait(queue, job_id)

        assert job.status == JobStatus.FAILED
        assert job.error == "Invoice extraction failed. Please try again."
    finally:
        queue.shutdown()


def test_keep_uploads_preserves_file(tmp_path: Path, settings):
    keep = settings.model_copy(update={"keep_uploads": True})
    queue = QueueManager(keep)
    path = _upload(tmp_path)
    try:
        job_id = queue.submit("temp.pdf", path, lambda p: {}, "Approach 1")
        job = _wait(queue, job_id)
        assert job.status == JobStatus.COMPLETED
        assert path.exists()
    finally:
        queue.shutdown()


def test_unknown_job_returns_none(settings):
    queue = QueueManager(settings)
    try:
        assert queue.get_job("missing") is None
    finally:
        queue.shutdown()


def test_submit_after_shutdown_raises(tmp_path: Path, settings):
    queue = QueueManager(settings)
    queue.shutdown()
    with pytest.raises(RuntimeError):
        queue.submit("temp.pdf", _upload(tmp_path), lambda p: {}, "Approach 1")


def test_jobs_are_listed_in_creation_order(tmp_path: Path, settings):
    queue = QueueManager(settings)
    try:
        first = queue.submit("a.pdf", _upload(tmp_path), lambda p: {}, "Approach 1")
        second = queue.submit("b.pdf", _upload(tmp_path), lambda p: {}, "Approach 2")
        _wait(queue, first)
        _wait(queue, second)

        jobs = queue.get_jobs()
        assert [job.id for job in jobs] == [first, second]
    finally:
        queue.shutdown()
