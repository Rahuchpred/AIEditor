from __future__ import annotations

from app.constants import ErrorCode, JobStatus
from app.models import AnalysisJob, utc_now
from app.providers import LLMProviderError, LLMTimeoutError, TranscriptionProviderError


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
        style_mode="preset",
        style_value="clear",
    )

    context.service.process_job(job_id)

    result_response = context.client.get(f"/v1/analysis-jobs/{job_id}/result")
    assert result_response.status_code == 200
    body = result_response.json()
    assert body["captions_corrected_en"]["full_text"] == "Clean English caption."
    assert body["rewrite_primary_en"] == "clear: Clean English caption."
    assert body["speaking_tips_en"] == [
        "Use shorter sentences.",
        "Replace vague words with concrete ones.",
        "Open with the main point.",
    ]


def test_submit_non_english_audio_translates_to_english(context_factory, wav_bytes):
    context = context_factory(language_detected="es", transcript_text="hola mundo")
    job_id = _create_job(
        context.client,
        "speech.wav",
        wav_bytes,
        "audio/wav",
        style_mode="preset",
        style_value="smart",
    )

    context.service.process_job(job_id)

    result_response = context.client.get(f"/v1/analysis-jobs/{job_id}/result")
    assert result_response.status_code == 200
    body = result_response.json()
    assert body["transcript_raw"]["language_detected"] == "es"
    assert body["captions_corrected_en"]["full_text"] == "Translated English caption."
    assert body["rewrite_primary_en"] == "smart: Translated English caption."


def test_submit_valid_video_extracts_audio_before_transcription(context_factory):
    context = context_factory()
    job_id = _create_job(
        context.client,
        "clip.mp4",
        b"fake-video-payload",
        "video/mp4",
        style_mode="preset",
        style_value="friendly",
    )

    context.service.process_job(job_id)

    assert context.media_processor.normalized_calls == 1
    result_response = context.client.get(f"/v1/analysis-jobs/{job_id}/result")
    assert result_response.status_code == 200
    assert result_response.json()["input"]["media_type"] == "video"


