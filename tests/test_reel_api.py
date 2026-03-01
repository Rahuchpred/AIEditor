from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


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
        )

    assert response.status_code == 400
    error = response.json()["error"]
    assert error.startswith("Reel assembly failed:")
    assert "Invalid argument" in error
    assert "ffmpeg version" not in error
    assert len(error) < len(verbose_error)
