from __future__ import annotations

from enum import StrEnum


class JobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class StyleMode(StrEnum):
    PRESET = "preset"
    CUSTOM = "custom"


class ErrorCode(StrEnum):
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    DURATION_LIMIT_EXCEEDED = "DURATION_LIMIT_EXCEEDED"
    TRANSCRIPTION_FAILED = "TRANSCRIPTION_FAILED"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    LLM_PROVIDER_ERROR = "LLM_PROVIDER_ERROR"
    INVALID_STYLE_VALUE = "INVALID_STYLE_VALUE"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    RESULT_NOT_READY = "RESULT_NOT_READY"


PRESET_STYLES = frozenset({"clear", "confident", "smart", "friendly", "professional"})
SUPPORTED_MEDIA_TYPES = {
    "video/mp4": "video",
    "video/quicktime": "video",
    "video/webm": "video",
    "audio/mpeg": "audio",
    "audio/wav": "audio",
    "audio/mp4": "audio",
    "audio/x-m4a": "audio",
}

DEFAULT_MAX_BYTES = 200 * 1024 * 1024
DEFAULT_MAX_DURATION_SECONDS = 15 * 60
DEFAULT_TIPS_COUNT = 3
DEFAULT_ENGLISH_LANGUAGE_CODE = "en"
