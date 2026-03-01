from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.media import FfmpegMediaProcessor


def _capture_concat_command(monkeypatch, durations_by_path: dict[Path, float]):
    processor = FfmpegMediaProcessor()
    captured: dict[str, list[str]] = {}

    monkeypatch.setattr("app.media._resolve_ffmpeg_binary", lambda: "ffmpeg")
    monkeypatch.setattr(
        processor,
        "_probe_duration",
        lambda path: durations_by_path[Path(path)],
    )

    def fake_run(command, capture_output, text, check):
        captured["command"] = command
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr("app.media.subprocess.run", fake_run)
    return processor, captured


def _input_paths(command: list[str]) -> list[str]:
    return [command[index + 1] for index, token in enumerate(command) if token == "-i"]


def test_concat_clips_uses_video_only_graph(monkeypatch, tmp_path):
    clip_paths = [tmp_path / f"clip-{idx}.mp4" for idx in range(3)]
    audio_path = tmp_path / "voiceover.mp3"
    output_path = tmp_path / "out.mp4"
    durations = {clip_paths[0]: 5.0, clip_paths[1]: 5.0, clip_paths[2]: 5.0, audio_path: 12.0}
    processor, captured = _capture_concat_command(monkeypatch, durations)

    processor.concat_clips_with_audio(clip_paths, audio_path, output_path)

    command = captured["command"]
    filter_graph = command[command.index("-filter_complex") + 1]
    assert "concat=n=3:v=1:a=0[outv]" in filter_graph
    assert "anullsrc" not in filter_graph
    assert "[outa]" not in filter_graph
    assert "fps=30" in filter_graph
    assert "format=yuv420p" in filter_graph
    assert "setsar=1" in filter_graph
    assert command[command.index("-map") + 1] == "[outv]"
    assert command[command.index("-map", command.index("-map") + 1) + 1] == "3:a"
    assert "-shortest" in command


def test_concat_clips_repeats_inputs_until_audio_is_covered(monkeypatch, tmp_path):
    clip_paths = [tmp_path / f"clip-{idx}.mp4" for idx in range(3)]
    audio_path = tmp_path / "voiceover.mp3"
    output_path = tmp_path / "out.mp4"
    durations = {clip_paths[0]: 5.0, clip_paths[1]: 5.0, clip_paths[2]: 5.0, audio_path: 20.0}
    processor, captured = _capture_concat_command(monkeypatch, durations)

    processor.concat_clips_with_audio(clip_paths, audio_path, output_path)

    assert _input_paths(captured["command"]) == [
        str(clip_paths[0]),
        str(clip_paths[1]),
        str(clip_paths[2]),
        str(clip_paths[0]),
        str(audio_path),
    ]
    filter_graph = captured["command"][captured["command"].index("-filter_complex") + 1]
    assert "concat=n=4:v=1:a=0[outv]" in filter_graph


def test_concat_clips_overshoots_and_still_uses_shortest(monkeypatch, tmp_path):
    clip_paths = [tmp_path / "clip-a.mp4", tmp_path / "clip-b.mp4"]
    audio_path = tmp_path / "voiceover.mp3"
    output_path = tmp_path / "out.mp4"
    durations = {clip_paths[0]: 4.0, clip_paths[1]: 6.0, audio_path: 11.0}
    processor, captured = _capture_concat_command(monkeypatch, durations)

    processor.concat_clips_with_audio(clip_paths, audio_path, output_path)

    assert _input_paths(captured["command"]) == [
        str(clip_paths[0]),
        str(clip_paths[1]),
        str(clip_paths[0]),
        str(audio_path),
    ]
    assert "-shortest" in captured["command"]


def test_concat_clips_rejects_when_no_clips_have_usable_duration(monkeypatch, tmp_path):
    clip_paths = [tmp_path / f"clip-{idx}.mp4" for idx in range(2)]
    audio_path = tmp_path / "voiceover.mp3"
    output_path = tmp_path / "out.mp4"
    durations = {clip_paths[0]: 0.0, clip_paths[1]: -1.0, audio_path: 11.0}
    processor, _captured = _capture_concat_command(monkeypatch, durations)

    with pytest.raises(RuntimeError, match="No clips with usable duration"):
        processor.concat_clips_with_audio(clip_paths, audio_path, output_path)