def test_submit_with_preset_style_validates_preset(context_factory, wav_bytes):
    context = context_factory()
    response = context.client.post(
        "/v1/analysis-jobs",
        files={"media_file": ("speech.wav", wav_bytes, "audio/wav")},
        data={"style_mode": "preset", "style_value": "not-a-style"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == ErrorCode.INVALID_STYLE_VALUE


def test_submit_with_custom_style_respects_free_text_style(context_factory, wav_bytes):
    context = context_factory()
    job_id = _create_job(
        context.client,
        "speech.wav",
        wav_bytes,
        "audio/wav",
        style_mode="custom",
        style_value="Paul Graham",
    )

    context.service.process_job(job_id)

    result_response = context.client.get(f"/v1/analysis-jobs/{job_id}/result")
    assert result_response.status_code == 200
    assert result_response.json()["rewrite_primary_en"] == "Paul Graham: Clean English caption."


def test_submit_unsupported_file_type_returns_error(context_factory):
    context = context_factory()
    response = context.client.post(
        "/v1/analysis-jobs",
        files={"media_file": ("notes.txt", b"text", "text/plain")},
        data={"style_mode": "preset", "style_value": "clear"},
    )

    assert response.status_code == 415
    assert response.json()["detail"]["code"] == ErrorCode.UNSUPPORTED_MEDIA_TYPE


def test_submit_oversized_file_returns_error(context_factory):
    context = context_factory(media_max_bytes=8)
    response = context.client.post(
        "/v1/analysis-jobs",
        files={"media_file": ("speech.wav", b"0123456789", "audio/wav")},
        data={"style_mode": "preset", "style_value": "clear"},
    )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == ErrorCode.FILE_TOO_LARGE


def test_submit_over_duration_limit_returns_error(context_factory, wav_bytes):
    context = context_factory(media_duration=901.0, media_max_duration_seconds=900)
    response = context.client.post(
        "/v1/analysis-jobs",
        files={"media_file": ("speech.wav", wav_bytes, "audio/wav")},
        data={"style_mode": "preset", "style_value": "clear"},
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
        style_mode="preset",
        style_value="clear",
    )

    context.service.process_job(job_id)

    status_response = context.client.get(f"/v1/analysis-jobs/{job_id}")
    assert status_response.status_code == 200
    body = status_response.json()
    assert body["status"] == JobStatus.FAILED
    assert body["error_code"] == ErrorCode.TRANSCRIPTION_FAILED


def test_llm_timeout_marks_job_failed(context_factory, wav_bytes):
    context = context_factory(
        llm_failure=LLMTimeoutError("timed out"),
    )
    job_id = _create_job(
        context.client,
        "speech.wav",
        wav_bytes,
        "audio/wav",
        style_mode="preset",
        style_value="clear",
    )

    context.service.process_job(job_id)

    status_response = context.client.get(f"/v1/analysis-jobs/{job_id}")
    assert status_response.status_code == 200
    body = status_response.json()
    assert body["status"] == JobStatus.FAILED
    assert body["error_code"] == ErrorCode.LLM_TIMEOUT


def test_status_endpoint_reports_processing_before_completion(context_factory, wav_bytes):
    context = context_factory()
    job_id = _create_job(
        context.client,
        "speech.wav",
        wav_bytes,
        "audio/wav",
        style_mode="preset",
        style_value="clear",
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
        style_mode="preset",
        style_value="clear",
    )

    result_response = context.client.get(f"/v1/analysis-jobs/{job_id}/result")
    assert result_response.status_code == 404
    assert result_response.json()["detail"]["code"] == ErrorCode.RESULT_NOT_READY


def test_timestamps_are_preserved_in_corrected_segments(context_factory, wav_bytes):
    context = context_factory()
    job_id = _create_job(
        context.client,
        "speech.wav",
        wav_bytes,
        "audio/wav",
        style_mode="preset",
        style_value="clear",
    )

    context.service.process_job(job_id)

    result_response = context.client.get(f"/v1/analysis-jobs/{job_id}/result")
    body = result_response.json()
    assert body["transcript_raw"]["segments"][0]["start_ms"] == 0
    assert body["transcript_raw"]["segments"][0]["end_ms"] == 1800
    assert body["captions_corrected_en"]["segments"][0]["start_ms"] == 0
    assert body["captions_corrected_en"]["segments"][0]["end_ms"] == 1800


def test_tips_are_exactly_three_strings_and_rewrite_is_single_string(context_factory, wav_bytes):
    context = context_factory()
    job_id = _create_job(
        context.client,
        "speech.wav",
        wav_bytes,
        "audio/wav",
        style_mode="preset",
        style_value="professional",
    )

    context.service.process_job(job_id)

    result_response = context.client.get(f"/v1/analysis-jobs/{job_id}/result")
    body = result_response.json()
    assert len(body["speaking_tips_en"]) == 3
    assert all(isinstance(tip, str) for tip in body["speaking_tips_en"])
    assert isinstance(body["rewrite_primary_en"], str)
    assert body["rewrite_primary_en"] == "professional: Clean English caption."


def test_generic_llm_provider_error_marks_job_failed(context_factory, wav_bytes):
    context = context_factory(
        llm_failure=LLMProviderError("bad output"),
    )
    job_id = _create_job(
        context.client,
        "speech.wav",
        wav_bytes,
        "audio/wav",
        style_mode="preset",
        style_value="clear",
    )

    context.service.process_job(job_id)

    status_response = context.client.get(f"/v1/analysis-jobs/{job_id}")
    assert status_response.status_code == 200
    body = status_response.json()
    assert body["status"] == JobStatus.FAILED
    assert body["error_code"] == ErrorCode.LLM_PROVIDER_ERROR
