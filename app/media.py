from __future__ import annotations

import json
import re
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Protocol

from app.captions import write_ass_subtitles
from app.constants import SUPPORTED_MEDIA_TYPES
from app.errors import ServiceError
from app.constants import ErrorCode
from app.schemas import CaptionCue, CaptionRenderOptions, MediaInfo, VideoGeometry


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

    def probe_video_geometry(self, file_path: Path) -> VideoGeometry | None:
        return self._probe_video_geometry(file_path)

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

        rotation_steps = self._rotation_filter_steps(input_path)
        n = len(keep_ranges)
        filter_parts: list[str] = []
        concat_inputs = ""
        for i, (start, end) in enumerate(keep_ranges):
            video_chain = [f"trim=start={start}:end={end}", "setpts=PTS-STARTPTS", *rotation_steps]
            filter_parts.append(
                f"[0:v]{','.join(video_chain)}[v{i}];"
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
            "-metadata:s:v:0", "rotate=0",
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

        command = [ffmpeg, "-y", "-i", str(input_path), "-ss", str(start), "-t", str(end - start)]
        rotation_steps = self._rotation_filter_steps(input_path)
        if rotation_steps:
            command.extend(["-vf", ",".join(rotation_steps)])

        command.extend(
            [
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-metadata:s:v:0", "rotate=0",
                str(output_path),
            ]
        )
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
        for i, path in enumerate(expanded_clip_paths):
            normalize_steps = [
                *self._rotation_filter_steps(path),
                f"scale={width}:{height}:force_original_aspect_ratio=decrease",
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
                "fps=30",
                "format=yuv420p",
                "setsar=1",
                "setpts=PTS-STARTPTS",
            ]
            filter_parts.append(f"[{i}:v]{','.join(normalize_steps)}[v{i}];")
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
            "-metadata:s:v:0", "rotate=0",
            str(output_path),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "ffmpeg concat+audio failed")

    def write_ass_subtitles(
        self,
        cues: list[CaptionCue],
        output_path: Path,
        options: CaptionRenderOptions,
    ) -> None:
        write_ass_subtitles(cues, output_path, options)

    def burn_subtitles_into_video(
        self,
        input_video_path: Path,
        subtitle_path: Path,
        output_path: Path,
        options: CaptionRenderOptions,
    ) -> None:
        ffmpeg = _resolve_ffmpeg_binary()
        if ffmpeg is None:
            raise RuntimeError("ffmpeg is required for subtitle rendering")
        if not self._supports_libass(ffmpeg):
            raise RuntimeError("ffmpeg subtitle rendering is unavailable (libass/subtitles filter missing)")

        subtitle_arg = _escape_filter_path(subtitle_path)
        filter_steps = [*self._rotation_filter_steps(input_video_path)]
        subtitle_filter = f"subtitles='{subtitle_arg}'"
        if options.font_path:
            fonts_dir = Path(options.font_path).expanduser().resolve().parent
            subtitle_filter += f":fontsdir='{_escape_filter_path(fonts_dir)}'"
        filter_steps.append(subtitle_filter)

        command = [
            ffmpeg,
            "-y",
            "-i",
            str(input_video_path),
            "-vf",
            ",".join(filter_steps),
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-metadata:s:v:0",
            "rotate=0",
            str(output_path),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "ffmpeg subtitle burn failed")

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

    def _probe_video_geometry(self, file_path: Path) -> VideoGeometry | None:
        ffprobe = shutil.which("ffprobe")
        if ffprobe is None:
            return None

        command = [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_streams",
            "-of",
            "json",
            str(file_path),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            return None

        try:
            payload = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError:
            return None

        streams = payload.get("streams") or []
        if not streams:
            return None

        stream = streams[0]
        try:
            encoded_width = int(stream.get("width") or 0)
            encoded_height = int(stream.get("height") or 0)
        except (TypeError, ValueError):
            return None
        if encoded_width <= 0 or encoded_height <= 0:
            return None

        rotation_degrees = 0
        for side_data in stream.get("side_data_list") or []:
            normalized_rotation = _normalize_rotation_degrees(side_data.get("rotation"))
            if normalized_rotation is not None:
                rotation_degrees = normalized_rotation
                break
        if rotation_degrees == 0:
            rotation_degrees = _normalize_rotation_degrees((stream.get("tags") or {}).get("rotate")) or 0

        if rotation_degrees in (90, 270):
            display_width = encoded_height
            display_height = encoded_width
        else:
            display_width = encoded_width
            display_height = encoded_height

        return VideoGeometry(
            encoded_width=encoded_width,
            encoded_height=encoded_height,
            rotation_degrees=rotation_degrees,
            display_width=display_width,
            display_height=display_height,
            is_portrait_display=display_height > display_width,
        )

    def _rotation_filter_steps(self, file_path: Path) -> list[str]:
        geometry = self._probe_video_geometry(file_path)
        if geometry is None:
            return []
        if geometry.rotation_degrees == 90:
            return ["transpose=clock"]
        if geometry.rotation_degrees == 180:
            return ["transpose=clock", "transpose=clock"]
        if geometry.rotation_degrees == 270:
            return ["transpose=cclock"]
        return []

    def _supports_libass(self, ffmpeg_binary: str) -> bool:
        command = [ffmpeg_binary, "-hide_banner", "-filters"]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            return False
        filters_text = f"{completed.stdout}\n{completed.stderr}"
        return " subtitles " in filters_text or filters_text.rstrip().endswith(" subtitles")


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


def _normalize_rotation_degrees(value: object) -> int | None:
    if value is None:
        return None
    try:
        degrees = int(round(float(str(value).strip())))
    except (TypeError, ValueError):
        return None
    return degrees % 360


def _resolve_ffmpeg_binary() -> str | None:
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _escape_filter_path(path: Path) -> str:
    raw = str(path)
    return raw.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
