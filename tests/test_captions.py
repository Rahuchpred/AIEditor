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
    options = default_caption_render_options(frame_width=1080, frame_height=1920)
    segments = [
        TimedTextSegment(
            start_ms=0,
            end_ms=2400,
            text="one of these six hooks is the one you should use",
        )
    ]

    cues = segments_to_caption_cues(segments, options)

    assert cues
    assert all(cue.text.strip() == cue.text for cue in cues)
    assert all(cue.end_ms > cue.start_ms for cue in cues)
    assert cues[0].text.split("\n")[0] == "one of these six hooks"
    assert any(line.startswith("is") for cue in cues for line in cue.text.split("\n")[1:])
    assert all(len(line) <= 22 for cue in cues for line in cue.text.split("\n"))


def test_remap_cues_after_cuts_shifts_timeline():
    options = default_caption_render_options(frame_width=1080, frame_height=1920)
    cues = segments_to_caption_cues(
        [TimedTextSegment(start_ms=0, end_ms=3000, text="One two three four five six")],
        options,
    )

    remapped = remap_cues_after_cuts(cues, [{"start_s": 1.0, "end_s": 1.5}])

    assert remapped
    assert remapped[0].start_ms == 0
    assert all(cue.start_ms >= 0 for cue in remapped)
    assert all(cue.end_ms <= 2500 for cue in remapped)


def test_write_ass_subtitles_creates_dialogue_lines(tmp_path):
    output_path = tmp_path / "captions.ass"
    options = default_caption_render_options(frame_width=1080, frame_height=1920)
    cues = segments_to_caption_cues(
        [TimedTextSegment(start_ms=0, end_ms=1200, text="Caption line")],
        options,
    )

    write_ass_subtitles(cues, output_path, options)

    text = output_path.read_text(encoding="utf-8")
    assert "[Events]" in text
    assert "Dialogue:" in text
    assert ",2,130,194,461,1" in text


def test_default_caption_render_options_uses_orientation_profiles():
    portrait = default_caption_render_options(frame_width=1080, frame_height=1920)
    landscape = default_caption_render_options(frame_width=1920, frame_height=1080)

    assert portrait.font_size == 54
    assert portrait.max_chars_per_line == 22
    assert portrait.margin_left == 130
    assert portrait.margin_right == 194
    assert portrait.bottom_margin == 461
    assert portrait.soft_wrap_threshold == 18
    assert portrait.soft_wrap_increment_limit == 4

    assert landscape.font_size == 48
    assert landscape.max_chars_per_line == 32
    assert landscape.margin_left == 48
    assert landscape.margin_right == 48
    assert landscape.bottom_margin == 86


def test_burn_subtitles_into_video_builds_expected_command(monkeypatch, tmp_path):
    processor = FfmpegMediaProcessor()
    input_video = tmp_path / "input.mp4"
    subtitle = tmp_path / "captions.ass"
    output_video = tmp_path / "output.mp4"
    input_video.write_bytes(b"video")
    subtitle.write_text("ass", encoding="utf-8")

    captured: dict[str, list[str]] = {}

    monkeypatch.setattr("app.media._resolve_ffmpeg_binary", lambda: "ffmpeg")
    monkeypatch.setattr(processor, "_rotation_filter_steps", lambda path: [])

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
    assert "-metadata:s:v:0" in command
    assert "rotate=0" in command


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
