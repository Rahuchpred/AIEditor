from __future__ import annotations

from celery import Celery

from app.container import get_container, get_settings

settings = get_settings()
celery_app = Celery(
    "aiedit_feature4",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.task_ignore_result = True


@celery_app.task(name="app.tasks.process_analysis_job")
def process_analysis_job(job_id: str) -> None:
    container = get_container()
    container.create_analysis_service().process_job(job_id)
