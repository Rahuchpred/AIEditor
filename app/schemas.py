from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

class TimedTextSegment(BaseModel):
    start_ms: int | None = None
    end_ms: int | None = None
    text: str


class TranscriptPayload(BaseModel):
    language_detected: str | None = None
    segments: list[TimedTextSegment]


class CorrectedCaptions(BaseModel):
    segments: list[TimedTextSegment]
    full_text: str


class ProcessingMetrics(BaseModel):
    transcription_provider: str
    llm_provider: str
    transcription_ms: int
    llm_ms: int
    total_ms: int


class ResultInputMetadata(BaseModel):
    media_type: str
    duration_seconds: float
    style_mode: str
    style_value: str


class AnalysisJobAccepted(BaseModel):
    job_id: str
    status: str
    status_url: str
    result_url: str


class AnalysisJobStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: str
    status: str
    created_at: str
    updated_at: str
    error_code: str | None = None
    error_message: str | None = None


class AnalysisJobResult(BaseModel):
    job_id: str
    input: ResultInputMetadata
    transcript: TranscriptPayload
    processing_metrics: ProcessingMetrics


class TranscriptionResult(BaseModel):
    language_detected: str | None = None
    segments: list[TimedTextSegment]


class MediaInfo(BaseModel):
    media_type: str
    size_bytes: int
    duration_seconds: float


class ProviderResponseError(BaseModel):
    detail: str
    metadata: dict[str, Any] | None = None


# --- Reel Generator schemas ---


class ReelScript(BaseModel):
    """Viral Instagram reel script with hook, body, CTA."""

    hook: str
    body: list[str]
    cta: str
    full_narration: str
    hashtags: list[str]


class VoiceProfile(BaseModel):
    """ElevenLabs cloned voice profile."""

    voice_id: str
    name: str


class ReelScriptRequest(BaseModel):
    """Request to generate a reel script."""

    rough_idea: str
    clip_count: int = 5

