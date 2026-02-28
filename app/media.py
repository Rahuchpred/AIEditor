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
