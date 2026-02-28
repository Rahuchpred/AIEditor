from __future__ import annotations

import json
import time
from typing import Any, Protocol

import httpx

from app.config import Settings
from app.constants import DEFAULT_ENGLISH_LANGUAGE_CODE, DEFAULT_TIPS_COUNT
from app.prompts import build_caption_cleanup_prompt, build_rewrite_prompt, build_tips_prompt
from app.schemas import CorrectedCaptions, TimedTextSegment, TranscriptionResult


class TranscriptionProviderError(RuntimeError):
    pass


class LLMProviderError(RuntimeError):
    pass


class LLMTimeoutError(LLMProviderError):
    pass


class TranscriptionProvider(Protocol):
    def transcribe(self, audio_path, language_hint: str | None) -> TranscriptionResult:
        ...


class LLMProvider(Protocol):
    def clean_captions(self, transcription: TranscriptionResult, include_timestamps: bool) -> CorrectedCaptions:
        ...

    def rewrite_primary(self, corrected_text: str, style_value: str) -> str:
        ...

    def speaking_tips(self, corrected_text: str, style_value: str) -> list[str]:
        ...


class HttpElevenLabsTranscriptionProvider:
    _MAX_ATTEMPTS = 3

    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = httpx.Client(timeout=settings.provider_timeout_seconds)

    def transcribe(self, audio_path, language_hint: str | None) -> TranscriptionResult:
        if not self._settings.elevenlabs_api_key:
            raise TranscriptionProviderError("Missing ElevenLabs API key")

        payload = {"model_id": self._settings.elevenlabs_model_id}
        if language_hint:
            payload["language_code"] = language_hint

        try:
            with open(audio_path, "rb") as audio_handle:
                response = self._post_with_retries(
                    self._settings.elevenlabs_api_url,
                    headers={"xi-api-key": self._settings.elevenlabs_api_key},
                    data=payload,
                    files={"file": (audio_path.name, audio_handle, "audio/wav")},
                )
        except httpx.TimeoutException as exc:
            raise TranscriptionProviderError("ElevenLabs transcription timed out") from exc
        except httpx.HTTPError as exc:
            raise TranscriptionProviderError("ElevenLabs transcription request failed") from exc

        if response.status_code >= 400:
            detail = _safe_http_error_detail(response)
            raise TranscriptionProviderError(
                f"ElevenLabs transcription returned HTTP {response.status_code}: {detail}"
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise TranscriptionProviderError("ElevenLabs transcription returned invalid JSON") from exc

        segments = self._extract_segments(body)
        if not segments:
            raise TranscriptionProviderError("ElevenLabs transcription returned no segments")

        language_detected = body.get("language_code") or body.get("language") or body.get("detected_language")
        return TranscriptionResult(language_detected=language_detected, segments=segments)

    def _extract_segments(self, body: dict[str, Any]) -> list[TimedTextSegment]:
        raw_segments = body.get("segments") or []
        if raw_segments:
            parsed_segments: list[TimedTextSegment] = []
            for segment in raw_segments:
                text = str(segment.get("text", "")).strip()
                if not text:
                    continue
                parsed_segments.append(
                    TimedTextSegment(
                        start_ms=_to_millis(segment.get("start_ms", segment.get("start"))),
                        end_ms=_to_millis(segment.get("end_ms", segment.get("end"))),
                        text=text,
                    )
                )
            if parsed_segments:
                return parsed_segments

        words = body.get("words") or []
        if isinstance(words, list) and words:
            word_segments: list[TimedTextSegment] = []
            for token in words:
                token_text = str(token.get("text") or token.get("word") or "").strip()
                if not token_text:
                    continue
                word_segments.append(
                    TimedTextSegment(
                        start_ms=_to_millis(token.get("start_ms", token.get("start"))),
                        end_ms=_to_millis(token.get("end_ms", token.get("end"))),
                        text=token_text,
                    )
                )
            if word_segments:
                return _merge_word_segments(word_segments)

        text = str(body.get("text", "")).strip()
        if not text:
            return []
        return [TimedTextSegment(start_ms=0, end_ms=None, text=text)]

    def _post_with_retries(self, url: str, **kwargs: Any) -> httpx.Response:
        response: httpx.Response | None = None
        for attempt in range(1, self._MAX_ATTEMPTS + 1):
            response = self._client.post(url, **kwargs)
            if not _is_transient_status(response.status_code) or attempt == self._MAX_ATTEMPTS:
                break
            time.sleep(_retry_backoff_seconds(attempt))
        assert response is not None
        return response


class MistralLLMProvider:
    _MAX_ATTEMPTS = 3

    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = httpx.Client(timeout=settings.provider_timeout_seconds)

    def clean_captions(self, transcription: TranscriptionResult, include_timestamps: bool) -> CorrectedCaptions:
        prompt = build_caption_cleanup_prompt(transcription, include_timestamps)
        content = self._chat(prompt)
        payload = self._parse_json(content, "caption cleanup")

        raw_segments = payload.get("segments") or []
        if not raw_segments:
            raw_segments = []
            for segment in transcription.segments:
                raw_segments.append(
                    {
                        "start_ms": segment.start_ms,
                        "end_ms": segment.end_ms,
                        "text": segment.text,
                    }
                )

        segments = []
        for index, segment in enumerate(raw_segments):
            original = transcription.segments[min(index, len(transcription.segments) - 1)]
            start_ms = segment.get("start_ms", original.start_ms)
            end_ms = segment.get("end_ms", original.end_ms)
            if not include_timestamps:
                start_ms = None
                end_ms = None
            segments.append(
                TimedTextSegment(
                    start_ms=_coerce_optional_int(start_ms),
                    end_ms=_coerce_optional_int(end_ms),
                    text=str(segment.get("text", "")).strip() or original.text,
                )
            )

        full_text = str(payload.get("full_text", "")).strip() or " ".join(segment.text for segment in segments)
        return CorrectedCaptions(segments=segments, full_text=full_text)

    def rewrite_primary(self, corrected_text: str, style_value: str) -> str:
        prompt = build_rewrite_prompt(corrected_text, style_value)
        content = self._chat(prompt)
        cleaned = _strip_code_fences(content).strip()
        if not cleaned:
            raise LLMProviderError("Mistral rewrite returned empty content")
        return cleaned

    def speaking_tips(self, corrected_text: str, style_value: str) -> list[str]:
        prompt = build_tips_prompt(corrected_text, style_value)
        content = self._chat(prompt)
        payload = self._parse_json(content, "speaking tips")
        if not isinstance(payload, list):
            raise LLMProviderError("Mistral tips response was not a JSON array")

        tips = [str(item).strip() for item in payload if str(item).strip()]
        if len(tips) != DEFAULT_TIPS_COUNT:
            raise LLMProviderError("Mistral tips response did not contain exactly three tips")
        return tips

    def _chat(self, prompt: str) -> str:
        if not self._settings.mistral_api_key:
            raise LLMProviderError("Missing Mistral API key")

        try:
            response = self._post_with_retries(
                self._settings.mistral_api_url,
                headers={"Authorization": f"Bearer {self._settings.mistral_api_key}"},
                json={
                    "model": self._settings.mistral_model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Output only English. Preserve meaning. Do not invent facts. "
                                "Return strict JSON when the prompt asks for JSON."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                },
            )
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError("Mistral request timed out") from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError("Mistral request failed") from exc

        if response.status_code >= 400:
            detail = _safe_http_error_detail(response)
            raise LLMProviderError(f"Mistral returned HTTP {response.status_code}: {detail}")

        try:
            body = response.json()
        except ValueError as exc:
            raise LLMProviderError("Mistral returned invalid JSON") from exc

        choices = body.get("choices") or []
        if not choices:
            raise LLMProviderError("Mistral returned no choices")
        message = choices[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, list):
            return "".join(str(item.get("text", "")).strip() for item in content)
        return str(content)

    def _parse_json(self, raw_content: str, context: str) -> Any:
        stripped = _strip_code_fences(raw_content)
        try:
            return json.loads(stripped)
        except ValueError as exc:
            raise LLMProviderError(f"Mistral {context} response was not valid JSON") from exc

    def _post_with_retries(self, url: str, **kwargs: Any) -> httpx.Response:
        response: httpx.Response | None = None
        for attempt in range(1, self._MAX_ATTEMPTS + 1):
            response = self._client.post(url, **kwargs)
            if not _is_transient_status(response.status_code) or attempt == self._MAX_ATTEMPTS:
                break
            time.sleep(_retry_backoff_seconds(attempt))
        assert response is not None
        return response


def _strip_code_fences(payload: str) -> str:
    stripped = payload.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        stripped = stripped[3:-3].strip()
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    return stripped


def _to_millis(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if value > 10_000:
            return int(value)
        return int(float(value) * 1000)
    try:
        numeric = float(str(value))
    except ValueError:
        return None
    return int(numeric if numeric > 10_000 else numeric * 1000)


def _coerce_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _merge_word_segments(word_segments: list[TimedTextSegment]) -> list[TimedTextSegment]:
    merged: list[TimedTextSegment] = []
    buffer_words: list[str] = []
    buffer_start: int | None = None
    buffer_end: int | None = None

    for segment in word_segments:
        buffer_words.append(segment.text)
        if buffer_start is None:
            buffer_start = segment.start_ms
        if segment.end_ms is not None:
            buffer_end = segment.end_ms

        boundary = segment.text.endswith((".", "?", "!")) or len(buffer_words) >= 10
        if not boundary:
            continue

        merged.append(
            TimedTextSegment(
                start_ms=buffer_start,
                end_ms=buffer_end,
                text=" ".join(buffer_words).replace(" ,", ",").replace(" .", ".").strip(),
            )
        )
        buffer_words = []
        buffer_start = None
        buffer_end = None

    if buffer_words:
        merged.append(
            TimedTextSegment(
                start_ms=buffer_start,
                end_ms=buffer_end,
                text=" ".join(buffer_words).replace(" ,", ",").replace(" .", ".").strip(),
            )
        )
    return merged


def _is_transient_status(status_code: int) -> bool:
    return status_code == 429 or 500 <= status_code <= 599


def _retry_backoff_seconds(attempt: int) -> float:
    return min(0.8, 0.15 * (2 ** (attempt - 1)))


def _safe_http_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            detail = payload.get("error") or payload.get("message") or payload.get("detail")
            if detail:
                return str(detail)[:200]
    except ValueError:
        pass
    text = response.text.strip()
    return (text or "upstream error")[:200]
