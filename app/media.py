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
from app.schemas import CaptionCue, CaptionRenderOptions, MediaInfo


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

    def probe_video_geometry(self, file_path: Path):
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
            ffmpeg, "-y", "-noautorotate", "-i", str(input_path),
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

        command = [ffmpeg, "-y", "-noautorotate", "-i", str(input_path), "-ss", str(start), "-t", str(end - start)]
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
        *,
        apply_rotation: bool = True,
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
            rotation_steps = self._rotation_filter_steps(path) if apply_rotation else []
            normalize_steps = [
                *rotation_steps,
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

        flat_inputs: list[str] = []
        for clip_path in expanded_clip_paths:
            flat_inputs.extend(["-noautorotate", "-i", str(clip_path)])
        flat_inputs.extend(["-i", str(audio_path)])

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
        *,
        apply_rotation: bool = False,
    ) -> None:
        ffmpeg = _resolve_ffmpeg_binary()
        if ffmpeg is None:
            raise RuntimeError("ffmpeg is required for subtitle rendering")
        if not self._supports_libass(ffmpeg):
            raise RuntimeError("ffmpeg subtitle rendering is unavailable (libass/subtitles filter missing)")

        subtitle_arg = _escape_filter_path(subtitle_path)
        # By default, subtitle burn assumes the video was already re-encoded upright
        # earlier in the pipeline.  When apply_rotation is True (e.g. the editor-render
        # path where the stored preview may still carry rotation metadata), we prepend
        # rotation filters so the subtitle coordinate system matches the upright frame.
        filter_steps: list[str] = []
        if apply_rotation:
            filter_steps.extend(self._rotation_filter_steps(input_video_path))
        subtitle_filter = f"subtitles='{subtitle_arg}'"
        if options.font_path:
            fonts_dir = Path(options.font_path).expanduser().resolve().parent
            subtitle_filter += f":fontsdir='{_escape_filter_path(fonts_dir)}'"
        filter_steps.append(subtitle_filter)

        command = [
            ffmpeg,
            "-y",
            "-noautorotate",
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

    def render_caption_overlay_video(
        self,
        subtitle_path: Path,
        output_path: Path,
        duration_seconds: float,
        options: CaptionRenderOptions,
        *,
        fps: int = 30,
    ) -> None:
        ffmpeg = _resolve_ffmpeg_binary()
        if ffmpeg is None:
            raise RuntimeError("ffmpeg is required for caption overlay rendering")
        if not self._supports_libass(ffmpeg):
            raise RuntimeError("ffmpeg caption overlay rendering is unavailable (libass/subtitles filter missing)")

        safe_duration = max(0.1, float(duration_seconds))
        subtitle_arg = _escape_filter_path(subtitle_path)
        subtitle_filter = f"subtitles='{subtitle_arg}'"
        if options.font_path:
            fonts_dir = Path(options.font_path).expanduser().resolve().parent
            subtitle_filter += f":fontsdir='{_escape_filter_path(fonts_dir)}'"

        canvas = (
            f"color=color=black@0.0:size={options.play_res_x}x{options.play_res_y}:"
            f"rate={fps}:duration={safe_duration}"
        )
        command = [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            canvas,
            "-vf",
            f"format=rgba,{subtitle_filter}",
            "-an",
            "-c:v",
            "qtrle",
            "-pix_fmt",
            "argb",
            str(output_path),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "ffmpeg caption overlay render failed")

    def burn_captions_moviepy(
        self,
        input_video_path: Path,
        output_path: Path,
        cues: list[CaptionCue],
        options: CaptionRenderOptions,
    ) -> None:
        """Burn captions into video using MoviePy/Pillow text rendering."""
        from moviepy import CompositeVideoClip, TextClip, VideoFileClip

        video = VideoFileClip(str(input_video_path))
        final = None
        text_clips = []
        try:
            video_w, video_h = video.size

            font_color = _ass_color_to_hex(options.primary_color)
            outline_color = _ass_color_to_hex(options.outline_color)

            # Use a concrete font file when configured, otherwise try the named font first
            # and fall back to MoviePy's default Pillow font if that lookup fails.
            preferred_font = options.font_path or (options.font_name or None)

            # Scale from PlayRes coordinate space to actual video pixels.
            scale_y = video_h / max(options.play_res_y, 1)
            scale_x = video_w / max(options.play_res_x, 1)
            pixel_font_size = max(16, round(options.font_size * scale_y))
            pixel_bottom_margin = max(12, round(options.bottom_margin * scale_y))
            text_max_width = max(100, video_w - round((options.margin_left + options.margin_right) * scale_x))
            stroke_width = max(1, round(options.outline_width * scale_y))

            def _build_text_clip(display_text: str):
                common_kwargs = {
                    "text": display_text,
                    "font_size": pixel_font_size,
                    "color": font_color,
                    "stroke_color": outline_color,
                    "stroke_width": stroke_width,
                    "method": "caption",
                    "size": (text_max_width, None),
                    "text_align": "center",
                    "horizontal_align": "center",
                }
                if preferred_font:
                    try:
                        return TextClip(font=preferred_font, **common_kwargs)
                    except Exception:
                        # Fall back to the default font instead of failing the whole render.
                        pass
                return TextClip(**common_kwargs)

            for cue in cues:
                text = cue.text.strip()
                if not text:
                    continue

                start_s = cue.start_ms / 1000.0
                end_s = cue.end_ms / 1000.0
                duration = max(0.05, end_s - start_s)

                display_text = text.replace("\\N", "\n").replace("\\n", "\n")
                txt_clip = _build_text_clip(display_text)

                y_pos = video_h - pixel_bottom_margin - txt_clip.size[1]
                txt_clip = (
                    txt_clip
                    .with_position(("center", y_pos))
                    .with_start(start_s)
                    .with_duration(duration)
                )
                text_clips.append(txt_clip)

            if not text_clips:
                import shutil

                shutil.copyfile(input_video_path, output_path)
                return

            final = CompositeVideoClip([video, *text_clips])
            final.write_videofile(
                str(output_path),
                codec="libx264",
                preset="fast",
                audio_codec="aac",
                audio_bitrate="128k",
                logger=None,
            )
        except Exception as exc:
            raise RuntimeError(f"MoviePy caption render failed: {exc}") from exc
        finally:
            for text_clip in text_clips:
                close = getattr(text_clip, "close", None)
                if callable(close):
                    close()
            if final is not None:
                final.close()
            video.close()

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

    def _probe_video_geometry(self, file_path: Path):
        ffprobe = shutil.which("ffprobe")
        if ffprobe is not None:
            result = self._probe_geometry_ffprobe(file_path, ffprobe)
            if result is not None:
                return result
        # Fall back to parsing ffmpeg -i stderr when ffprobe is unavailable.
        ffmpeg = _resolve_ffmpeg_binary()
        if ffmpeg is not None:
            return self._probe_geometry_ffmpeg(file_path, ffmpeg)
        return None

    @staticmethod
    def _probe_geometry_ffprobe(file_path: Path, ffprobe: str):
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
            payload = json.loads(getattr(completed, "stdout", "") or "{}")
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
                # displaymatrix rotation is the negative of the rotate tag convention;
                # negate it so downstream transpose mapping stays consistent.
                rotation_degrees = (360 - normalized_rotation) % 360
                break
        if rotation_degrees == 0:
            rotation_degrees = _normalize_rotation_degrees((stream.get("tags") or {}).get("rotate")) or 0

        display_width = encoded_height if rotation_degrees in (90, 270) else encoded_width
        display_height = encoded_width if rotation_degrees in (90, 270) else encoded_height

        return {
            "encoded_width": encoded_width,
            "encoded_height": encoded_height,
            "rotation_degrees": rotation_degrees,
            "display_width": display_width,
            "display_height": display_height,
            "is_portrait_display": display_height > display_width,
        }

    @staticmethod
    def _probe_geometry_ffmpeg(file_path: Path, ffmpeg: str):
        """Parse video geometry from ``ffmpeg -i`` stderr output."""
        command = [ffmpeg, "-i", str(file_path)]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        stderr = completed.stderr or ""

        # Extract dimensions from "Video: ... 1920x1080" stream line.
        dim_match = re.search(r"Video:.*?\b(\d{2,5})x(\d{2,5})\b", stderr)
        if not dim_match:
            return None
        encoded_width = int(dim_match.group(1))
        encoded_height = int(dim_match.group(2))

        rotation_degrees = 0
        # Check displaymatrix rotation (e.g. "rotation of -90.00 degrees").
        # Negate because displaymatrix convention is opposite to the rotate tag.
        dm_match = re.search(r"displaymatrix:.*?rotation of\s+([-\d.]+)\s+degrees", stderr)
        if dm_match:
            raw = _normalize_rotation_degrees(dm_match.group(1)) or 0
            rotation_degrees = (360 - raw) % 360
        # Fall back to rotate tag in metadata.
        if rotation_degrees == 0:
            tag_match = re.search(r"rotate\s*:\s*([-\d]+)", stderr)
            if tag_match:
                rotation_degrees = _normalize_rotation_degrees(tag_match.group(1)) or 0

        display_width = encoded_height if rotation_degrees in (90, 270) else encoded_width
        display_height = encoded_width if rotation_degrees in (90, 270) else encoded_height

        return {
            "encoded_width": encoded_width,
            "encoded_height": encoded_height,
            "rotation_degrees": rotation_degrees,
            "display_width": display_width,
            "display_height": display_height,
            "is_portrait_display": display_height > display_width,
        }

    def _rotation_filter_steps(self, file_path: Path) -> list[str]:
        geometry = self._probe_video_geometry(file_path)
        if geometry is None:
            return []

        rotation_degrees = int(geometry.get("rotation_degrees", 0))
        if rotation_degrees == 90:
            return ["transpose=clock"]
        if rotation_degrees == 180:
            return ["transpose=clock", "transpose=clock"]
        if rotation_degrees == 270:
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


def _ass_color_to_hex(ass_color: str) -> str:
    """Convert ASS colour ``&HAABBGGRR`` to ``#RRGGBB`` for Pillow."""
    raw = ass_color.strip().lstrip("&").lstrip("H").lstrip("h")
    if len(raw) == 8:
        # AABBGGRR → RRGGBB
        return f"#{raw[6:8]}{raw[4:6]}{raw[2:4]}"
    if len(raw) == 6:
        # BBGGRR → RRGGBB
        return f"#{raw[4:6]}{raw[2:4]}{raw[0:2]}"
    return ass_color
