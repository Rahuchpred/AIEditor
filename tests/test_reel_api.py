from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas import TimedTextSegment, TranscriptionResult


def test_assemble_reel_returns_video_response(monkeypatch):
    class FakeProcessor:
        def __init__(self):
            self.auto_cut_calls = []
            self.concat_calls = []

        def auto_cut_clip(self, input_path, output_path, target_duration=5.0, max_duration=7.0):
            self.auto_cut_calls.append((input_path, output_path, target_duration, max_duration))
            output_path.write_bytes(b"trimmed")

        def concat_clips_with_audio(self, clip_paths, audio_path, output_path, *, apply_rotation=True):
            self.concat_calls.append((list(clip_paths), audio_path, apply_rotation))
            output_path.write_bytes(b"video-bytes")

    processor = FakeProcessor()
    monkeypatch.setattr("app.api.reel_routes.FfmpegMediaProcessor", lambda: processor)

    with TestClient(create_app()) as client:
        response = client.post(
            "/v1/reel/assemble",
            files=[
                ("clips", ("clip0.mp4", b"clip-0", "video/mp4")),
                ("clips", ("clip1.mp4", b"clip-1", "video/mp4")),
                ("voiceover", ("voiceover.mp3", b"voiceover", "audio/mpeg")),
            ],
            data={"captions_enabled": "false"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("video/mp4")
    assert response.content == b"video-bytes"
    assert len(processor.auto_cut_calls) == 2
    assert len(processor.concat_calls) == 1
    assert len(processor.concat_calls[0][0]) == 2
    assert processor.concat_calls[0][2] is False


def test_assemble_reel_returns_compact_error_message(monkeypatch):
    verbose_error = "\n".join(
        [
            "ffmpeg version 7.1",
            "Input #0, mov,mp4,m4a,3gp,3g2,mj2, from '/tmp/t0.mp4':",
            "Filter concat has an unconnected output",
            "Error binding filtergraph inputs/outputs: Invalid argument",
        ]
    )

    class FakeProcessor:
        def auto_cut_clip(self, input_path, output_path, target_duration=5.0, max_duration=7.0):
            output_path.write_bytes(b"trimmed")

        def concat_clips_with_audio(self, clip_paths, audio_path, output_path, *, apply_rotation=True):
            raise RuntimeError(verbose_error)

    monkeypatch.setattr("app.api.reel_routes.FfmpegMediaProcessor", FakeProcessor)

    with TestClient(create_app()) as client:
        response = client.post(
            "/v1/reel/assemble",
            files=[
                ("clips", ("clip0.mp4", b"clip-0", "video/mp4")),
                ("voiceover", ("voiceover.mp3", b"voiceover", "audio/mpeg")),
            ],
            data={"captions_enabled": "false"},
        )

    assert response.status_code == 400
    error = response.json()["error"]
    assert error.startswith("Reel assembly failed:")
    assert "Invalid argument" in error
    assert "ffmpeg version" not in error
    assert len(error) < len(verbose_error)


def test_assemble_reel_with_captions_transcribes_and_burns(monkeypatch):
    class FakeProcessor:
        def __init__(self):
            self.auto_cut_calls = []
            self.concat_calls = []
            self.caption_burns = []

        def auto_cut_clip(self, input_path, output_path, target_duration=5.0, max_duration=7.0):
            self.auto_cut_calls.append((input_path, output_path, target_duration, max_duration))
            output_path.write_bytes(b"trimmed")

        def concat_clips_with_audio(self, clip_paths, audio_path, output_path, *, apply_rotation=True):
            self.concat_calls.append((list(clip_paths), audio_path, apply_rotation))
            output_path.write_bytes(b"video-bytes")

        def burn_subtitles_into_video(self, input_video_path, subtitle_path, output_path, options):
            self.caption_burns.append((input_video_path, subtitle_path, output_path, options))
            output_path.write_bytes(b"captioned-video-bytes")

    class FakeTranscriptionProvider:
        def transcribe(self, audio_path, language_hint):
            from app.schemas import TimedTextSegment, TranscriptionResult

            return TranscriptionResult(
                language_detected="en",
                segments=[TimedTextSegment(start_ms=0, end_ms=1000, text="Caption line")],
            )

    processor = FakeProcessor()
    monkeypatch.setattr("app.api.reel_routes.FfmpegMediaProcessor", lambda: processor)
    monkeypatch.setattr(
        "app.api.reel_routes._reel_caption_transcription_provider",
        lambda settings: FakeTranscriptionProvider(),
    )

    with TestClient(create_app()) as client:
        response = client.post(
            "/v1/reel/assemble",
            files=[
                ("clips", ("clip0.mp4", b"clip-0", "video/mp4")),
                ("voiceover", ("voiceover.mp3", b"voiceover", "audio/mpeg")),
            ],
            data={"captions_enabled": "true"},
        )

    assert response.status_code == 200
    assert response.content == b"captioned-video-bytes"
    assert len(processor.caption_burns) == 1
    assert processor.concat_calls[0][2] is False
    options = processor.caption_burns[0][3]
    assert options.alignment == 2
    assert options.play_res_x == 1080
    assert options.play_res_y == 1920


def test_render_reel_with_captions_uses_existing_video(monkeypatch):
    class FakeProcessor:
        def __init__(self):
            self.caption_burns = []

        def burn_subtitles_into_video(self, input_video_path, subtitle_path, output_path, options):
            self.caption_burns.append((input_video_path, subtitle_path, output_path, options))
            output_path.write_bytes(b"captioned-video-bytes")

    class FakeTranscriptionProvider:
        def transcribe(self, audio_path, language_hint):
            return TranscriptionResult(
                language_detected="en",
                segments=[TimedTextSegment(start_ms=0, end_ms=1000, text="Caption line")],
            )

    processor = FakeProcessor()
    monkeypatch.setattr("app.api.reel_routes.FfmpegMediaProcessor", lambda: processor)
    monkeypatch.setattr(
        "app.api.reel_routes._reel_caption_transcription_provider",
        lambda settings: FakeTranscriptionProvider(),
    )

    with TestClient(create_app()) as client:
        response = client.post(
            "/v1/reel/caption-video",
            files=[
                ("video", ("reel.mp4", b"video-bytes", "video/mp4")),
                ("voiceover", ("voiceover.mp3", b"voiceover", "audio/mpeg")),
            ],
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("video/mp4")
    assert response.content == b"captioned-video-bytes"
    assert len(processor.caption_burns) == 1
    options = processor.caption_burns[0][3]
    assert options.play_res_x == 1080
    assert options.play_res_y == 1920


def test_render_reel_with_captions_uses_narration_text_without_transcription(monkeypatch):
    class FakeProcessor:
        def __init__(self):
            self.caption_burns = []
            self.subtitle_text = ""

        def _probe_duration(self, file_path):
            return 4.0

        def burn_subtitles_into_video(self, input_video_path, subtitle_path, output_path, options):
            self.caption_burns.append((input_video_path, subtitle_path, output_path, options))
            self.subtitle_text = subtitle_path.read_text(encoding="utf-8")
            output_path.write_bytes(b"captioned-video-bytes")

    processor = FakeProcessor()
    monkeypatch.setattr("app.api.reel_routes.FfmpegMediaProcessor", lambda: processor)
    monkeypatch.setattr(
        "app.api.reel_routes._reel_caption_transcription_provider",
        lambda settings: (_ for _ in ()).throw(AssertionError("transcription should not be called")),
    )

    with TestClient(create_app()) as client:
        response = client.post(
            "/v1/reel/caption-video",
            data={"narration_text": "Hello world from the generated script"},
            files=[
                ("video", ("reel.mp4", b"video-bytes", "video/mp4")),
                ("voiceover", ("voiceover.mp3", b"voiceover", "audio/mpeg")),
            ],
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("video/mp4")
    assert response.content == b"captioned-video-bytes"
    assert len(processor.caption_burns) == 1
    assert "Hello world" in processor.subtitle_text


def test_render_reel_captions_overlay_returns_video_response(monkeypatch):
    class FakeProcessor:
        def __init__(self):
            self.overlay_calls = []

        def _probe_duration(self, file_path):
            return 3.5

        def render_caption_overlay_video(self, subtitle_path, output_path, duration_seconds, options, fps=30):
            self.overlay_calls.append((subtitle_path, output_path, duration_seconds, options, fps))
            output_path.write_bytes(b"overlay-video-bytes")

    class FakeTranscriptionProvider:
        def transcribe(self, audio_path, language_hint):
            return TranscriptionResult(
                language_detected="en",
                segments=[TimedTextSegment(start_ms=0, end_ms=1200, text="Caption line")],
            )

    processor = FakeProcessor()
    monkeypatch.setattr("app.api.reel_routes.FfmpegMediaProcessor", lambda: processor)
    monkeypatch.setattr(
        "app.api.reel_routes._reel_caption_transcription_provider",
        lambda settings: FakeTranscriptionProvider(),
    )

    with TestClient(create_app()) as client:
        response = client.post(
            "/v1/reel/captions-overlay",
            files=[("voiceover", ("voiceover.mp3", b"voiceover", "audio/mpeg"))],
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("video/quicktime")
    assert response.content == b"overlay-video-bytes"
    assert len(processor.overlay_calls) == 1
    _subtitle_path, _output_path, duration_seconds, options, fps = processor.overlay_calls[0]
    assert duration_seconds == 3.5
    assert options.play_res_x == 1080
    assert options.play_res_y == 1920
    assert fps == 30


def test_analyze_example_extracts_style(monkeypatch):
    """POST /v1/reel/analyze-example returns style_notes from example video."""

    class FakeProcessor:
        def normalize_to_wav(self, input_path, output_path):
            output_path.write_bytes(b"fake-wav")

    class FakeSTT:
        def transcribe(self, audio_path, language_hint):
            return TranscriptionResult(
                language_detected="en",
                segments=[TimedTextSegment(start_ms=0, end_ms=5000, text="Hello world example speech.")],
            )

    class FakeScriptProvider:
        def __init__(self, settings):
            pass

        def analyze_example_style(self, transcript):
            assert "Hello world" in transcript
            return "Energetic, punchy, short sentences."

    monkeypatch.setattr("app.api.reel_routes.FfmpegMediaProcessor", FakeProcessor)
    monkeypatch.setattr("app.api.reel_routes._reel_caption_transcription_provider", lambda s: FakeSTT())
    monkeypatch.setattr("app.api.reel_routes.MistralReelScriptProvider", FakeScriptProvider)

    with TestClient(create_app()) as client:
        response = client.post(
            "/v1/reel/analyze-example",
            files=[("file", ("example.mp4", b"fake-video", "video/mp4"))],
        )

    assert response.status_code == 200
    data = response.json()
    assert data["style_notes"] == "Energetic, punchy, short sentences."
    assert "Hello world" in data["example_transcript"]


def test_analyze_example_returns_error_when_no_speech(monkeypatch):
    """POST /v1/reel/analyze-example returns 400 when no speech is detected."""

    class FakeProcessor:
        def normalize_to_wav(self, input_path, output_path):
            output_path.write_bytes(b"fake-wav")

    class FakeSTT:
        def transcribe(self, audio_path, language_hint):
            return TranscriptionResult(language_detected="en", segments=[])

    monkeypatch.setattr("app.api.reel_routes.FfmpegMediaProcessor", FakeProcessor)
    monkeypatch.setattr("app.api.reel_routes._reel_caption_transcription_provider", lambda s: FakeSTT())

    with TestClient(create_app()) as client:
        response = client.post(
            "/v1/reel/analyze-example",
            files=[("file", ("example.mp4", b"fake-video", "video/mp4"))],
        )

    assert response.status_code == 400
    assert "No speech" in response.json()["error"]


def test_generate_script_passes_style_notes(monkeypatch):
    """POST /v1/reel/generate-script forwards style_notes to the provider."""
    captured_style_notes = {}

    original_generate = None

    class FakeScriptProvider:
        def __init__(self, settings):
            pass

        def generate_reel_script(self, rough_idea, selected_hook, clip_count, style_notes=None):
            captured_style_notes["value"] = style_notes
            from app.schemas import ReelScript

            return ReelScript(
                hook="Hook",
                body=["Body"],
                cta="CTA",
                full_narration="Hook Body CTA",
                hashtags=["#test"],
            )

    class FakeCatalog:
        def shortlist(self, *a, **kw):
            return []

        def get_hook(self, hook_id):
            from app.schemas import HookTemplate

            return HookTemplate(id=hook_id, hook_text="Test hook", source_url=None, page_number=0, section=None)

    monkeypatch.setattr("app.api.reel_routes.MistralReelScriptProvider", FakeScriptProvider)
    monkeypatch.setattr("app.api.reel_routes.get_hook_catalog_service", lambda path: FakeCatalog())

    with TestClient(create_app()) as client:
        response = client.post(
            "/v1/reel/generate-script",
            json={
                "rough_idea": "5 productivity hacks",
                "selected_hook_id": "hook-1",
                "clip_count": 3,
                "style_notes": "Conversational, warm, uses rhetorical questions.",
            },
        )

    assert response.status_code == 200
    assert captured_style_notes["value"] == "Conversational, warm, uses rhetorical questions."
