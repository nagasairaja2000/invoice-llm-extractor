"""Background job queue with bounded concurrency and cleanup."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any

from app.config import Settings
from app.exceptions import AppError
from app.schemas.job import JobPublic, JobStatus, utc_now_iso
from app.utils.files import remove_file

logger = logging.getLogger(__name__)

JobCallback = Callable[[Path], dict[str, Any]]


@dataclass
class Job:
    id: str
    filename: str
    approach: str
    file_path: Path
    callback: JobCallback
    status: JobStatus = JobStatus.QUEUED
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    created_ts: float = field(default_factory=time.time)
    updated_ts: float = field(default_factory=time.time)

    def to_public(self) -> JobPublic:
        return JobPublic(
            id=self.id,
            filename=self.filename,
            approach=self.approach,
            status=self.status,
            result=self.result,
            error=self.error,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class QueueManager:
    """Runs extraction callbacks in a bounded thread pool.

    ``ThreadPoolExecutor`` already provides a queue, so no separate dispatcher
    thread is needed.
    """

    def __init__(self, settings: Settings, max_workers: int | None = None):
        self.settings = settings
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers or settings.worker_threads,
            thread_name_prefix="invoice-worker",
        )
        self._jobs: dict[str, Job] = {}
        self._lock = RLock()
        self._closed = False

    def submit(
        self,
        filename: str,
        file_path: Path,
        callback: JobCallback,
        approach: str,
    ) -> str:
        job_id = uuid.uuid4().hex
        job = Job(
            id=job_id,
            filename=filename,
            approach=approach,
            file_path=Path(file_path),
            callback=callback,
        )

        with self._lock:
            if self._closed:
                raise RuntimeError("The job queue has been shut down.")
            self._cleanup_locked()
            self._jobs[job_id] = job

        self.executor.submit(self._run_job, job_id)
        logger.info("Queued job %s (%s) for %s", job_id, approach, filename)
        return job_id

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = JobStatus.PROCESSING
            job.updated_at = utc_now_iso()
            job.updated_ts = time.time()

        file_path = job.file_path
        result: dict[str, Any] | None = None
        error: str | None = None
        status = JobStatus.FAILED

        try:
            result = job.callback(file_path)
            status = JobStatus.COMPLETED
        except AppError as exc:
            logger.warning("Job %s failed: %s", job_id, exc)
            error = exc.public_message
        except Exception:
            logger.exception("Job %s failed unexpectedly.", job_id)
            error = "Invoice extraction failed. Please try again."
        finally:
            # Remove the temporary upload before flipping the job to a
            # terminal state, so a client that observes COMPLETED/FAILED can
            # rely on the file already being gone.
            if not self.settings.keep_uploads:
                remove_file(file_path)

        with self._lock:
            job.result = result
            job.error = error
            job.status = status
            job.updated_at = utc_now_iso()
            job.updated_ts = time.time()

        if status == JobStatus.COMPLETED:
            logger.info("Job %s completed.", job_id)

    def get_job(self, job_id: str) -> JobPublic | None:
        with self._lock:
            self._cleanup_locked()
            job = self._jobs.get(job_id)
            return job.to_public() if job else None

    def get_jobs(self) -> list[JobPublic]:
        with self._lock:
            self._cleanup_locked()
            jobs = sorted(self._jobs.values(), key=lambda item: item.created_ts)
            return [job.to_public() for job in jobs]

    def _cleanup_locked(self) -> None:
        """Remove expired jobs and cap the in-memory job store."""
        now = time.time()
        terminal = {JobStatus.COMPLETED, JobStatus.FAILED}

        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if job.status in terminal
            and now - job.updated_ts > self.settings.job_ttl_seconds
        ]
        for job_id in expired:
            self._jobs.pop(job_id, None)

        if len(self._jobs) <= self.settings.max_jobs:
            return

        removable = sorted(
            (
                job
                for job in self._jobs.values()
                if job.status in terminal
            ),
            key=lambda item: item.created_ts,
        )
        for job in removable:
            if len(self._jobs) <= self.settings.max_jobs:
                break
            self._jobs.pop(job.id, None)

    def shutdown(self, wait: bool = False) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            pending = [
                job
                for job in self._jobs.values()
                if job.status in {JobStatus.QUEUED, JobStatus.PROCESSING}
            ]

        self.executor.shutdown(wait=wait, cancel_futures=True)

        if not self.settings.keep_uploads:
            for job in pending:
                remove_file(job.file_path)
