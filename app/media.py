from __future__ import annotations

import re
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Protocol

from app.constants import SUPPORTED_MEDIA_TYPES
from app.errors import ServiceError
from app.constants import ErrorCode
from app.schemas import MediaInfo


class MediaProcessor(Protocol):
    def inspect(self, file_path: Path, content_type: str) -> MediaInfo:
        ...

    def normalize_to_wav(self, input_path: Path, output_path: Path) -> None:
        ...


class FfmpegMediaProcessor:
    def inspect(self, file_path: Path, content_type: str) -> MediaInfo:
        media_type = SUPPORTED_MEDIA_TYPES.get(content_type)
        if media_type is None:
            raise ServiceError(
                code=ErrorCode.UNSUPPORTED_MEDIA_TYPE,
                message=f"Unsupported content type: {content_type}",
                status_code=415,
            )

        duration_seconds = self._probe_duration(file_path)
        return MediaInfo(
            media_type=media_type,
            size_bytes=file_path.stat().st_size,
            duration_seconds=duration_seconds,
        )

    def normalize_to_wav(self, input_path: Path, output_path: Path) -> None:
        ffmpeg = _resolve_ffmpeg_binary()
        if ffmpeg is None:
            if input_path.suffix.lower() == ".wav":
                shutil.copyfile(input_path, output_path)
                return
            raise RuntimeError("ffmpeg is required to normalize non-wav media")

        command = [
            ffmpeg,
            "-y",
            "-i",
            str(input_path),
            "-ac",
            "1",
            "-ar",
            "16000",
            str(output_path),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "ffmpeg failed to normalize media")

    def detect_silence(
        self,
        file_path: Path,
        threshold_db: float = -30,
        min_duration: float = 0.4,
    ) -> list[dict[str, float]]:
        ffmpeg = _resolve_ffmpeg_binary()
        if ffmpeg is None:
            raise RuntimeError("ffmpeg is required for silence detection")

        command = [
            ffmpeg, "-i", str(file_path),
            "-af", f"silencedetect=noise={threshold_db}dB:d={min_duration}",
            "-f", "null", "-",
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        return _parse_silence_regions(completed.stderr)

    def trim_keep_ranges(
        self,
        input_path: Path,
        output_path: Path,
        keep_ranges: list[tuple[float, float]],
    ) -> None:
        ffmpeg = _resolve_ffmpeg_binary()
        if ffmpeg is None:
            raise RuntimeError("ffmpeg is required for trimming")
        if not keep_ranges:
            raise RuntimeError("No segments to keep")

        n = len(keep_ranges)
        filter_parts: list[str] = []
        concat_inputs = ""
        for i, (start, end) in enumerate(keep_ranges):
            filter_parts.append(
                f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}];"
                f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}];"
            )
            concat_inputs += f"[v{i}][a{i}]"

        filter_complex = "".join(filter_parts) + f"{concat_inputs}concat=n={n}:v=1:a=1[outv][outa]"

        command = [
            ffmpeg, "-y", "-i", str(input_path),
            "-filter_complex", filter_complex,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            str(output_path),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "ffmpeg trim+concat failed")

    def auto_cut_clip(
        self,
        input_path: Path,
        output_path: Path,
        target_duration: float = 5.0,
        max_duration: float = 7.0,
    ) -> None:
        """Trim a clip to target_duration if longer than max_duration. Keeps centered segment."""
        ffmpeg = _resolve_ffmpeg_binary()
        if ffmpeg is None:
            raise RuntimeError("ffmpeg is required for auto-cut")

        duration = self._probe_duration(input_path)
        if duration <= max_duration:
            start = 0.0
            end = duration
        else:
            start = max(0.0, (duration - target_duration) / 2)
            end = min(duration, start + target_duration)

        command = [
            ffmpeg, "-y", "-i", str(input_path),
            "-ss", str(start), "-t", str(end - start),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            str(output_path),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "ffmpeg auto-cut failed")

    def concat_clips_with_audio(
        self,
        clip_paths: list[Path],
        audio_path: Path,
        output_path: Path,
        width: int = 1080,
        height: int = 1920,
    ) -> None:
        """Concatenate B-roll clips (scaled to width x height) and overlay voiceover audio."""
        ffmpeg = _resolve_ffmpeg_binary()
        if ffmpeg is None:
            raise RuntimeError("ffmpeg is required for concat")
        if not clip_paths:
            raise RuntimeError("No clips to concatenate")

        expanded_clip_paths = self._expand_clips_to_cover_audio(clip_paths, audio_path)
        n = len(expanded_clip_paths)

        filter_parts: list[str] = []
        concat_inputs = ""
        for i, _path in enumerate(expanded_clip_paths):
            normalize_video = (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
                "fps=30,"
                "format=yuv420p,"
                "setsar=1,"
                "setpts=PTS-STARTPTS"
            )
            filter_parts.append(
                f"[{i}:v]{normalize_video}[v{i}];"
            )
            concat_inputs += f"[v{i}]"

        filter_complex = "".join(filter_parts) + f"{concat_inputs}concat=n={n}:v=1:a=0[outv]"

        inputs = [str(p) for p in expanded_clip_paths] + [str(audio_path)]
        flat_inputs: list[str] = []
        for inp in inputs:
            flat_inputs.extend(["-i", inp])

        audio_input_index = n
        command = [
            ffmpeg, "-y",
            *flat_inputs,
            "-filter_complex", filter_complex,
            "-map", "[outv]", "-map", f"{audio_input_index}:a",
            "-shortest",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            str(output_path),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "ffmpeg concat+audio failed")

    def _expand_clips_to_cover_audio(self, clip_paths: list[Path], audio_path: Path) -> list[Path]:
        audio_duration = self._probe_duration(audio_path)
        if audio_duration <= 0:
            raise RuntimeError("Voiceover duration must be greater than zero")

        usable_clips: list[tuple[Path, float]] = []
        for path in clip_paths:
            duration = self._probe_duration(path)
            if duration > 0:
                usable_clips.append((path, duration))
        if not usable_clips:
            raise RuntimeError("No clips with usable duration")

        expanded_clip_paths: list[Path] = []
        covered_duration = 0.0
        index = 0
        while covered_duration < audio_duration:
            path, duration = usable_clips[index % len(usable_clips)]
            expanded_clip_paths.append(path)
            covered_duration += duration
            index += 1
        return expanded_clip_paths

    def _probe_duration(self, file_path: Path) -> float:
        ffprobe = shutil.which("ffprobe")
        if ffprobe is not None:
            command = [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(file_path),
            ]
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            if completed.returncode == 0:
                try:
                    return float(completed.stdout.strip())
                except ValueError:
                    pass

        ffmpeg = _resolve_ffmpeg_binary()
        if ffmpeg is not None:
            command = [ffmpeg, "-i", str(file_path), "-f", "null", "-"]
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            duration = _parse_ffmpeg_duration(completed.stderr)
            if duration is not None:
                return duration

        if file_path.suffix.lower() == ".wav":
            with wave.open(str(file_path), "rb") as wav_file:
                frame_rate = wav_file.getframerate()
                frame_count = wav_file.getnframes()
                if frame_rate == 0:
                    raise RuntimeError("WAV file has an invalid frame rate")
                return frame_count / frame_rate

        raise RuntimeError("Unable to determine media duration; install ffprobe or upload WAV audio")


def _parse_silence_regions(stderr_text: str) -> list[dict[str, float]]:
    regions: list[dict[str, float]] = []
    starts = re.findall(r"silence_start:\s*([\d.]+)", stderr_text)
    ends = re.findall(r"silence_end:\s*([\d.]+)", stderr_text)
    for i, start_str in enumerate(starts):
        start = float(start_str)
        end = float(ends[i]) if i < len(ends) else None
        if end is not None:
            regions.append({"start_s": round(start, 3), "end_s": round(end, 3)})
    return regions


def _parse_ffmpeg_duration(stderr_text: str) -> float | None:
    match = re.search(r"Duration:\s*(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)", stderr_text)
    if not match:
        return None
    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = float(match.group(3))
    return hours * 3600 + minutes * 60 + seconds


def _resolve_ffmpeg_binary() -> str | None:
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None
