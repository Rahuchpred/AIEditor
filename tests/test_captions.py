from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.captions import (
    default_caption_render_options,
    remap_cues_after_cuts,
    segments_to_caption_cues,
    write_ass_subtitles,
)
from app.media import FfmpegMediaProcessor
from app.schemas import TimedTextSegment


def test_segments_to_caption_cues_normalizes_and_splits_text():
    segments = [
        TimedTextSegment(
            start_ms=0,
            end_ms=2400,
            text="  This is a fairly long caption segment that should wrap into readable subtitle lines.  ",
        )
    ]

    cues = segments_to_caption_cues(segments)

    assert cues
    assert all(cue.text.strip() == cue.text for cue in cues)
    assert all(cue.end_ms > cue.start_ms for cue in cues)
    assert any("\n" in cue.text for cue in cues)


def test_remap_cues_after_cuts_shifts_timeline():
    cues = segments_to_caption_cues(
        [TimedTextSegment(start_ms=0, end_ms=3000, text="One two three four five six")]
    )

    remapped = remap_cues_after_cuts(cues, [{"start_s": 1.0, "end_s": 1.5}])

    assert remapped
    assert remapped[0].start_ms == 0
    assert all(cue.start_ms >= 0 for cue in remapped)
    assert all(cue.end_ms <= 2500 for cue in remapped)


def test_write_ass_subtitles_creates_dialogue_lines(tmp_path):
    output_path = tmp_path / "captions.ass"
    cues = segments_to_caption_cues(
        [TimedTextSegment(start_ms=0, end_ms=1200, text="Caption line")]
    )

    write_ass_subtitles(cues, output_path, default_caption_render_options())

    text = output_path.read_text(encoding="utf-8")
    assert "[Events]" in text
    assert "Dialogue:" in text


def test_burn_subtitles_into_video_builds_expected_command(monkeypatch, tmp_path):
    processor = FfmpegMediaProcessor()
    input_video = tmp_path / "input.mp4"
    subtitle = tmp_path / "captions.ass"
    output_video = tmp_path / "output.mp4"
    input_video.write_bytes(b"video")
    subtitle.write_text("ass", encoding="utf-8")

    captured: dict[str, list[str]] = {}

    monkeypatch.setattr("app.media._resolve_ffmpeg_binary", lambda: "ffmpeg")

    def fake_run(command, capture_output, text, check):
        captured["command"] = command
        if command[-1] == "-filters":
            return SimpleNamespace(returncode=0, stdout=" ... subtitles ... ", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("app.media.subprocess.run", fake_run)

    processor.burn_subtitles_into_video(
        input_video,
        subtitle,
        output_video,
        default_caption_render_options(),
    )

    command = captured["command"]
    assert "-vf" in command
    assert "subtitles=" in command[command.index("-vf") + 1]


def test_burn_subtitles_into_video_raises_without_ffmpeg(monkeypatch, tmp_path):
    processor = FfmpegMediaProcessor()
    monkeypatch.setattr("app.media._resolve_ffmpeg_binary", lambda: None)

    with pytest.raises(RuntimeError, match="subtitle rendering"):
        processor.burn_subtitles_into_video(
            tmp_path / "input.mp4",
            tmp_path / "captions.ass",
            tmp_path / "output.mp4",
            default_caption_render_options(),
        )
