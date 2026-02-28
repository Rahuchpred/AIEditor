from __future__ import annotations

from app.constants import ErrorCode, JobStatus
from app.models import AnalysisJob, utc_now
from app.providers import TranscriptionProviderError


def _create_job(client, file_name: str, payload: bytes, content_type: str, **data):
    response = client.post(
        "/v1/analysis-jobs",
        files={"media_file": (file_name, payload, content_type)},
        data=data,
    )
    assert response.status_code == 202, response.text
    return response.json()["job_id"]


def test_submit_valid_english_audio_returns_cleaned_result(context_factory, wav_bytes):
    context = context_factory()
    job_id = _create_job(
        context.client,
        "speech.wav",
        wav_bytes,
        "audio/wav",
    )

    context.service.process_job(job_id)

    result_response = context.client.get(f"/v1/analysis-jobs/{job_id}/result")
    assert result_response.status_code == 200
    body = result_response.json()
    assert body["transcript"]["language_detected"] == "en"
    assert body["transcript"]["segments"][0]["text"] == "Hello from the transcript."


def test_submit_non_english_audio_translates_to_english(context_factory, wav_bytes):
    context = context_factory(language_detected="es", transcript_text="hola mundo")
    job_id = _create_job(
        context.client,
        "speech.wav",
        wav_bytes,
        "audio/wav",
    )

    context.service.process_job(job_id)

    result_response = context.client.get(f"/v1/analysis-jobs/{job_id}/result")
    assert result_response.status_code == 200
    body = result_response.json()
    assert body["transcript"]["language_detected"] == "es"
    assert body["transcript"]["segments"][0]["text"] == "hola mundo"


def test_submit_valid_video_extracts_audio_before_transcription(context_factory):
    context = context_factory()
    job_id = _create_job(
        context.client,
        "clip.mp4",
        b"fake-video-payload",
        "video/mp4",
    )

    context.service.process_job(job_id)

    assert context.media_processor.normalized_calls == 1
    result_response = context.client.get(f"/v1/analysis-jobs/{job_id}/result")
    assert result_response.status_code == 200
    assert result_response.json()["input"]["media_type"] == "video"


def test_submit_unsupported_file_type_returns_error(context_factory):
    context = context_factory()
    response = context.client.post(
        "/v1/analysis-jobs",
        files={"media_file": ("notes.txt", b"text", "text/plain")},
    )

    assert response.status_code == 415
    assert response.json()["detail"]["code"] == ErrorCode.UNSUPPORTED_MEDIA_TYPE


def test_submit_oversized_file_returns_error(context_factory):
    context = context_factory(media_max_bytes=8)
    response = context.client.post(
        "/v1/analysis-jobs",
        files={"media_file": ("speech.wav", b"0123456789", "audio/wav")},
    )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == ErrorCode.FILE_TOO_LARGE


def test_submit_over_duration_limit_returns_error(context_factory, wav_bytes):
    context = context_factory(media_duration=901.0, media_max_duration_seconds=900)
    response = context.client.post(
        "/v1/analysis-jobs",
        files={"media_file": ("speech.wav", wav_bytes, "audio/wav")},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == ErrorCode.DURATION_LIMIT_EXCEEDED


def test_transcription_failure_marks_job_failed(context_factory, wav_bytes):
    context = context_factory(
        transcription_failure=TranscriptionProviderError("provider down"),
    )
    job_id = _create_job(
        context.client,
        "speech.wav",
        wav_bytes,
        "audio/wav",
    )

    context.service.process_job(job_id)

    status_response = context.client.get(f"/v1/analysis-jobs/{job_id}")
    assert status_response.status_code == 200
    body = status_response.json()
    assert body["status"] == JobStatus.FAILED
    assert body["error_code"] == ErrorCode.TRANSCRIPTION_FAILED


def test_status_endpoint_reports_processing_before_completion(context_factory, wav_bytes):
    context = context_factory()
    job_id = _create_job(
        context.client,
        "speech.wav",
        wav_bytes,
        "audio/wav",
    )

    with context.container.session_factory() as session:
        job = session.get(AnalysisJob, job_id)
        job.status = JobStatus.PROCESSING
        job.updated_at = utc_now()
        session.commit()

    status_response = context.client.get(f"/v1/analysis-jobs/{job_id}")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == JobStatus.PROCESSING


def test_result_endpoint_returns_404_before_completion(context_factory, wav_bytes):
    context = context_factory()
    job_id = _create_job(
        context.client,
        "speech.wav",
        wav_bytes,
        "audio/wav",
    )

    result_response = context.client.get(f"/v1/analysis-jobs/{job_id}/result")
    assert result_response.status_code == 404
    assert result_response.json()["detail"]["code"] == ErrorCode.RESULT_NOT_READY


def test_timestamps_are_preserved_in_transcript_segments(context_factory, wav_bytes):
    context = context_factory()
    job_id = _create_job(
        context.client,
        "speech.wav",
        wav_bytes,
        "audio/wav",
    )

    context.service.process_job(job_id)

    result_response = context.client.get(f"/v1/analysis-jobs/{job_id}/result")
    body = result_response.json()
    assert body["transcript"]["segments"][0]["start_ms"] == 0
    assert body["transcript"]["segments"][0]["end_ms"] == 1800


def test_timestamps_can_be_disabled_in_transcript_segments(context_factory, wav_bytes):
    context = context_factory()
    job_id = _create_job(
        context.client,
        "speech.wav",
        wav_bytes,
        "audio/wav",
        include_timestamps=False,
    )

    context.service.process_job(job_id)

    result_response = context.client.get(f"/v1/analysis-jobs/{job_id}/result")
    body = result_response.json()
    assert body["transcript"]["segments"][0]["start_ms"] is None
    assert body["transcript"]["segments"][0]["end_ms"] is None
