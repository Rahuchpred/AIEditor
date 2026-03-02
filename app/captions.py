from __future__ import annotations

import math
from pathlib import Path

from app.schemas import CaptionCue, CaptionRenderOptions, EditableCaptionCue, TimedTextSegment

_MIN_CUE_MS = 600
_MAX_CUE_MS = 3500
_MIN_EDITABLE_CUE_MS = 300


def default_caption_render_options(
    *,
    frame_width: int = 1920,
    frame_height: int = 1080,
    font_path: str = "",
    font_name: str = "Arial",
    font_size: int | None = None,
) -> CaptionRenderOptions:
    is_portrait = frame_height > frame_width
    if is_portrait:
        resolved_font_size = font_size if font_size is not None else max(
            28, round(frame_height * 0.04))
        alignment = 2
        margin_left = 24
        margin_right = 24
        bottom_margin = max(40, round(frame_height * 0.05))
        max_chars_per_line = 18
        max_lines = 2
        soft_wrap_threshold = 16
        soft_wrap_increment_limit = 4
        angle = 0
    else:
        resolved_font_size = font_size if font_size is not None else max(
            28, round(frame_height * 0.04))
        alignment = 2
        margin_left = 48
        margin_right = 48
        bottom_margin = max(60, round(frame_height * 0.08))
        max_chars_per_line = 32
        max_lines = 2
        soft_wrap_threshold = 26
        soft_wrap_increment_limit = 6
        angle = 0

    return CaptionRenderOptions(
        font_path=font_path,
        font_name=font_name,
        font_size=resolved_font_size,
        primary_color="&H00FFFFFF",
        outline_color="&H00000000",
        outline_width=3,
        angle=angle,
        alignment=alignment,
        margin_left=margin_left,
        margin_right=margin_right,
        bottom_margin=bottom_margin,
        max_chars_per_line=max_chars_per_line,
        max_lines=max_lines,
        soft_wrap_threshold=soft_wrap_threshold,
        soft_wrap_increment_limit=soft_wrap_increment_limit,
        play_res_x=frame_width,
        play_res_y=frame_height,
    )


def segments_to_raw_cues(segments: list[TimedTextSegment]) -> list[CaptionCue]:
    raw_cues: list[CaptionCue] = []
    for segment in segments:
        if segment.start_ms is None or segment.end_ms is None or segment.end_ms <= segment.start_ms:
            continue
        raw_cues.append(
            CaptionCue(
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                text=str(segment.text or ""),
            )
        )
    return raw_cues


