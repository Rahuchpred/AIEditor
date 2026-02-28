from __future__ import annotations

import io
import wave
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.constants import ErrorCode, SUPPORTED_MEDIA_TYPES
from app.container import AppContainer
from app.db import build_engine, build_session_factory, init_database
from app.errors import ServiceError
from app.main import create_app
from app.providers import LLMProviderError, LLMTimeoutError, TranscriptionProviderError
from app.queueing import NoOpTaskDispatcher
from app.schemas import CorrectedCaptions, MediaInfo, TimedTextSegment, TranscriptionResult
from app.storage import LocalObjectStorageClient


class FakeMediaProcessor:
    def __init__(self, duration_seconds: float = 5.0):
        self.duration_seconds = duration_seconds
        self.normalized_calls = 0

    def inspect(self, file_path, content_type: str) -> MediaInfo:
        media_type = SUPPORTED_MEDIA_TYPES.get(content_type)
        if media_type is None:
            raise ServiceError(
                code=ErrorCode.UNSUPPORTED_MEDIA_TYPE,
                message=f"Unsupported content type: {content_type}",
                status_code=415,
            )
        return MediaInfo(
            media_type=media_type,
            size_bytes=file_path.stat().st_size,
            duration_seconds=self.duration_seconds,
        )

    def normalize_to_wav(self, input_path, output_path) -> None:
        self.normalized_calls += 1
        output_path.write_bytes(input_path.read_bytes() or b"normalized")


class FakeTranscriptionProvider:
    def __init__(
        self,
        language_detected: str = "en",
        text: str = "Hello from the transcript.",
        failure: Exception | None = None,
    ):
        self.language_detected = language_detected
        self.text = text
        self.failure = failure

    def transcribe(self, audio_path, language_hint: str | None) -> TranscriptionResult:
        if self.failure:
            raise self.failure
        return TranscriptionResult(
            language_detected=self.language_detected,
            segments=[
                TimedTextSegment(
                    start_ms=0,
                    end_ms=1800,
                    text=self.text,
                )
            ],
        )


class FakeLLMProvider:
    def __init__(self, failure: Exception | None = None):
        self.failure = failure

    def clean_captions(self, transcription: TranscriptionResult, include_timestamps: bool) -> CorrectedCaptions:
        if self.failure:
            raise self.failure

        cleaned_text = (
            "Translated English caption."
            if transcription.language_detected and transcription.language_detected != "en"
            else "Clean English caption."
        )
        segments = [
            TimedTextSegment(
                start_ms=segment.start_ms if include_timestamps else None,
                end_ms=segment.end_ms if include_timestamps else None,
                text=cleaned_text,
            )
            for segment in transcription.segments
        ]
        return CorrectedCaptions(segments=segments, full_text=" ".join(segment.text for segment in segments))

    def rewrite_primary(self, corrected_text: str, style_value: str) -> str:
        if self.failure:
            raise self.failure
        return f"{style_value}: {corrected_text}"

    def speaking_tips(self, corrected_text: str, style_value: str) -> list[str]:
        if self.failure:
            raise self.failure
        return [
            "Use shorter sentences.",
            "Replace vague words with concrete ones.",
            "Open with the main point.",
        ]


@dataclass
class TestContext:
    client: TestClient
    container: AppContainer
    media_processor: FakeMediaProcessor
    transcription_provider: FakeTranscriptionProvider
    llm_provider: FakeLLMProvider

    @property
    def service(self):
        return self.container.create_analysis_service()

    def close(self) -> None:
        self.client.close()


def make_wav_bytes(duration_seconds: float = 1.0, frame_rate: int = 8000) -> bytes:
    frame_count = max(1, int(duration_seconds * frame_rate))
    raw_frames = b"\x00\x00" * frame_count
    with io.BytesIO() as buffer:
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(frame_rate)
            wav_file.writeframes(raw_frames)
        return buffer.getvalue()


@pytest.fixture
def context_factory(tmp_path):
    created_contexts: list[TestContext] = []

    def _factory(
        *,
        media_duration: float = 5.0,
        language_detected: str = "en",
        transcript_text: str = "Hello from the transcript.",
        transcription_failure: Exception | None = None,
        llm_failure: Exception | None = None,
        media_max_bytes: int | None = None,
        media_max_duration_seconds: int = 900,
    ) -> TestContext:
        settings = Settings(
            database_url=f"sqlite+pysqlite:///{tmp_path / f'test-{len(created_contexts)}.db'}",
            task_execution_mode="queue",
            storage_backend="local",
            local_storage_path=str(tmp_path / f"storage-{len(created_contexts)}"),
            media_max_bytes=media_max_bytes or 200 * 1024 * 1024,
            media_max_duration_seconds=media_max_duration_seconds,
        )
        engine = build_engine(settings.database_url)
        init_database(engine)
        session_factory = build_session_factory(engine)

        media_processor = FakeMediaProcessor(duration_seconds=media_duration)
        transcription_provider = FakeTranscriptionProvider(
            language_detected=language_detected,
            text=transcript_text,
            failure=transcription_failure,
        )
        llm_provider = FakeLLMProvider(failure=llm_failure)

        container = AppContainer(
            settings=settings,
            session_factory=session_factory,
            storage=LocalObjectStorageClient(settings.local_storage_path),
            media_processor=media_processor,
            transcription_provider=transcription_provider,
            llm_provider=llm_provider,
            task_dispatcher=NoOpTaskDispatcher(),
        )
        client = TestClient(create_app(container))
        context = TestContext(
            client=client,
            container=container,
            media_processor=media_processor,
            transcription_provider=transcription_provider,
            llm_provider=llm_provider,
        )
        created_contexts.append(context)
        return context

    yield _factory

    for context in created_contexts:
        context.close()


@pytest.fixture
def wav_bytes() -> bytes:
    return make_wav_bytes()
