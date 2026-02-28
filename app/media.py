from __future__ import annotations

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
        ffmpeg = shutil.which("ffmpeg")
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

        if file_path.suffix.lower() == ".wav":
            with wave.open(str(file_path), "rb") as wav_file:
                frame_rate = wav_file.getframerate()
                frame_count = wav_file.getnframes()
                if frame_rate == 0:
                    raise RuntimeError("WAV file has an invalid frame rate")
                return frame_count / frame_rate

        raise RuntimeError("Unable to determine media duration; install ffprobe or upload WAV audio")