def shape_caption_cues(
    cues: list[CaptionCue],
    options: CaptionRenderOptions | None = None,
) -> list[CaptionCue]:
    options = options or default_caption_render_options()
    shaped_cues: list[CaptionCue] = []
    for cue in cues:
        if cue.end_ms <= cue.start_ms:
            continue
        cleaned = _normalize_text(cue.text)
        if not cleaned:
            continue

        chunks = _split_text(cleaned, options)
        if not chunks:
            continue

        total_duration = max(cue.end_ms - cue.start_ms, _MIN_CUE_MS)
        step = max(total_duration // len(chunks), 1)
        cursor = cue.start_ms

        for index, chunk in enumerate(chunks):
            next_cursor = cue.end_ms if index == len(
                chunks) - 1 else min(cue.end_ms, cursor + step)
            if next_cursor <= cursor:
                next_cursor = min(cue.end_ms, cursor + _MIN_CUE_MS)
            shaped_cues.append(CaptionCue(
                start_ms=cursor, end_ms=next_cursor, text=chunk))
            cursor = next_cursor

    return _normalize_cue_lengths(shaped_cues)


def segments_to_caption_cues(
    segments: list[TimedTextSegment],
    options: CaptionRenderOptions | None = None,
) -> list[CaptionCue]:
    return shape_caption_cues(segments_to_raw_cues(segments), options)


def remap_cues_after_cuts(cues: list[CaptionCue], cut_regions: list[dict[str, float]]) -> list[CaptionCue]:
    if not cues:
        return []

    cuts_ms = _normalized_cut_ranges_ms(cut_regions)
    if not cuts_ms:
        return cues

    remapped: list[CaptionCue] = []
    for cue in cues:
        surviving_fragments = _surviving_fragments(
            cue.start_ms, cue.end_ms, cuts_ms)
        if not surviving_fragments:
            continue

        if len(surviving_fragments) == 1:
            start_ms, end_ms = surviving_fragments[0]
            remapped.append(
                CaptionCue(
                    start_ms=_shift_ms_after_cuts(start_ms, cuts_ms),
                    end_ms=_shift_ms_after_cuts(end_ms, cuts_ms),
                    text=cue.text,
                )
            )
            continue

        fragments = _split_text_across_fragments(cue.text, surviving_fragments)
        for (start_ms, end_ms), fragment_text in fragments:
            remapped.append(
                CaptionCue(
                    start_ms=_shift_ms_after_cuts(start_ms, cuts_ms),
                    end_ms=_shift_ms_after_cuts(end_ms, cuts_ms),
                    text=fragment_text,
                )
            )

    return _normalize_cue_lengths(remapped)


def normalize_edited_cues(cues: list[EditableCaptionCue]) -> list[CaptionCue]:
    normalized: list[CaptionCue] = []
    for cue in sorted(cues, key=lambda item: (item.start_ms, item.end_ms, item.id)):
        start_ms = max(0, int(cue.start_ms))
        end_ms = int(cue.end_ms)
        text = str(cue.text or "").strip()
        if not text:
            continue

        if end_ms <= start_ms:
            end_ms = start_ms + _MIN_EDITABLE_CUE_MS
        elif end_ms - start_ms < _MIN_EDITABLE_CUE_MS:
            end_ms = start_ms + _MIN_EDITABLE_CUE_MS

        if normalized and start_ms < normalized[-1].end_ms:
            start_ms = normalized[-1].end_ms
            end_ms = max(end_ms, start_ms + _MIN_EDITABLE_CUE_MS)

        normalized.append(CaptionCue(start_ms=start_ms, end_ms=end_ms, text=text))

    return normalized


def write_ass_subtitles(
    cues: list[CaptionCue],
    output_path: Path,
    options: CaptionRenderOptions,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        f"PlayResX: {options.play_res_x}",
        f"PlayResY: {options.play_res_y}",
        "",
        "[V4+ Styles]",
        (
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
            "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
            "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
        ),
        (
            "Style: Default,"
            f"{options.font_name},{options.font_size},{options.primary_color},&H000000FF,"
            f"{options.outline_color},&H64000000,-1,0,0,0,100,100,0,{options.angle},1,"
            f"{options.outline_width},0,{options.alignment},{options.margin_left},{options.margin_right},"
            f"{options.bottom_margin},1"
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    for cue in cues:
        lines.append(
            "Dialogue: 0,"
            f"{_ass_timestamp(cue.start_ms)},{_ass_timestamp(cue.end_ms)},Default,,0,0,0,,{_escape_ass_text(cue.text)}"
        )

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _normalize_text(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def _split_text(text: str, options: CaptionRenderOptions) -> list[str]:
    words = text.split()
    if not words:
        return []

    lines: list[str] = []
    current: list[str] = []
    current_len = 0
    for word in words:
        next_increment = len(word) + (1 if current else 0)
        projected = current_len + next_increment
        if (
            current
            and current_len >= options.soft_wrap_threshold
            and next_increment > options.soft_wrap_increment_limit
        ):
            lines.append(" ".join(current))
            current = [word]
            current_len = len(word)
        elif current and projected > options.max_chars_per_line:
            lines.append(" ".join(current))
            current = [word]
            current_len = len(word)
        else:
            current.append(word)
            current_len = projected
    if current:
        lines.append(" ".join(current))

    chunks: list[str] = []
    for index in range(0, len(lines), options.max_lines):
        chunk_lines = lines[index:index + options.max_lines]
        chunks.append("\n".join(chunk_lines))
    return chunks


def _normalize_cue_lengths(cues: list[CaptionCue]) -> list[CaptionCue]:
    normalized: list[CaptionCue] = []
    for index, cue in enumerate(cues):
        start_ms = cue.start_ms
        next_start = cues[index + 1].start_ms if index + \
            1 < len(cues) else None
        end_ms = cue.end_ms

        min_end = start_ms + _MIN_CUE_MS
        if end_ms < min_end:
            end_ms = min_end if next_start is None else min(
                min_end, next_start)

        max_end = start_ms + _MAX_CUE_MS
        if end_ms > max_end:
            end_ms = max_end if next_start is None else min(
                max_end, next_start)

        if next_start is not None and end_ms > next_start:
            end_ms = next_start

        if end_ms <= start_ms:
            continue

        normalized.append(CaptionCue(start_ms=start_ms,
                          end_ms=end_ms, text=cue.text))
    return normalized


def _normalized_cut_ranges_ms(cut_regions: list[dict[str, float]]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for region in cut_regions:
        start = int(float(region["start_s"]) * 1000)
        end = int(float(region["end_s"]) * 1000)
        if end <= start:
            continue
        ranges.append((start, end))
    return sorted(ranges)


def _surviving_fragments(
    start_ms: int,
    end_ms: int,
    cuts_ms: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    fragments: list[tuple[int, int]] = []
    cursor = start_ms
    for cut_start, cut_end in cuts_ms:
        if cut_end <= cursor:
            continue
        if cut_start >= end_ms:
            break
        if cut_start > cursor:
            fragments.append((cursor, min(cut_start, end_ms)))
        cursor = max(cursor, cut_end)
        if cursor >= end_ms:
            break
    if cursor < end_ms:
        fragments.append((cursor, end_ms))
    return [(start, end) for start, end in fragments if end > start]


def _shift_ms_after_cuts(value_ms: int, cuts_ms: list[tuple[int, int]]) -> int:
    removed = 0
    for cut_start, cut_end in cuts_ms:
        if value_ms <= cut_start:
            break
        removed += max(0, min(value_ms, cut_end) - cut_start)
    return max(0, value_ms - removed)


def _split_text_across_fragments(
    text: str,
    fragments: list[tuple[int, int]],
) -> list[tuple[tuple[int, int], str]]:
    words = text.split()
    if not words:
        return []
    if len(fragments) == 1:
        return [(fragments[0], text)]

    durations = [max(1, end - start) for start, end in fragments]
    total_duration = sum(durations)
    raw_counts = [max(1, round(len(words) * (duration / total_duration)))
                  for duration in durations]

    while sum(raw_counts) > len(words):
        for index in range(len(raw_counts) - 1, -1, -1):
            if raw_counts[index] > 1 and sum(raw_counts) > len(words):
                raw_counts[index] -= 1
    while sum(raw_counts) < len(words):
        raw_counts[-1] += 1

    chunks: list[tuple[tuple[int, int], str]] = []
    cursor = 0
    for (start, end), count in zip(fragments, raw_counts):
        fragment_words = words[cursor:cursor + count]
        cursor += count
        if not fragment_words:
            continue
        chunks.append(((start, end), " ".join(fragment_words)))
    return chunks


def _ass_timestamp(value_ms: int) -> str:
    total_centiseconds = max(0, int(math.floor(value_ms / 10)))
    hours = total_centiseconds // 360000
    minutes = (total_centiseconds % 360000) // 6000
    seconds = (total_centiseconds % 6000) // 100
    centiseconds = total_centiseconds % 100
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"


def _escape_ass_text(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")
    return escaped.replace("\n", "\\N")
