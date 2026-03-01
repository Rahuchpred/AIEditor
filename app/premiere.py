from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote
from xml.dom import minidom
from xml.etree.ElementTree import Element, SubElement, tostring

DEFAULT_FPS = 30


@dataclass(slots=True)
class PremiereClip:
    name: str
    media_name: str
    sequence_start_s: float
    sequence_end_s: float
    source_in_s: float
    source_out_s: float
    source_duration_s: float


@dataclass(slots=True)
class PremiereMarker:
    name: str
    start_s: float
    end_s: float
    comment: str = ""


def build_premiere_xml(
    sequence_name: str,
    video_clips: list[PremiereClip],
    *,
    audio_clips: list[PremiereClip] | None = None,
    markers: list[PremiereMarker] | None = None,
    width: int = 1080,
    height: int = 1920,
    fps: int = DEFAULT_FPS,
) -> bytes:
    audio_clips = audio_clips or []
    markers = markers or []
    sequence_duration_frames = _sequence_duration_frames(video_clips, audio_clips, markers, fps)

    root = Element("xmeml", version="5")
    sequence = SubElement(root, "sequence")
    SubElement(sequence, "name").text = sequence_name
    SubElement(sequence, "duration").text = str(sequence_duration_frames)
    _append_rate(sequence, fps)
    _append_timecode(sequence, fps)

    media = SubElement(sequence, "media")

    video = SubElement(media, "video")
    video_format = SubElement(video, "format")
    sample_characteristics = SubElement(video_format, "samplecharacteristics")
    _append_rate(sample_characteristics, fps)
    SubElement(sample_characteristics, "width").text = str(width)
    SubElement(sample_characteristics, "height").text = str(height)
    SubElement(sample_characteristics, "anamorphic").text = "FALSE"
    SubElement(sample_characteristics, "pixelaspectratio").text = "square"
    SubElement(sample_characteristics, "fielddominance").text = "none"
    video_track = SubElement(video, "track")
    for index, clip in enumerate(video_clips, start=1):
        _append_clipitem(video_track, clip, fps=fps, media_type="video", index=index)

    if audio_clips:
        audio = SubElement(media, "audio")
        audio_format = SubElement(audio, "format")
        audio_sample_characteristics = SubElement(audio_format, "samplecharacteristics")
        SubElement(audio_sample_characteristics, "depth").text = "16"
        SubElement(audio_sample_characteristics, "samplerate").text = "48000"
        audio_track = SubElement(audio, "track")
        for index, clip in enumerate(audio_clips, start=1):
            _append_clipitem(audio_track, clip, fps=fps, media_type="audio", index=index)

    if markers:
        markers_node = SubElement(sequence, "markers")
        for marker in markers:
            marker_node = SubElement(markers_node, "marker")
            SubElement(marker_node, "name").text = marker.name
            SubElement(marker_node, "comment").text = marker.comment
            SubElement(marker_node, "in").text = str(_seconds_to_frames(marker.start_s, fps))
            SubElement(marker_node, "out").text = str(_seconds_to_frames(max(marker.end_s, marker.start_s), fps))

    raw_xml = tostring(root, encoding="utf-8")
    pretty = minidom.parseString(raw_xml).toprettyxml(indent="  ", encoding="UTF-8").decode("utf-8")
    lines = [line for line in pretty.splitlines() if line.strip()]
    if lines and lines[0].startswith("<?xml"):
        lines.insert(1, "<!DOCTYPE xmeml>")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _append_clipitem(track: Element, clip: PremiereClip, *, fps: int, media_type: str, index: int) -> None:
    clipitem = SubElement(track, "clipitem", id=f"{media_type}-clip-{index}")
    SubElement(clipitem, "name").text = clip.name
    _append_rate(clipitem, fps)
    SubElement(clipitem, "enabled").text = "TRUE"
    SubElement(clipitem, "start").text = str(_seconds_to_frames(clip.sequence_start_s, fps))
    SubElement(clipitem, "end").text = str(_seconds_to_frames(clip.sequence_end_s, fps))
    SubElement(clipitem, "in").text = str(_seconds_to_frames(clip.source_in_s, fps))
    SubElement(clipitem, "out").text = str(_seconds_to_frames(clip.source_out_s, fps))
    if media_type == "video":
        SubElement(clipitem, "alphatype").text = "none"

    file_node = SubElement(clipitem, "file", id=f"{media_type}-file-{index}")
    SubElement(file_node, "name").text = clip.media_name
    SubElement(file_node, "pathurl").text = _placeholder_path_url(clip.media_name)
    _append_rate(file_node, fps)
    SubElement(file_node, "duration").text = str(_seconds_to_frames(clip.source_duration_s, fps))

    media = SubElement(file_node, "media")
    if media_type == "video":
        video = SubElement(media, "video")
        sample_characteristics = SubElement(video, "samplecharacteristics")
        _append_rate(sample_characteristics, fps)
    else:
        audio = SubElement(media, "audio")
        SubElement(audio, "channelcount").text = "2"


def _append_rate(node: Element, fps: int) -> None:
    rate = SubElement(node, "rate")
    SubElement(rate, "timebase").text = str(fps)
    SubElement(rate, "ntsc").text = "FALSE"


def _append_timecode(node: Element, fps: int) -> None:
    timecode = SubElement(node, "timecode")
    _append_rate(timecode, fps)
    SubElement(timecode, "string").text = "00:00:00:00"
    SubElement(timecode, "frame").text = "0"
    SubElement(timecode, "displayformat").text = "NDF"


def _sequence_duration_frames(
    video_clips: list[PremiereClip],
    audio_clips: list[PremiereClip],
    markers: list[PremiereMarker],
    fps: int,
) -> int:
    endpoints = [
        *(_seconds_to_frames(clip.sequence_end_s, fps) for clip in video_clips),
        *(_seconds_to_frames(clip.sequence_end_s, fps) for clip in audio_clips),
        *(_seconds_to_frames(marker.end_s, fps) for marker in markers),
    ]
    return max(endpoints, default=0)


def _seconds_to_frames(seconds: float, fps: int) -> int:
    return max(0, int(round(float(seconds) * fps)))


def _placeholder_path_url(file_name: str) -> str:
    safe_name = Path(file_name or "media").name or "media"
    return f"file://localhost/{quote(safe_name)}"
