from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas import VideoGeometry


def test_assemble_reel_returns_video_response(monkeypatch):
    class FakeProcessor:
        def __init__(self):
            self.auto_cut_calls = []
            self.concat_calls = []

        def auto_cut_clip(self, input_path, output_path, target_duration=5.0, max_duration=7.0):
            self.auto_cut_calls.append((input_path, output_path, target_duration, max_duration))
            output_path.write_bytes(b"trimmed")

        def concat_clips_with_audio(self, clip_paths, audio_path, output_path):
            self.concat_calls.append((list(clip_paths), audio_path))
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

        def concat_clips_with_audio(self, clip_paths, audio_path, output_path):
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
            self.subtitle_writes = []
            self.subtitle_burns = []

        def auto_cut_clip(self, input_path, output_path, target_duration=5.0, max_duration=7.0):
            self.auto_cut_calls.append((input_path, output_path, target_duration, max_duration))
            output_path.write_bytes(b"trimmed")

        def concat_clips_with_audio(self, clip_paths, audio_path, output_path):
            self.concat_calls.append((list(clip_paths), audio_path))
            output_path.write_bytes(b"video-bytes")

        def probe_video_geometry(self, path):
            return VideoGeometry(
                encoded_width=1080,
                encoded_height=1920,
                rotation_degrees=0,
                display_width=1080,
                display_height=1920,
                is_portrait_display=True,
            )

        def write_ass_subtitles(self, cues, output_path, options):
            self.subtitle_writes.append((list(cues), output_path, options))
            output_path.write_text("ass", encoding="utf-8")

        def burn_subtitles_into_video(self, input_video_path, subtitle_path, output_path, options):
            self.subtitle_burns.append((input_video_path, subtitle_path, output_path, options))
            output_path.write_bytes(b"captioned-video-bytes")

    class FakeTranscriptionProvider:
        def transcribe(self, audio_path, language_hint):
            from app.schemas import TimedTextSegment, TranscriptionResult

            return TranscriptionResult(
                language_detected="en",
                segments=[
                    TimedTextSegment(
                        start_ms=0,
                        end_ms=1600,
                        text="one of these six hooks is the one you should use",
                    )
                ],
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
    assert len(processor.subtitle_writes) == 1
    assert len(processor.subtitle_burns) == 1
    cues, _output_path, options = processor.subtitle_writes[0]
    assert options.max_chars_per_line == 22
    assert options.bottom_margin == 461
    assert cues[0].text.split("\n")[0] == "one of these six hooks"
    assert all(len(line) <= 22 for cue in cues for line in cue.text.split("\n"))
