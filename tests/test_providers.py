from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.providers import (
    HttpElevenLabsTranscriptionProvider,
    LLMProviderError,
    LLMTimeoutError,
    MistralLLMProvider,
    TranscriptionProviderError,
)
from app.schemas import TimedTextSegment, TranscriptionResult


class FakeHttpClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def post(self, *_args, **_kwargs):
        self.calls += 1
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _json_response(status_code: int, payload: dict) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        request=httpx.Request("POST", "https://example.com"),
        json=payload,
    )


def _text_response(status_code: int, text: str) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        request=httpx.Request("POST", "https://example.com"),
        text=text,
    )


def _settings() -> Settings:
    return Settings(
        database_url="sqlite+pysqlite:///./providers-test.db",
        task_execution_mode="inline",
        storage_backend="local",
        local_storage_path=".local-storage",
        elevenlabs_api_key="test-eleven-key",
        mistral_api_key="test-mistral-key",
    )


def test_elevenlabs_transcribe_retries_transient_status(tmp_path):
    audio_path = tmp_path / "clip.wav"
    audio_path.write_bytes(b"wav-data")
    provider = HttpElevenLabsTranscriptionProvider(_settings())
    provider._client = FakeHttpClient(
        [
            _json_response(429, {"error": "rate limit"}),
            _json_response(
                200,
                {
                    "language_code": "en",
                    "segments": [{"start_ms": 0, "end_ms": 1200, "text": "Hello world"}],
                },
            ),
        ]
    )

    result = provider.transcribe(audio_path, "en")
    assert result.language_detected == "en"
    assert result.segments[0].text == "Hello world"
    assert provider._client.calls == 2


def test_elevenlabs_transcribe_parses_words_when_segments_missing(tmp_path):
    audio_path = tmp_path / "clip.wav"
    audio_path.write_bytes(b"wav-data")
    provider = HttpElevenLabsTranscriptionProvider(_settings())
    provider._client = FakeHttpClient(
        [
            _json_response(
                200,
                {
                    "language_code": "en",
                    "words": [
                        {"text": "Hello", "start": 0.0, "end": 0.2},
                        {"text": "there.", "start": 0.21, "end": 0.5},
                    ],
                },
            )
        ]
    )

    result = provider.transcribe(audio_path, "en")
    assert len(result.segments) == 1
    assert result.segments[0].text == "Hello there."
    assert result.segments[0].start_ms == 0
    assert result.segments[0].end_ms == 500


def test_elevenlabs_transcribe_raises_with_http_details(tmp_path):
    audio_path = tmp_path / "clip.wav"
    audio_path.write_bytes(b"wav-data")
    provider = HttpElevenLabsTranscriptionProvider(_settings())
    provider._client = FakeHttpClient(
        [
            _text_response(500, "provider crashed"),
            _text_response(500, "provider crashed"),
            _text_response(500, "provider crashed"),
        ]
    )

    with pytest.raises(TranscriptionProviderError, match="HTTP 500"):
        provider.transcribe(audio_path, "en")


def test_mistral_maps_timeout_to_llm_timeout():
    provider = MistralLLMProvider(_settings())
    provider._client = FakeHttpClient([httpx.TimeoutException("timeout")])

    with pytest.raises(LLMTimeoutError):
        provider.rewrite_primary("hello", "clear")


def test_mistral_retries_transient_status_and_parses_content_list():
    provider = MistralLLMProvider(_settings())
    provider._client = FakeHttpClient(
        [
            _json_response(503, {"error": "temporary"}),
            _json_response(
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": [
                                    {"type": "text", "text": "Improved rewrite output"}
                                ]
                            }
                        }
                    ]
                },
            ),
        ]
    )

    rewritten = provider.rewrite_primary("source text", "clear")
    assert rewritten == "Improved rewrite output"
    assert provider._client.calls == 2


def test_mistral_clean_captions_rejects_non_json():
    provider = MistralLLMProvider(_settings())
    provider._client = FakeHttpClient(
        [
            _json_response(
                200,
                {"choices": [{"message": {"content": "not-json"}}]},
            )
        ]
    )

    transcription = TranscriptionResult(
        language_detected="en",
        segments=[TimedTextSegment(start_ms=0, end_ms=1000, text="hello")],
    )
    with pytest.raises(LLMProviderError, match="valid JSON"):
        provider.clean_captions(transcription, include_timestamps=True)


def test_voice_cloning_provider_prefers_dedicated_voice_key():
    settings = Settings(
        database_url="sqlite+pysqlite:///./providers-test.db",
        task_execution_mode="inline",
        storage_backend="local",
        local_storage_path=".local-storage",
        elevenlabs_api_key="transcription-key",
        elevenlabs_voice_api_key="voice-key",
        mistral_api_key="test-mistral-key",
    )
    provider = HttpElevenLabsTranscriptionProvider(settings)
    assert provider._settings.elevenlabs_api_key == "transcription-key"

    from app.providers import ElevenLabsVoiceCloningProvider

    voice_provider = ElevenLabsVoiceCloningProvider(settings)
    assert voice_provider._api_key == "voice-key"
