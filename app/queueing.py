from __future__ import annotations

from typing import Protocol


class TaskDispatcher(Protocol):
    def enqueue(self, job_id: str) -> None:
        ...


class CeleryTaskDispatcher:
    def enqueue(self, job_id: str) -> None:
        from app.tasks import process_analysis_job

        process_analysis_job.delay(job_id)


class NoOpTaskDispatcher:
    def enqueue(self, job_id: str) -> None:
        return None
