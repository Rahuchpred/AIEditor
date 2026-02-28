from __future__ import annotations

from fastapi import APIRouter, File, Form, Request, UploadFile

from app.container import get_container
from app.schemas import AnalysisJobAccepted, AnalysisJobResult, AnalysisJobStatus

router = APIRouter()


def _service_from_request(request: Request):
    container = getattr(request.app.state, "container", None) or get_container()
    return container.create_analysis_service()


@router.get("/healthz")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/v1/analysis-jobs", response_model=AnalysisJobAccepted, status_code=202)
async def create_analysis_job(
    request: Request,
    media_file: UploadFile = File(...),
    style_mode: str = Form(...),
    style_value: str = Form(...),
    input_language_hint: str | None = Form(default=None),
    include_raw_transcript: bool = Form(default=True),
    include_timestamps: bool = Form(default=True),
) -> AnalysisJobAccepted:
    service = _service_from_request(request)
    return service.create_job(
        upload_file=media_file,
        style_mode=style_mode,
        style_value=style_value,
        input_language_hint=input_language_hint,
        include_raw_transcript=include_raw_transcript,
        include_timestamps=include_timestamps,
    )


@router.get("/v1/analysis-jobs/{job_id}", response_model=AnalysisJobStatus)
def get_analysis_job_status(request: Request, job_id: str) -> AnalysisJobStatus:
    service = _service_from_request(request)
    return service.get_status(job_id)


@router.get("/v1/analysis-jobs/{job_id}/result", response_model=AnalysisJobResult)
def get_analysis_job_result(request: Request, job_id: str) -> AnalysisJobResult:
    service = _service_from_request(request)
    return service.get_result(job_id)
