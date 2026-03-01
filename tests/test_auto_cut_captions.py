from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas import VideoGeometry


def test_auto_cut_with_captions_uses_transcript_result(context_factory, monkeypatch):
    context = context_factory()

    class FakeProcessor:
        def __init__(self):
            self.subtitle_writes = []

        def _probe_duration(self, path):
            return 4.0

        def trim_keep_ranges(self, input_path, output_path, keep_ranges):
            output_path.write_bytes(b"trimmed-video")

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
            assert cues
            self.subtitle_writes.append((list(cues), options))
            output_path.write_text("ass", encoding="utf-8")

        def burn_subtitles_into_video(self, input_video_path, subtitle_path, output_path, options):
            output_path.write_bytes(b"captioned-video")

    processor = FakeProcessor()
    monkeypatch.setattr("app.api.routes._media_proc", processor)

    create_response = context.client.post(
        "/v1/analysis-jobs",
        files={"media_file": ("clip.mp4", b"fake-video", "video/mp4")},
        data={"include_timestamps": "true"},
    )
    job_id = create_response.json()["job_id"]
    context.service.process_job(job_id)

    response = context.client.post(
        "/v1/auto-cut",
        files={"media_file": ("clip.mp4", b"fake-video", "video/mp4")},
        data={
            "cut_regions": '[{"start_s": 1.0, "end_s": 1.5}]',
            "job_id": job_id,
            "captions_enabled": "true",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("video/mp4")
    assert response.content == b"captioned-video"
    assert len(processor.subtitle_writes) == 1
    _cues, options = processor.subtitle_writes[0]
    assert options.max_chars_per_line == 22
    assert options.bottom_margin == 461


def test_auto_cut_rejects_audio_when_captions_enabled(context_factory):
    context = context_factory()

    response = context.client.post(
        "/v1/auto-cut",
        files={"media_file": ("speech.wav", b"wav-data", "audio/wav")},
        data={
            "cut_regions": "[]",
            "captions_enabled": "true",
        },
    )

    assert response.status_code == 400
    assert "video uploads" in response.json()["error"]


def test_auto_cut_without_captions_preserves_existing_behavior(monkeypatch):
    class FakeProcessor:
        def _probe_duration(self, path):
            return 4.0

        def trim_keep_ranges(self, input_path, output_path, keep_ranges):
            output_path.write_bytes(b"trimmed-video")

    monkeypatch.setattr("app.api.routes._media_proc", FakeProcessor())

    with TestClient(create_app()) as client:
        response = client.post(
            "/v1/auto-cut",
            files={"media_file": ("clip.mp4", b"fake-video", "video/mp4")},
            data={
                "cut_regions": '[{"start_s": 1.0, "end_s": 1.5}]',
                "captions_enabled": "false",
            },
        )

    assert response.status_code == 200
    assert response.content == b"trimmed-video"
