from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.routes import _caption_options_for_video
from app.main import create_app


def test_auto_cut_with_captions_uses_transcript_result(context_factory, monkeypatch):
    context = context_factory()

    class FakeProcessor:
        def _probe_duration(self, path):
            return 4.0

        def trim_keep_ranges(self, input_path, output_path, keep_ranges):
            output_path.write_bytes(b"trimmed-video")

        def burn_subtitles_into_video(self, input_video_path, subtitle_path, output_path, options):
            output_path.write_bytes(b"captioned-video")

    monkeypatch.setattr("app.api.routes._media_proc", FakeProcessor())

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


def test_root_ui_includes_caption_editor_controls():
    with TestClient(create_app()) as client:
        response = client.get("/")

    assert response.status_code == 200
    html = response.text
    assert "Open Caption Editor" in html
    assert 'id="captionEditorCard"' in html
    assert 'id="editorTimeline"' in html
    assert 'id="cueText"' in html
    assert "Render Final Video" in html
    assert "Export Timeline to Premiere Pro" not in html
    assert 'id="editorDownloadLink"' in html
    assert "<h3>Rendered Video</h3>" not in html
    assert "payload.error" in html


def test_auto_cut_editor_session_returns_preview_and_cues(context_factory, monkeypatch):
    context = context_factory()

    class FakeProcessor:
        def _probe_duration(self, path):
            return 4.0

        def trim_keep_ranges(self, input_path, output_path, keep_ranges):
            output_path.write_bytes(b"trimmed-video")

    monkeypatch.setattr("app.api.routes._media_proc", FakeProcessor())

    create_response = context.client.post(
        "/v1/analysis-jobs",
        files={"media_file": ("clip.mp4", b"fake-video", "video/mp4")},
        data={"include_timestamps": "true"},
    )
    job_id = create_response.json()["job_id"]
    context.service.process_job(job_id)

    response = context.client.post(
        "/v1/auto-cut/editor-session",
        files={"media_file": ("clip.mp4", b"fake-video", "video/mp4")},
        data={
            "cut_regions": '[{"start_s": 1.0, "end_s": 1.5}]',
            "job_id": job_id,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"]
    assert payload["preview_video_url"].endswith("/preview")
    assert payload["cues"]
    assert payload["caption_track"]["vertical_position_pct"] >= 10

    preview_response = context.client.get(payload["preview_video_url"])
    assert preview_response.status_code == 200
    assert preview_response.content == b"trimmed-video"


def test_auto_cut_editor_render_returns_video_and_keeps_session_available(context_factory, monkeypatch):
    context = context_factory()

    class FakeProcessor:
        def __init__(self):
            self.rendered_cues = []

        def _probe_duration(self, path):
            return 4.0

        def trim_keep_ranges(self, input_path, output_path, keep_ranges):
            output_path.write_bytes(b"trimmed-video")

        def burn_subtitles_into_video(self, input_video_path, subtitle_path, output_path, options, *, apply_rotation=False):
            # Extract cue texts from the ASS subtitle file
            from app.captions import CaptionCue
            self.rendered_cues = []
            for line in subtitle_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("Dialogue:"):
                    text = line.split(",", 9)[-1]
                    self.rendered_cues.append(CaptionCue(start_ms=0, end_ms=1000, text=text))
            output_path.write_bytes(b"rendered-video")

    processor = FakeProcessor()
    monkeypatch.setattr("app.api.routes._media_proc", processor)

    session_response = context.client.post(
        "/v1/auto-cut/editor-session",
        files={"media_file": ("clip.mp4", b"fake-video", "video/mp4")},
        data={"cut_regions": '[{"start_s": 1.0, "end_s": 1.5}]'},
    )
    assert session_response.status_code == 200
    session_payload = session_response.json()
    edited_cue = dict(session_payload["cues"][0])
    edited_cue["text"] = "Edited caption"

    render_response = context.client.post(
        f"/v1/auto-cut/editor-session/{session_payload['session_id']}/render",
        json={
            "cues": [edited_cue],
            "caption_track": {"vertical_position_pct": 70},
        },
    )

    assert render_response.status_code == 200
    assert render_response.headers["content-type"].startswith("video/mp4")
    assert render_response.content == b"rendered-video"
    assert processor.rendered_cues[0].text == "Edited caption"

    preview_response = context.client.get(session_payload["preview_video_url"])
    assert preview_response.status_code == 200
    assert preview_response.content == b"trimmed-video"


def test_auto_cut_editor_premiere_export_route_is_removed(context_factory, monkeypatch):
    context = context_factory()

    class FakeProcessor:
        def _probe_duration(self, path):
            return 4.0

        def trim_keep_ranges(self, input_path, output_path, keep_ranges):
            output_path.write_bytes(b"trimmed-video")

    monkeypatch.setattr("app.api.routes._media_proc", FakeProcessor())

    session_response = context.client.post(
        "/v1/auto-cut/editor-session",
        files={"media_file": ("clip.mp4", b"fake-video", "video/mp4")},
        data={"cut_regions": '[{"start_s": 1.0, "end_s": 1.5}]'},
    )
    assert session_response.status_code == 200
    session_payload = session_response.json()

    export_response = context.client.post(
        f"/v1/auto-cut/editor-session/{session_payload['session_id']}/premiere-export",
        json={
            "cues": session_payload["cues"],
            "caption_track": {"vertical_position_pct": 70},
        },
    )

    assert export_response.status_code == 404


def test_caption_options_use_encoded_portrait_canvas_when_display_metadata_is_stale():
    class FakeProcessor:
        def probe_video_geometry(self, path):
            return {
                "encoded_width": 1080,
                "encoded_height": 1920,
                "display_width": 1920,
                "display_height": 1080,
            }

    options = _caption_options_for_video(
        FakeProcessor(),
        None,
        font_path="",
        font_name="Arial",
    )

    assert options.play_res_x == 1080
    assert options.play_res_y == 1920


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
