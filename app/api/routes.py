from __future__ import annotations

import json
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.background import BackgroundTask

from app.captions import (
    default_caption_render_options,
    normalize_edited_cues,
    remap_cues_after_cuts,
    segments_to_caption_cues,
    segments_to_raw_cues,
    shape_caption_cues,
)
from app.container import get_container
from app.media import FfmpegMediaProcessor
from app.providers import TranscriptionProviderError
from app.schemas import (
    AnalysisJobAccepted,
    AnalysisJobResult,
    AnalysisJobStatus,
    AutoCutEditorSessionResponse,
    CaptionRenderOptions,
    CaptionTrackSettings,
    CutRegion,
    EditableCaptionCue,
    RenderEditedCaptionsRequest,
)

router = APIRouter()


def _container_from_request(request: Request):
    return getattr(request.app.state, "container", None) or get_container()


def _service_from_request(request: Request):
    container = _container_from_request(request)
    return container.create_analysis_service()


def _transcription_provider_from_request(request: Request):
    container = _container_from_request(request)
    return container.transcription_provider


def _caption_options_for_video(media_proc, file_path: Path, *, font_path: str, font_name: str):
    geometry_probe = getattr(media_proc, "probe_video_geometry", None)
    geometry = geometry_probe(file_path) if callable(geometry_probe) else None
    frame_width = int(geometry.get("display_width", 1920)) if geometry else 1920
    frame_height = int(geometry.get("display_height", 1080)) if geometry else 1080
    return default_caption_render_options(
        frame_width=frame_width,
        frame_height=frame_height,
        font_path=font_path,
        font_name=font_name,
    )


def _clamp_vertical_position_pct(value: float) -> float:
    return max(10.0, min(90.0, round(float(value), 1)))


def _caption_track_from_options(options: CaptionRenderOptions) -> CaptionTrackSettings:
    baseline_pct = ((options.play_res_y - options.bottom_margin) / max(options.play_res_y, 1)) * 100
    return CaptionTrackSettings(vertical_position_pct=_clamp_vertical_position_pct(baseline_pct))


def _bottom_margin_from_track_settings(play_res_y: int, track_settings: CaptionTrackSettings) -> int:
    bottom_margin = round(play_res_y - (play_res_y * track_settings.vertical_position_pct / 100.0))
    return max(24, min(play_res_y - 24, bottom_margin))


def _parse_cut_regions(raw_regions: str) -> list[CutRegion]:
    payload = json.loads(raw_regions)
    if not isinstance(payload, list):
        raise ValueError("cut_regions must be a JSON array")
    parsed: list[CutRegion] = []
    for item in payload:
        parsed_region = CutRegion.model_validate(item)
        if parsed_region.end_s <= parsed_region.start_s:
            continue
        parsed.append(parsed_region)
    return sorted(parsed, key=lambda region: region.start_s)


def _build_keep_ranges(cuts: list[CutRegion], duration: float) -> list[tuple[float, float]]:
    keep_ranges: list[tuple[float, float]] = []
    cursor = 0.0
    for cut in cuts:
        start = max(0.0, float(cut.start_s))
        end = min(duration, float(cut.end_s))
        if start > cursor:
            keep_ranges.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < duration:
        keep_ranges.append((cursor, duration))
    return keep_ranges


def _editable_cues_from_caption_cues(cues: list) -> list[EditableCaptionCue]:
    editable: list[EditableCaptionCue] = []
    for index, cue in enumerate(cues):
        text = str(getattr(cue, "text", "") or "").strip()
        start_ms = int(getattr(cue, "start_ms", 0) or 0)
        end_ms = int(getattr(cue, "end_ms", 0) or 0)
        if not text or end_ms <= start_ms:
            continue
        editable.append(
            EditableCaptionCue(
                id=f"cue_{index + 1:04d}",
                start_ms=start_ms,
                end_ms=end_ms,
                text=text,
            )
        )
    return editable


def _editor_session_preview_key(session_id: str) -> str:
    return f"editor-sessions/{session_id}/preview.mp4"


def _editor_session_manifest_key(session_id: str) -> str:
    return f"editor-sessions/{session_id}/manifest.json"


def _delete_storage_key(storage, key: str) -> None:
    try:
        storage.delete(key)
    except Exception:
        pass


@router.get("/healthz")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


def _build_editor_cues(
    request: Request,
    preview_path: Path,
    cuts: list[CutRegion],
    job_id: str | None,
) -> list[EditableCaptionCue]:
    raw_cues = []
    if job_id:
        try:
            result = _service_from_request(request).get_result(job_id)
            raw_cues = remap_cues_after_cuts(
                segments_to_raw_cues(result.transcript.segments),
                [cut.model_dump() for cut in cuts],
            )
        except Exception:
            raw_cues = []

    if not raw_cues:
        try:
            transcription = _transcription_provider_from_request(request).transcribe(preview_path, None)
        except (TranscriptionProviderError, RuntimeError) as exc:
            raise RuntimeError(f"Caption transcription failed: {exc}") from exc
        raw_cues = segments_to_raw_cues(transcription.segments)

    return _editable_cues_from_caption_cues(raw_cues)


def _render_options_from_manifest(manifest: dict, track_settings: CaptionTrackSettings) -> CaptionRenderOptions:
    play_res_x = int(manifest.get("play_res_x") or 1920)
    play_res_y = int(manifest.get("play_res_y") or 1080)
    return CaptionRenderOptions(
        font_path=str(manifest.get("font_path") or ""),
        font_name=str(manifest.get("font_name") or "Arial"),
        font_size=int(manifest.get("font_size") or 42),
        primary_color=str(manifest.get("primary_color") or "&H00FFFFFF"),
        outline_color=str(manifest.get("outline_color") or "&H00000000"),
        outline_width=int(manifest.get("outline_width") or 3),
        angle=int(manifest.get("angle") or 0),
        alignment=int(manifest.get("alignment") or 2),
        margin_left=int(manifest.get("margin_left") or 40),
        margin_right=int(manifest.get("margin_right") or 40),
        bottom_margin=_bottom_margin_from_track_settings(play_res_y, track_settings),
        max_chars_per_line=int(manifest.get("max_chars_per_line") or 32),
        max_lines=int(manifest.get("max_lines") or 2),
        soft_wrap_threshold=int(manifest.get("soft_wrap_threshold") or 26),
        soft_wrap_increment_limit=int(manifest.get("soft_wrap_increment_limit") or 6),
        play_res_x=play_res_x,
        play_res_y=play_res_y,
    )


@router.get("/", response_class=HTMLResponse)
def ui_playground() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AIEdit API Playground</title>
  <style>
    :root {
      --bg: #0b1020;
      --panel: #121a2c;
      --panel-strong: #18233a;
      --text: #e7eefc;
      --muted: #9fb0d1;
      --border: #2a385a;
      --brand: #4f7cff;
      --brand-hover: #3e68e6;
      --ok: #25c281;
    }
    * { box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      max-width: 980px;
      margin: 0 auto;
      padding: 24px 16px 36px;
      background: radial-gradient(circle at top right, #172442 0%, var(--bg) 40%);
      color: var(--text);
    }
    h1 { margin: 0 0 8px; font-size: 28px; }
    h3 { margin: 0 0 10px; color: #dce7ff; }
    .subtitle { color: var(--muted); margin-bottom: 14px; display: block; }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 12px;
      color: #d9ffe9;
      background: rgba(37, 194, 129, 0.15);
      border: 1px solid rgba(37, 194, 129, 0.45);
      padding: 4px 10px;
      border-radius: 999px;
      margin-bottom: 10px;
    }
    .card {
      border: 1px solid var(--border);
      background: linear-gradient(180deg, var(--panel) 0%, #11192b 100%);
      border-radius: 12px;
      padding: 14px;
      margin: 14px 0;
      box-shadow: 0 8px 20px rgba(5, 9, 20, 0.35);
    }
    .row { display: flex; gap: 12px; flex-wrap: wrap; }
    label { display: block; font-size: 13px; margin-bottom: 6px; color: #c9d8f8; }
    input[type="text"], select {
      width: 260px;
      padding: 8px 10px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel-strong);
      color: var(--text);
      outline: none;
    }
    input[type="text"]::placeholder { color: #8da0c4; }
    input[type="text"]:focus, select:focus {
      border-color: #4d79ff;
      box-shadow: 0 0 0 3px rgba(79, 124, 255, 0.2);
    }
    input[type="file"] { padding: 6px 0; color: var(--muted); }
    input[type="checkbox"] { accent-color: var(--brand); }
    button {
      padding: 8px 12px;
      border: 1px solid var(--brand);
      border-radius: 8px;
      background: var(--brand);
      color: white;
      cursor: pointer;
      font-weight: 600;
    }
    button:hover { background: var(--brand-hover); }
    .ghost {
      background: transparent;
      color: #ccdbff;
      border-color: #5371b7;
    }
    .ghost:hover { background: rgba(79, 124, 255, 0.12); }
    pre {
      background: #091121;
      color: #d9e6ff;
      border: 1px solid #22345d;
      padding: 12px;
      border-radius: 8px;
      overflow: auto;
      min-height: 190px;
    }
    #previewPanel { display: none; margin-bottom: 14px; }
    #previewPanel.visible { display: block; }
    .portrait-stage-card {
      width: 100%;
      max-width: 460px;
      margin-left: auto;
      margin-right: auto;
    }
    .preview-wrap {
      position: relative;
      width: 100%;
      max-width: 420px;
      margin: 0 auto;
      aspect-ratio: 9 / 16;
      background: #060d1a;
      border-radius: 8px;
      overflow: hidden;
      border: 1px solid #22345d;
    }
    .preview-video {
      width: 100%;
      height: 100%;
      object-fit: contain;
      display: block;
    }
    .preview-placeholder {
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      color: #5a6f96;
      font-size: 14px;
      pointer-events: none;
    }
    .preview-controls {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-top: 10px;
      width: 100%;
      max-width: 420px;
      margin-left: auto;
      margin-right: auto;
    }
    .preview-controls button {
      min-width: 70px;
      padding: 6px 10px;
      font-size: 13px;
    }
    .preview-time {
      font-size: 12px;
      color: var(--muted);
      white-space: nowrap;
      margin-left: auto;
      font-variant-numeric: tabular-nums;
    }
    .tl-container {
      position: relative;
      height: 36px;
      cursor: pointer;
      user-select: none;
      -webkit-user-select: none;
      width: 100%;
      max-width: 420px;
      margin: 0 auto;
    }
    .tl-track {
      position: absolute;
      top: 14px;
      left: 0;
      right: 0;
      height: 8px;
      background: #1a2744;
      border-radius: 4px;
      overflow: hidden;
    }
    .tl-fill {
      height: 100%;
      width: 0%;
      background: linear-gradient(90deg, var(--brand) 0%, #6b9aff 100%);
      border-radius: 4px;
      transition: width 0.05s linear;
    }
    .tl-playhead {
      position: absolute;
      top: 8px;
      width: 18px;
      height: 18px;
      margin-left: -9px;
      border-radius: 50%;
      background: var(--brand);
      border: 3px solid #e7eefc;
      box-shadow: 0 0 6px rgba(79, 124, 255, 0.5);
      left: 0%;
      transition: left 0.05s linear;
      z-index: 2;
    }
    .tl-playhead:hover, .tl-playhead.dragging {
      transform: scale(1.25);
      box-shadow: 0 0 12px rgba(79, 124, 255, 0.7);
    }
    .tl-hover-line {
      position: absolute;
      top: 10px;
      width: 1px;
      height: 16px;
      background: rgba(255,255,255,0.3);
      pointer-events: none;
      display: none;
      z-index: 1;
    }
    .tl-preview-overlay {
      position: absolute;
      bottom: 42px;
      transform: translateX(-50%);
      background: #0d1629;
      border: 1px solid #2a385a;
      border-radius: 6px;
      padding: 4px;
      pointer-events: none;
      opacity: 0;
      transition: opacity 0.15s ease;
      z-index: 10;
      box-shadow: 0 4px 16px rgba(0,0,0,0.5);
    }
    .tl-preview-overlay.show { opacity: 1; }
    .tl-preview-canvas {
      display: block;
      border-radius: 4px;
      background: #060d1a;
    }
    .tl-preview-time {
      display: block;
      text-align: center;
      font-size: 11px;
      color: var(--muted);
      margin-top: 3px;
      font-variant-numeric: tabular-nums;
    }
    .tl-cut-region {
      position: absolute;
      top: 11px;
      height: 14px;
      background: rgba(255, 55, 55, 0.45);
      border-radius: 3px;
      pointer-events: none;
      z-index: 1;
    }
    #autoCutCard { display: none; }
    #autoCutCard.visible { display: block; }
    .autocut-info {
      display: flex;
      align-items: center;
      gap: 10px;
      width: 100%;
      max-width: 420px;
      margin-bottom: 10px;
      margin-left: auto;
      margin-right: auto;
      font-size: 13px;
      color: var(--muted);
    }
    .autocut-info .cut-count {
      color: #ff5c5c;
      font-weight: 600;
    }
    .autocut-info .saved-time {
      color: var(--ok);
      font-weight: 600;
    }
    #captionEditorCard { display: none; }
    #captionEditorCard.visible { display: block; }
    .editor-stage {
      width: 100%;
      max-width: 420px;
      margin: 0 auto;
    }
    .editor-preview-wrap {
      position: relative;
    }
    .editor-caption-overlay {
      position: absolute;
      left: 50%;
      top: 78%;
      transform: translate(-50%, -50%);
      width: calc(100% - 36px);
      padding: 0 8px;
      text-align: center;
      font-weight: 700;
      font-size: 26px;
      line-height: 1.2;
      text-shadow:
        -2px -2px 0 rgba(0, 0, 0, 0.95),
        2px -2px 0 rgba(0, 0, 0, 0.95),
        -2px 2px 0 rgba(0, 0, 0, 0.95),
        2px 2px 0 rgba(0, 0, 0, 0.95);
      pointer-events: none;
      z-index: 3;
    }
    .editor-caption-overlay.hidden {
      display: none;
    }
    .editor-controls {
      display: flex;
      align-items: center;
      gap: 10px;
      width: 100%;
      max-width: 420px;
      margin: 10px auto 0;
    }
    .editor-ruler {
      position: relative;
      height: 26px;
      width: 100%;
      max-width: 420px;
      margin: 14px auto 0;
      border-bottom: 1px solid rgba(122, 145, 196, 0.25);
    }
    .editor-ruler-tick {
      position: absolute;
      bottom: 0;
      width: 1px;
      height: 10px;
      background: rgba(159, 176, 209, 0.35);
    }
    .editor-ruler-tick span {
      position: absolute;
      top: -16px;
      left: 50%;
      transform: translateX(-50%);
      font-size: 10px;
      color: var(--muted);
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
    }
    .editor-timeline {
      position: relative;
      width: 100%;
      max-width: 420px;
      height: 72px;
      margin: 8px auto 0;
      border-radius: 10px;
      border: 1px solid #22345d;
      background: #0b1426;
      overflow: hidden;
      user-select: none;
      -webkit-user-select: none;
    }
    .editor-track {
      position: absolute;
      inset: 0;
    }
    .editor-track-fill {
      position: absolute;
      inset: 0 auto 0 0;
      width: 0%;
      background: linear-gradient(90deg, rgba(79, 124, 255, 0.18) 0%, rgba(79, 124, 255, 0.04) 100%);
      pointer-events: none;
    }
    .editor-track-playhead {
      position: absolute;
      top: 0;
      bottom: 0;
      width: 2px;
      background: rgba(255, 255, 255, 0.75);
      pointer-events: none;
      z-index: 4;
    }
    .editor-track-hover {
      position: absolute;
      top: 0;
      bottom: 0;
      width: 1px;
      background: rgba(255,255,255,0.28);
      pointer-events: none;
      display: none;
      z-index: 3;
    }
    .caption-block {
      position: absolute;
      top: 18px;
      height: 38px;
      border-radius: 8px;
      background: linear-gradient(180deg, #ff9b2d 0%, #de6f00 100%);
      color: #fff7eb;
      font-size: 12px;
      font-weight: 700;
      line-height: 38px;
      padding: 0 10px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      cursor: grab;
      border: 1px solid rgba(255,255,255,0.14);
      z-index: 2;
    }
    .caption-block.selected {
      box-shadow: 0 0 0 2px rgba(231, 238, 252, 0.7);
    }
    .caption-block.dragging {
      cursor: grabbing;
      opacity: 0.95;
    }
    .caption-handle {
      position: absolute;
      top: 0;
      width: 8px;
      height: 100%;
      background: rgba(0, 0, 0, 0.18);
      cursor: ew-resize;
    }
    .caption-handle.start { left: 0; border-radius: 8px 0 0 8px; }
    .caption-handle.end { right: 0; border-radius: 0 8px 8px 0; }
    .editor-mini-preview {
      bottom: 84px;
    }
    .cue-inspector {
      width: 100%;
      max-width: 420px;
      margin: 14px auto 0;
      padding: 12px;
      border-radius: 10px;
      border: 1px solid #22345d;
      background: rgba(8, 16, 34, 0.85);
    }
    .cue-inspector textarea {
      width: 100%;
      min-height: 76px;
      resize: vertical;
      padding: 10px;
      border-radius: 8px;
      border: 1px solid var(--border);
      background: var(--panel-strong);
      color: var(--text);
    }
    .cue-inspector-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin-top: 10px;
    }
    .cue-inspector input[type="number"],
    .cue-inspector input[type="range"] {
      width: 100%;
    }
    .cue-nav {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-top: 10px;
    }
    .cue-nav-actions {
      display: flex;
      gap: 8px;
    }
    .cue-meta {
      font-size: 12px;
      color: var(--muted);
      font-variant-numeric: tabular-nums;
    }
    .editor-status {
      margin-top: 10px;
      font-size: 12px;
      color: var(--muted);
    }
    .editor-status.ok { color: var(--ok); }
    .editor-status.err { color: #ff6b6b; }
    .download-link {
      display: inline-block;
      margin-top: 12px;
      color: #bfd0ff;
      text-decoration: none;
    }
    .download-link:hover { color: white; }
  </style>
</head>
<body>
  <nav style="margin-bottom:12px"><a href="/" style="color:var(--muted);text-decoration:none">Transcript & Auto-Cut</a> | <a href="/reel-generator" style="color:var(--muted);text-decoration:none">Reel Generator</a></nav>
  <span class="badge">API playground</span>
  <h1>AIEdit Test UI</h1>
  <small class="subtitle">Use this page to test job creation, status polling, and result retrieval.</small>

  <div class="card">
    <h3>Create Analysis Job</h3>
    <form id="createForm">
      <div class="row">
        <div>
          <label for="media_file">Media File</label>
          <input id="media_file" name="media_file" type="file" accept="audio/*,video/*" required />
        </div>
      </div>
      <div class="row">
        <div>
          <label for="input_language_hint">Input Language Hint</label>
          <input id="input_language_hint" name="input_language_hint" type="text" placeholder="en (optional)" />
        </div>
      </div>
      <div class="row">
        <label><input id="include_raw_transcript" name="include_raw_transcript" type="checkbox" checked /> include_raw_transcript</label>
        <label><input id="include_timestamps" name="include_timestamps" type="checkbox" checked /> include_timestamps</label>
      </div>
      <div class="row">
        <button type="submit">Submit Job</button>
      </div>
    </form>
  </div>

  <div class="card">
    <h3>Status / Result</h3>
    <div class="row">
      <div>
        <label for="job_id">Job ID</label>
        <input id="job_id" type="text" placeholder="Paste job id..." />
      </div>
      <div style="display:flex; align-items:flex-end; gap:8px;">
        <button id="statusBtn" class="ghost" type="button">Get Status</button>
        <button id="resultBtn" class="ghost" type="button">Get Result</button>
      </div>
    </div>
  </div>

  <div class="card portrait-stage-card">
    <h3>Response</h3>
    <div id="previewPanel">
      <div class="preview-wrap">
        <video id="previewVideo" class="preview-video" preload="metadata"></video>
        <div id="previewPlaceholder" class="preview-placeholder">No video loaded</div>
      </div>
      <div class="preview-controls">
        <button id="playPauseBtn" type="button">Play</button>
        <button id="autoCutBtn" class="ghost" type="button" disabled>Open Caption Editor</button>
        <span id="timeDisplay" class="preview-time">0:00 / 0:00</span>
      </div>
      <div id="tlContainer" class="tl-container">
        <div class="tl-track"><div id="tlFill" class="tl-fill"></div></div>
        <div id="tlPlayhead" class="tl-playhead"></div>
        <div id="tlHoverLine" class="tl-hover-line"></div>
        <div id="tlPreview" class="tl-preview-overlay">
          <canvas id="tlCanvas" class="tl-preview-canvas"></canvas>
          <span id="tlPreviewTime" class="tl-preview-time">0:00</span>
        </div>
      </div>
    </div>
    <pre id="out">{}</pre>
  </div>

  <div id="captionEditorCard" class="card portrait-stage-card">
    <h3>Caption Editor</h3>
    <div class="editor-stage">
      <div class="preview-wrap editor-preview-wrap">
        <video id="editorVideo" class="preview-video" preload="metadata"></video>
        <div id="editorCaptionOverlay" class="editor-caption-overlay hidden"></div>
      </div>
      <div class="editor-controls">
        <button id="editorPlayBtn" type="button" class="ghost">Play</button>
        <button id="renderEditorBtn" type="button">Render Final Video</button>
        <span id="editorTimeDisplay" class="preview-time">0:00 / 0:00</span>
      </div>
      <div id="editorRuler" class="editor-ruler"></div>
      <div id="editorTimeline" class="editor-timeline">
        <div id="editorTrack" class="editor-track">
          <div id="editorTrackFill" class="editor-track-fill"></div>
          <div id="editorTrackPlayhead" class="editor-track-playhead"></div>
          <div id="editorTrackHover" class="editor-track-hover"></div>
        </div>
        <div id="editorMiniPreview" class="tl-preview-overlay editor-mini-preview">
          <canvas id="editorMiniCanvas" class="tl-preview-canvas"></canvas>
          <span id="editorMiniTime" class="tl-preview-time">0:00</span>
        </div>
      </div>
      <div class="cue-inspector">
        <label for="cueText">Caption Text</label>
        <textarea id="cueText" placeholder="Select a caption block to edit"></textarea>
        <div class="cue-inspector-grid">
          <div>
            <label for="cueStartInput">Start (s)</label>
            <input id="cueStartInput" type="number" min="0" step="0.1" />
          </div>
          <div>
            <label for="cueEndInput">End (s)</label>
            <input id="cueEndInput" type="number" min="0" step="0.1" />
          </div>
          <div>
            <label for="cueDurationInput">Duration (s)</label>
            <input id="cueDurationInput" type="number" min="0.3" step="0.1" />
          </div>
        </div>
        <div style="margin-top:12px;">
          <label for="captionHeightInput">Caption Height</label>
          <input id="captionHeightInput" type="range" min="10" max="90" step="1" />
        </div>
        <div class="cue-nav">
          <div class="cue-nav-actions">
            <button id="prevCueBtn" type="button" class="ghost">Previous</button>
            <button id="nextCueBtn" type="button" class="ghost">Next</button>
          </div>
          <span id="cueMeta" class="cue-meta">No cue selected</span>
        </div>
        <div id="editorStatus" class="editor-status"></div>
      </div>
    </div>
  </div>

  <div id="autoCutCard" class="card portrait-stage-card">
    <h3>Rendered Video</h3>
    <div id="autoCutInfo" class="autocut-info"></div>
    <div class="preview-wrap">
      <video id="autoCutVideo" class="preview-video" controls preload="metadata"></video>
    </div>
    <a id="autoCutDownload" class="download-link" href="#" download="autocut.mp4">Download Rendered Video</a>
  </div>

  <script>
    const out = document.getElementById("out");
    const jobInput = document.getElementById("job_id");

    // --- Video Preview Panel ---
    const previewPanel = document.getElementById("previewPanel");
    const previewVideo = document.getElementById("previewVideo");
    const previewPlaceholder = document.getElementById("previewPlaceholder");
    const playPauseBtn = document.getElementById("playPauseBtn");
    const timeDisplay = document.getElementById("timeDisplay");
    const previewState = { isPlaying: false, currentTime: 0, duration: 0 };
    let previewObjectUrl = null;

    function fmtTime(sec) {
      const s = Math.max(0, Math.floor(sec));
      const m = Math.floor(s / 60);
      return m + ":" + String(s % 60).padStart(2, "0");
    }

    function updateTimeDisplay() {
      timeDisplay.textContent = fmtTime(previewState.currentTime) + " / " + fmtTime(previewState.duration);
    }

    document.getElementById("media_file").addEventListener("change", function () {
      const file = this.files[0];
      if (previewObjectUrl) { URL.revokeObjectURL(previewObjectUrl); previewObjectUrl = null; }
      previewState.isPlaying = false;
      previewState.currentTime = 0;
      previewState.duration = 0;
      playPauseBtn.textContent = "Play";
      updateTimeDisplay();

      if (file && file.type.startsWith("video/")) {
        previewObjectUrl = URL.createObjectURL(file);
        previewVideo.src = previewObjectUrl;
        previewVideo.load();
        previewPlaceholder.style.display = "none";
        previewPanel.classList.add("visible");
      } else {
        previewVideo.removeAttribute("src");
        previewPlaceholder.style.display = "";
        previewPanel.classList.remove("visible");
      }
    });

    previewVideo.addEventListener("loadedmetadata", function () {
      previewState.duration = previewVideo.duration || 0;
      updateTimeDisplay();
    });

    previewVideo.addEventListener("timeupdate", function () {
      previewState.currentTime = previewVideo.currentTime;
      updateTimeDisplay();
    });

    previewVideo.addEventListener("ended", function () {
      previewState.isPlaying = false;
      playPauseBtn.textContent = "Play";
    });

    playPauseBtn.addEventListener("click", function () {
      if (!previewVideo.src || !previewState.duration) return;
      if (previewState.isPlaying) {
        previewVideo.pause();
        previewState.isPlaying = false;
        playPauseBtn.textContent = "Play";
      } else {
        previewVideo.play();
        previewState.isPlaying = true;
        playPauseBtn.textContent = "Pause";
      }
    });
    // --- End Video Preview Panel ---

    // --- Advanced Playback Timeline ---
    const tlContainer = document.getElementById("tlContainer");
    const tlFill = document.getElementById("tlFill");
    const tlPlayhead = document.getElementById("tlPlayhead");
    const tlHoverLine = document.getElementById("tlHoverLine");
    const tlPreview = document.getElementById("tlPreview");
    const tlCanvas = document.getElementById("tlCanvas");
    const tlPreviewTime = document.getElementById("tlPreviewTime");
    const tlCtx = tlCanvas.getContext("2d");
    const tlState = { dragging: false, hoverActive: false };

    let thumbVideo = null;
    let thumbBusy = false;
    const THUMB_MAX = 120;

    function sizeCanvasToVideo() {
      const vw = previewVideo.videoWidth || 16;
      const vh = previewVideo.videoHeight || 9;
      const ratio = vw / vh;
      let cw, ch;
      if (ratio >= 1) { cw = THUMB_MAX; ch = Math.round(THUMB_MAX / ratio); }
      else { ch = THUMB_MAX; cw = Math.round(THUMB_MAX * ratio); }
      tlCanvas.width = cw;
      tlCanvas.height = ch;
      tlCanvas.style.width = cw + "px";
      tlCanvas.style.height = ch + "px";
    }

    previewVideo.addEventListener("loadedmetadata", sizeCanvasToVideo);

    function ensureThumbVideo() {
      if (thumbVideo) return;
      if (!previewVideo.src) return;
      thumbVideo = document.createElement("video");
      thumbVideo.src = previewVideo.src;
      thumbVideo.preload = "auto";
      thumbVideo.muted = true;
      thumbVideo.playsInline = true;
    }

    function drawThumbAtTime(timeSec) {
      if (!previewVideo.src || !previewState.duration) return;
      ensureThumbVideo();
      if (!thumbVideo || thumbBusy) return;
      thumbBusy = true;
      thumbVideo.currentTime = Math.max(0, Math.min(timeSec, previewState.duration));
      thumbVideo.onseeked = function () {
        tlCtx.drawImage(thumbVideo, 0, 0, tlCanvas.width, tlCanvas.height);
        thumbBusy = false;
      };
    }

    function tlPctFromEvent(e) {
      const rect = tlContainer.getBoundingClientRect();
      return Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    }

    function tlUpdatePositions() {
      if (!previewState.duration) return;
      const pct = (previewState.currentTime / previewState.duration) * 100;
      tlFill.style.width = pct + "%";
      tlPlayhead.style.left = pct + "%";
    }

    previewVideo.addEventListener("timeupdate", tlUpdatePositions);
    document.getElementById("media_file").addEventListener("change", function () {
      if (thumbVideo) { thumbVideo.src = ""; thumbVideo = null; }
      tlFill.style.width = "0%";
      tlPlayhead.style.left = "0%";
    });

    function tlShowPreview(e, pct) {
      const timeSec = pct * previewState.duration;
      tlPreviewTime.textContent = fmtTime(timeSec);
      const rect = tlContainer.getBoundingClientRect();
      const px = pct * rect.width;
      const half = (tlCanvas.offsetWidth + 8) / 2 || 40;
      const clamped = Math.max(half, Math.min(rect.width - half, px));
      tlPreview.style.left = clamped + "px";
      tlPreview.classList.add("show");
      tlHoverLine.style.left = px + "px";
      tlHoverLine.style.display = "block";
      drawThumbAtTime(timeSec);
    }

    function tlHidePreview() {
      tlPreview.classList.remove("show");
      tlHoverLine.style.display = "none";
    }

    tlContainer.addEventListener("mousemove", function (e) {
      if (!previewState.duration) return;
      const pct = tlPctFromEvent(e);
      tlShowPreview(e, pct);
      tlState.hoverActive = true;
    });

    tlContainer.addEventListener("mouseleave", function () {
      if (!tlState.dragging) tlHidePreview();
      tlState.hoverActive = false;
    });

    tlContainer.addEventListener("mousedown", function (e) {
      if (!previewState.duration) return;
      e.preventDefault();
      tlState.dragging = true;
      tlPlayhead.classList.add("dragging");
      const pct = tlPctFromEvent(e);
      previewVideo.currentTime = pct * previewState.duration;
      previewState.currentTime = previewVideo.currentTime;
      updateTimeDisplay();
      tlUpdatePositions();
      tlShowPreview(e, pct);
    });

    document.addEventListener("mousemove", function (e) {
      if (!tlState.dragging) return;
      const pct = tlPctFromEvent(e);
      previewVideo.currentTime = pct * previewState.duration;
      previewState.currentTime = previewVideo.currentTime;
      updateTimeDisplay();
      tlUpdatePositions();
      tlShowPreview(e, pct);
    });

    document.addEventListener("mouseup", function () {
      if (!tlState.dragging) return;
      tlState.dragging = false;
      tlPlayhead.classList.remove("dragging");
      if (!tlState.hoverActive) tlHidePreview();
    });
    // --- End Advanced Playback Timeline ---

    // --- Caption Editor ---
    const autoCutBtn = document.getElementById("autoCutBtn");
    const autoCutCard = document.getElementById("autoCutCard");
    const autoCutVideo = document.getElementById("autoCutVideo");
    const autoCutInfo = document.getElementById("autoCutInfo");
    const autoCutDownload = document.getElementById("autoCutDownload");
    const captionEditorCard = document.getElementById("captionEditorCard");
    const editorVideo = document.getElementById("editorVideo");
    const editorCaptionOverlay = document.getElementById("editorCaptionOverlay");
    const editorPlayBtn = document.getElementById("editorPlayBtn");
    const renderEditorBtn = document.getElementById("renderEditorBtn");
    const editorTimeDisplay = document.getElementById("editorTimeDisplay");
    const editorRuler = document.getElementById("editorRuler");
    const editorTimeline = document.getElementById("editorTimeline");
    const editorTrack = document.getElementById("editorTrack");
    const editorTrackFill = document.getElementById("editorTrackFill");
    const editorTrackPlayhead = document.getElementById("editorTrackPlayhead");
    const editorTrackHover = document.getElementById("editorTrackHover");
    const editorMiniPreview = document.getElementById("editorMiniPreview");
    const editorMiniCanvas = document.getElementById("editorMiniCanvas");
    const editorMiniTime = document.getElementById("editorMiniTime");
    const cueText = document.getElementById("cueText");
    const cueStartInput = document.getElementById("cueStartInput");
    const cueEndInput = document.getElementById("cueEndInput");
    const cueDurationInput = document.getElementById("cueDurationInput");
    const captionHeightInput = document.getElementById("captionHeightInput");
    const prevCueBtn = document.getElementById("prevCueBtn");
    const nextCueBtn = document.getElementById("nextCueBtn");
    const cueMeta = document.getElementById("cueMeta");
    const editorStatus = document.getElementById("editorStatus");

    const editorMiniCtx = editorMiniCanvas.getContext("2d");
    const MIN_EDITOR_CUE_MS = 300;
    let detectedCutRegions = [];
    let autoCutObjectUrl = null;
    let editorSessionId = null;
    let editorDuration = 0;
    let editorCues = [];
    let selectedCueId = null;
    let captionTrackSettings = { vertical_position_pct: 78 };
    let editorThumbVideo = null;
    let editorThumbBusy = false;
    const editorPlayState = { isPlaying: false, currentTime: 0, duration: 0 };
    const dragState = {
      mode: null,
      cueId: null,
      startX: 0,
      initialStartMs: 0,
      initialEndMs: 0,
      hoverActive: false,
    };

    function setEditorStatus(message, ok) {
      editorStatus.textContent = message || "";
      editorStatus.className = "editor-status" + (ok === true ? " ok" : ok === false ? " err" : "");
    }

    function clearRenderedOutput() {
      if (autoCutObjectUrl) { URL.revokeObjectURL(autoCutObjectUrl); autoCutObjectUrl = null; }
      autoCutVideo.removeAttribute("src");
      autoCutInfo.innerHTML = "";
      autoCutDownload.href = "#";
      autoCutCard.classList.remove("visible");
    }

    function resetEditorSession() {
      editorSessionId = null;
      editorDuration = 0;
      editorCues = [];
      selectedCueId = null;
      editorPlayState.isPlaying = false;
      editorPlayState.currentTime = 0;
      editorPlayState.duration = 0;
      dragState.mode = null;
      dragState.cueId = null;
      if (editorThumbVideo) {
        editorThumbVideo.src = "";
        editorThumbVideo = null;
      }
      editorThumbBusy = false;
      editorVideo.pause();
      editorVideo.removeAttribute("src");
      editorCaptionOverlay.textContent = "";
      editorCaptionOverlay.classList.add("hidden");
      editorTrack.innerHTML =
        '<div id="editorTrackFill" class="editor-track-fill"></div>' +
        '<div id="editorTrackPlayhead" class="editor-track-playhead"></div>' +
        '<div id="editorTrackHover" class="editor-track-hover"></div>';
      captionEditorCard.classList.remove("visible");
      cueText.value = "";
      cueStartInput.value = "";
      cueEndInput.value = "";
      cueDurationInput.value = "";
      captionHeightInput.value = "78";
      cueMeta.textContent = "No cue selected";
      editorTimeDisplay.textContent = "0:00 / 0:00";
      editorRuler.innerHTML = "";
      setEditorStatus("", undefined);
    }

    function clearCutRegions() {
      detectedCutRegions = [];
      autoCutBtn.disabled = true;
      tlContainer.querySelectorAll(".tl-cut-region").forEach(function (el) { el.remove(); });
      resetEditorSession();
      clearRenderedOutput();
    }

    document.getElementById("media_file").addEventListener("change", clearCutRegions);

    function renderCutRegions(regions) {
      tlContainer.querySelectorAll(".tl-cut-region").forEach(function (el) { el.remove(); });
      if (!previewState.duration || !regions.length) return;
      regions.forEach(function (r) {
        const left = (r.start_s / previewState.duration) * 100;
        const width = ((r.end_s - r.start_s) / previewState.duration) * 100;
        const div = document.createElement("div");
        div.className = "tl-cut-region";
        div.style.left = left + "%";
        div.style.width = width + "%";
        tlContainer.appendChild(div);
      });
    }

    function sortEditorCues() {
      editorCues.sort(function (a, b) {
        if (a.start_ms !== b.start_ms) return a.start_ms - b.start_ms;
        if (a.end_ms !== b.end_ms) return a.end_ms - b.end_ms;
        return String(a.id).localeCompare(String(b.id));
      });
    }

    function findCueIndexById(cueId) {
      return editorCues.findIndex(function (cue) { return cue.id === cueId; });
    }

    function getSelectedCue() {
      const index = findCueIndexById(selectedCueId);
      return index >= 0 ? editorCues[index] : null;
    }

    function clampCueBounds(cue) {
      cue.start_ms = Math.max(0, Math.round(cue.start_ms));
      cue.end_ms = Math.max(cue.start_ms + MIN_EDITOR_CUE_MS, Math.round(cue.end_ms));
      if (editorDuration > 0) {
        const maxMs = Math.round(editorDuration * 1000);
        if (cue.end_ms > maxMs) {
          cue.end_ms = maxMs;
          cue.start_ms = Math.max(0, cue.end_ms - MIN_EDITOR_CUE_MS);
        }
      }
    }

    function updateEditorTimeDisplay() {
      editorTimeDisplay.textContent = fmtTime(editorPlayState.currentTime) + " / " + fmtTime(editorPlayState.duration);
    }

    function updateEditorPlaybackUI() {
      const duration = Math.max(editorPlayState.duration, 0.001);
      const pct = Math.max(0, Math.min(100, (editorPlayState.currentTime / duration) * 100));
      const fillEl = document.getElementById("editorTrackFill");
      const playheadEl = document.getElementById("editorTrackPlayhead");
      if (fillEl) fillEl.style.width = pct + "%";
      if (playheadEl) playheadEl.style.left = pct + "%";
      editorPlayBtn.textContent = editorPlayState.isPlaying ? "Pause" : "Play";
      updateEditorTimeDisplay();
      updateCaptionOverlay();
    }

    function updateCaptionOverlay() {
      const current = editorCues.find(function (cue) {
        return editorPlayState.currentTime * 1000 >= cue.start_ms && editorPlayState.currentTime * 1000 <= cue.end_ms;
      });
      const topPct = Number(captionTrackSettings.vertical_position_pct || 78);
      editorCaptionOverlay.style.top = topPct + "%";
      if (!current || !String(current.text || "").trim()) {
        editorCaptionOverlay.textContent = "";
        editorCaptionOverlay.classList.add("hidden");
        return;
      }
      editorCaptionOverlay.textContent = current.text;
      editorCaptionOverlay.classList.remove("hidden");
    }

    function selectCue(cueId) {
      selectedCueId = cueId;
      renderEditorTimeline();
      syncCueInspector();
      updateCaptionOverlay();
    }

    function syncCueInspector() {
      const cue = getSelectedCue();
      const index = findCueIndexById(selectedCueId);
      const hasCue = Boolean(cue);
      cueText.disabled = !hasCue;
      cueStartInput.disabled = !hasCue;
      cueEndInput.disabled = !hasCue;
      cueDurationInput.disabled = !hasCue;
      prevCueBtn.disabled = !hasCue || index <= 0;
      nextCueBtn.disabled = !hasCue || index < 0 || index >= editorCues.length - 1;
      captionHeightInput.value = String(Math.round(Number(captionTrackSettings.vertical_position_pct || 78)));
      if (!cue) {
        cueText.value = "";
        cueStartInput.value = "";
        cueEndInput.value = "";
        cueDurationInput.value = "";
        cueMeta.textContent = "No cue selected";
        return;
      }
      cueText.value = cue.text || "";
      cueStartInput.value = (cue.start_ms / 1000).toFixed(1);
      cueEndInput.value = (cue.end_ms / 1000).toFixed(1);
      cueDurationInput.value = ((cue.end_ms - cue.start_ms) / 1000).toFixed(1);
      cueMeta.textContent = "Cue " + (index + 1) + " of " + editorCues.length;
    }

    function renderEditorRuler() {
      editorRuler.innerHTML = "";
      const totalSeconds = Math.max(1, Math.ceil(editorDuration));
      for (let second = 0; second <= totalSeconds; second += 1) {
        const tick = document.createElement("div");
        tick.className = "editor-ruler-tick";
        tick.style.left = (second / totalSeconds) * 100 + "%";
        const label = document.createElement("span");
        label.textContent = fmtTime(second);
        tick.appendChild(label);
        editorRuler.appendChild(tick);
      }
    }

    function renderEditorTimeline() {
      const fillMarkup =
        '<div id="editorTrackFill" class="editor-track-fill"></div>' +
        '<div id="editorTrackPlayhead" class="editor-track-playhead"></div>' +
        '<div id="editorTrackHover" class="editor-track-hover"></div>';
      editorTrack.innerHTML = fillMarkup;
      if (!editorDuration || !editorCues.length) {
        updateEditorPlaybackUI();
        return;
      }

      sortEditorCues();
      editorCues.forEach(function (cue) {
        const block = document.createElement("div");
        const leftPct = (cue.start_ms / (editorDuration * 1000)) * 100;
        const widthPct = ((cue.end_ms - cue.start_ms) / (editorDuration * 1000)) * 100;
        block.className = "caption-block" + (cue.id === selectedCueId ? " selected" : "");
        block.style.left = leftPct + "%";
        block.style.width = Math.max(widthPct, 2) + "%";
        block.dataset.cueId = cue.id;
        block.title = cue.text || "";
        block.textContent = cue.text || "";

        const startHandle = document.createElement("span");
        startHandle.className = "caption-handle start";
        startHandle.dataset.role = "start";
        const endHandle = document.createElement("span");
        endHandle.className = "caption-handle end";
        endHandle.dataset.role = "end";
        block.appendChild(startHandle);
        block.appendChild(endHandle);

        block.addEventListener("click", function (event) {
          event.stopPropagation();
          selectCue(cue.id);
        });
        block.addEventListener("dblclick", function (event) {
          event.stopPropagation();
          editorVideo.currentTime = cue.start_ms / 1000;
          editorPlayState.currentTime = editorVideo.currentTime;
          updateEditorPlaybackUI();
        });
        block.addEventListener("mousedown", function (event) {
          event.preventDefault();
          event.stopPropagation();
          const role = event.target && event.target.dataset ? event.target.dataset.role : "";
          const selectedMode = role === "start" || role === "end" ? role : "move";
          selectCue(cue.id);
          dragState.mode = selectedMode;
          dragState.cueId = cue.id;
          dragState.startX = event.clientX;
          dragState.initialStartMs = cue.start_ms;
          dragState.initialEndMs = cue.end_ms;
          block.classList.add("dragging");
        });

        editorTrack.appendChild(block);
      });

      updateEditorPlaybackUI();
    }

    function applyCueInputs() {
      const cue = getSelectedCue();
      if (!cue) return;
      cue.text = cueText.value;
      const startMs = Math.round(Number(cueStartInput.value || 0) * 1000);
      const endMs = Math.round(Number(cueEndInput.value || 0) * 1000);
      const durationMs = Math.round(Number(cueDurationInput.value || 0) * 1000);
      if (document.activeElement === cueDurationInput && Number.isFinite(durationMs) && durationMs >= MIN_EDITOR_CUE_MS) {
        cue.end_ms = cue.start_ms + durationMs;
      } else {
        if (Number.isFinite(startMs)) cue.start_ms = startMs;
        if (Number.isFinite(endMs)) cue.end_ms = endMs;
      }
      clampCueBounds(cue);
      renderEditorTimeline();
      syncCueInspector();
      updateCaptionOverlay();
    }

    function ensureEditorThumbVideo() {
      if (editorThumbVideo) return;
      if (!editorVideo.src) return;
      editorThumbVideo = document.createElement("video");
      editorThumbVideo.src = editorVideo.src;
      editorThumbVideo.preload = "auto";
      editorThumbVideo.muted = true;
      editorThumbVideo.playsInline = true;
    }

    function sizeEditorPreviewCanvas() {
      const vw = editorVideo.videoWidth || 16;
      const vh = editorVideo.videoHeight || 9;
      const ratio = vw / vh;
      let cw;
      let ch;
      if (ratio >= 1) {
        cw = THUMB_MAX;
        ch = Math.round(THUMB_MAX / ratio);
      } else {
        ch = THUMB_MAX;
        cw = Math.round(THUMB_MAX * ratio);
      }
      editorMiniCanvas.width = cw;
      editorMiniCanvas.height = ch;
      editorMiniCanvas.style.width = cw + "px";
      editorMiniCanvas.style.height = ch + "px";
    }

    function drawEditorThumbAtTime(timeSec) {
      if (!editorVideo.src || !editorPlayState.duration) return;
      ensureEditorThumbVideo();
      if (!editorThumbVideo || editorThumbBusy) return;
      editorThumbBusy = true;
      editorThumbVideo.currentTime = Math.max(0, Math.min(timeSec, editorPlayState.duration));
      editorThumbVideo.onseeked = function () {
        editorMiniCtx.drawImage(editorThumbVideo, 0, 0, editorMiniCanvas.width, editorMiniCanvas.height);
        editorThumbBusy = false;
      };
    }

    function editorPctFromClientX(clientX) {
      const rect = editorTimeline.getBoundingClientRect();
      if (!rect.width) return 0;
      return Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    }

    function showEditorMiniPreview(pct) {
      const rect = editorTimeline.getBoundingClientRect();
      const px = pct * rect.width;
      const timeSec = pct * editorPlayState.duration;
      editorMiniTime.textContent = fmtTime(timeSec);
      const half = (editorMiniCanvas.offsetWidth + 8) / 2 || 40;
      const clamped = Math.max(half, Math.min(rect.width - half, px));
      editorMiniPreview.style.left = clamped + "px";
      editorMiniPreview.classList.add("show");
      const hoverEl = document.getElementById("editorTrackHover");
      if (hoverEl) {
        hoverEl.style.left = px + "px";
        hoverEl.style.display = "block";
      }
      drawEditorThumbAtTime(timeSec);
    }

    function hideEditorMiniPreview() {
      editorMiniPreview.classList.remove("show");
      const hoverEl = document.getElementById("editorTrackHover");
      if (hoverEl) hoverEl.style.display = "none";
    }

    function openEditorSession(payload) {
      editorSessionId = payload.session_id;
      editorDuration = Number(payload.duration_seconds || 0);
      editorCues = Array.isArray(payload.cues) ? payload.cues.slice() : [];
      captionTrackSettings = payload.caption_track || { vertical_position_pct: 78 };
      selectedCueId = editorCues.length ? editorCues[0].id : null;
      editorPlayState.isPlaying = false;
      editorPlayState.currentTime = 0;
      editorPlayState.duration = editorDuration;
      editorVideo.pause();
      editorVideo.src = payload.preview_video_url || "";
      editorVideo.load();
      sizeEditorPreviewCanvas();
      renderEditorRuler();
      renderEditorTimeline();
      syncCueInspector();
      updateCaptionOverlay();
      captionEditorCard.classList.add("visible");
      setEditorStatus("Caption editor ready. Drag blocks or edit values below.", true);
    }

    async function runSilenceDetection() {
      const file = document.getElementById("media_file").files[0];
      if (!file) return;
      try {
        const fd = new FormData();
        fd.append("media_file", file);
        fd.append("min_silence_duration", "0.4");
        fd.append("silence_threshold_db", "-30");
        const resp = await fetch("/v1/detect-silence", { method: "POST", body: fd });
        const data = await resp.json();
        if (resp.ok && data.regions && data.regions.length) {
          detectedCutRegions = data.regions;
          renderCutRegions(detectedCutRegions);
          autoCutBtn.disabled = false;
        }
      } catch (err) {
        // silence detection is best-effort; don't block the UI
      }
    }

    autoCutBtn.addEventListener("click", async function () {
      const file = document.getElementById("media_file").files[0];
      if (!file || !detectedCutRegions.length) return;
      autoCutBtn.disabled = true;
      autoCutBtn.textContent = "Opening...";
      try {
        const fd = new FormData();
        fd.append("media_file", file);
        fd.append("cut_regions", JSON.stringify(detectedCutRegions));
        const jobId = jobInput.value.trim();
        if (jobId) fd.append("job_id", jobId);
        const resp = await fetch("/v1/auto-cut/editor-session", { method: "POST", body: fd });
        const payload = await readJsonOrText(resp);
        if (!resp.ok) {
          const message = extractErrorMessage(payload, "Failed to open caption editor");
          showTranscript("Caption editor error: " + message);
          return;
        }
        openEditorSession(payload);
      } catch (err) {
        showTranscript("Caption editor error: " + (err.message || "Network request failed"));
      } finally {
        autoCutBtn.textContent = "Open Caption Editor";
        autoCutBtn.disabled = !detectedCutRegions.length;
      }
    });

    editorVideo.addEventListener("loadedmetadata", function () {
      editorPlayState.duration = editorVideo.duration || editorDuration || 0;
      editorDuration = editorPlayState.duration;
      sizeEditorPreviewCanvas();
      updateEditorPlaybackUI();
    });

    editorVideo.addEventListener("timeupdate", function () {
      editorPlayState.currentTime = editorVideo.currentTime || 0;
      updateEditorPlaybackUI();
    });

    editorVideo.addEventListener("ended", function () {
      editorPlayState.isPlaying = false;
      updateEditorPlaybackUI();
    });

    editorPlayBtn.addEventListener("click", function () {
      if (!editorVideo.src || !editorPlayState.duration) return;
      if (editorPlayState.isPlaying) {
        editorVideo.pause();
        editorPlayState.isPlaying = false;
      } else {
        editorVideo.play();
        editorPlayState.isPlaying = true;
      }
      updateEditorPlaybackUI();
    });

    editorTimeline.addEventListener("mousemove", function (event) {
      if (!editorPlayState.duration || dragState.mode) return;
      const pct = editorPctFromClientX(event.clientX);
      showEditorMiniPreview(pct);
      dragState.hoverActive = true;
    });

    editorTimeline.addEventListener("mouseleave", function () {
      dragState.hoverActive = false;
      if (!dragState.mode) hideEditorMiniPreview();
    });

    editorTimeline.addEventListener("mousedown", function (event) {
      if (!editorPlayState.duration) return;
      if (event.target !== editorTimeline && event.target !== editorTrack) return;
      event.preventDefault();
      const pct = editorPctFromClientX(event.clientX);
      editorVideo.currentTime = pct * editorPlayState.duration;
      editorPlayState.currentTime = editorVideo.currentTime;
      updateEditorPlaybackUI();
      showEditorMiniPreview(pct);
    });

    document.addEventListener("mousemove", function (event) {
      if (!dragState.mode) return;
      const cue = editorCues.find(function (item) { return item.id === dragState.cueId; });
      if (!cue || !editorDuration) return;
      const timelineWidth = editorTimeline.getBoundingClientRect().width || 1;
      const deltaPct = (event.clientX - dragState.startX) / timelineWidth;
      const deltaMs = Math.round((deltaPct * editorDuration * 1000) / 100) * 100;
      if (dragState.mode === "move") {
        const durationMs = dragState.initialEndMs - dragState.initialStartMs;
        cue.start_ms = dragState.initialStartMs + deltaMs;
        cue.end_ms = cue.start_ms + durationMs;
      } else if (dragState.mode === "start") {
        cue.start_ms = dragState.initialStartMs + deltaMs;
      } else if (dragState.mode === "end") {
        cue.end_ms = dragState.initialEndMs + deltaMs;
      }
      clampCueBounds(cue);
      renderEditorTimeline();
      syncCueInspector();
      updateCaptionOverlay();
    });

    document.addEventListener("mouseup", function () {
      if (!dragState.mode) return;
      dragState.mode = null;
      dragState.cueId = null;
      document.querySelectorAll(".caption-block.dragging").forEach(function (node) {
        node.classList.remove("dragging");
      });
      if (!dragState.hoverActive) hideEditorMiniPreview();
    });

    cueText.addEventListener("input", function () {
      const cue = getSelectedCue();
      if (!cue) return;
      cue.text = cueText.value;
      renderEditorTimeline();
      updateCaptionOverlay();
    });

    cueStartInput.addEventListener("input", applyCueInputs);
    cueEndInput.addEventListener("input", applyCueInputs);
    cueDurationInput.addEventListener("input", applyCueInputs);

    captionHeightInput.addEventListener("input", function () {
      captionTrackSettings.vertical_position_pct = Number(captionHeightInput.value || 78);
      updateCaptionOverlay();
    });

    prevCueBtn.addEventListener("click", function () {
      const index = findCueIndexById(selectedCueId);
      if (index > 0) selectCue(editorCues[index - 1].id);
    });

    nextCueBtn.addEventListener("click", function () {
      const index = findCueIndexById(selectedCueId);
      if (index >= 0 && index < editorCues.length - 1) selectCue(editorCues[index + 1].id);
    });

    renderEditorBtn.addEventListener("click", async function () {
      if (!editorSessionId || !editorCues.length) return;
      renderEditorBtn.disabled = true;
      setEditorStatus("Rendering final video...", undefined);
      try {
        const response = await fetch(`/v1/auto-cut/editor-session/${encodeURIComponent(editorSessionId)}/render`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            cues: editorCues.map(function (cue) {
              return {
                id: cue.id,
                start_ms: cue.start_ms,
                end_ms: cue.end_ms,
                text: cue.text,
              };
            }),
            caption_track: {
              vertical_position_pct: Number(captionTrackSettings.vertical_position_pct || 78),
            },
          }),
        });
        if (!response.ok) {
          const payload = await readJsonOrText(response);
          throw new Error(extractErrorMessage(payload, "Render failed"));
        }

        const blob = await response.blob();
        if (autoCutObjectUrl) URL.revokeObjectURL(autoCutObjectUrl);
        autoCutObjectUrl = URL.createObjectURL(blob);
        autoCutVideo.src = autoCutObjectUrl;
        autoCutVideo.load();
        autoCutDownload.href = autoCutObjectUrl;

        const totalCut = detectedCutRegions.reduce(function (sum, region) {
          return sum + (region.end_s - region.start_s);
        }, 0);
        autoCutInfo.innerHTML =
          '<span>Cuts: <span class="cut-count">' + detectedCutRegions.length + " regions</span></span>" +
          '<span>Time saved: <span class="saved-time">' + fmtTime(totalCut) + "</span></span>";
        autoCutCard.classList.add("visible");
        setEditorStatus("Rendered video ready below.", true);
      } catch (err) {
        setEditorStatus(err.message || "Render failed", false);
      } finally {
        renderEditorBtn.disabled = false;
      }
    });
    // --- End Caption Editor ---

    function showTranscript(value) {
      out.textContent = String(value ?? "").trim() || "{}";
    }

    async function readJsonOrText(response) {
      const contentType = response.headers.get("content-type") || "";
      if (contentType.includes("application/json")) {
        return await response.json();
      }
      return await response.text();
    }

    function extractTranscript(payload) {
      if (!payload || typeof payload !== "object") return "";
      const segments = payload.transcript && Array.isArray(payload.transcript.segments)
        ? payload.transcript.segments
        : [];
      return segments
        .map((segment) => String(segment && segment.text ? segment.text : "").trim())
        .filter(Boolean)
        .join(" ")
        .replace(/\s+/g, " ")
        .trim();
    }

    function extractErrorMessage(payload, fallback) {
      if (!payload || typeof payload !== "object") return fallback;
      const detail = payload.detail;
      if (typeof detail === "string" && detail.trim()) return detail.trim();
      if (detail && typeof detail === "object") {
        if (typeof detail.message === "string" && detail.message.trim()) return detail.message.trim();
        if (typeof detail.code === "string" && detail.code.trim()) return detail.code.trim();
      }
      if (typeof payload === "string" && payload.trim()) return payload.trim();
      return fallback;
    }

    async function fetchTranscript(jobId) {
      const response = await fetch(`/v1/analysis-jobs/${encodeURIComponent(jobId)}/result`);
      const payload = await readJsonOrText(response);
      if (!response.ok) {
        return { ok: false, text: "", error: extractErrorMessage(payload, "Failed to fetch result") };
      }
      if (typeof payload === "string") {
        const text = payload.trim();
        return text
          ? { ok: true, text, error: "" }
          : { ok: false, text: "", error: "No transcript returned" };
      }
      const text = extractTranscript(payload);
      return text
        ? { ok: true, text, error: "" }
        : { ok: false, text: "", error: "No transcript returned" };
    }

    async function waitForTranscript(jobId) {
      for (let attempt = 0; attempt < 30; attempt += 1) {
        const statusResponse = await fetch(`/v1/analysis-jobs/${encodeURIComponent(jobId)}`);
        if (statusResponse.ok) {
          const statusPayload = await statusResponse.json();
          if (statusPayload.status === "succeeded") {
            return await fetchTranscript(jobId);
          }
          if (statusPayload.status === "failed") {
            const errorMessage = extractErrorMessage(
              statusPayload,
              "Job failed before transcript was produced"
            );
            return { ok: false, text: "", error: errorMessage };
          }
        }
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
      return { ok: false, text: "", error: "Timed out waiting for transcript" };
    }

    async function getTranscriptForJob(data) {
      if (data.status === "succeeded") {
        return await fetchTranscript(data.job_id);
      }
      if (data.status === "failed") {
        const msg = data.error_message || "Job failed before transcript was produced";
        return { ok: false, text: "", error: msg };
      }
      return await waitForTranscript(data.job_id);
    }

    document.getElementById("createForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      const media = document.getElementById("media_file").files[0];
      if (!media) {
        showTranscript("Please choose a file first.");
        return;
      }
      try {
        const payload = new FormData();
        payload.append("media_file", media);
        const hint = document.getElementById("input_language_hint").value.trim();
        if (hint) payload.append("input_language_hint", hint);
        payload.append("include_raw_transcript", String(document.getElementById("include_raw_transcript").checked));
        payload.append("include_timestamps", String(document.getElementById("include_timestamps").checked));

        showTranscript("Processing... this may take a minute.");
        const response = await fetch("/v1/analysis-jobs", { method: "POST", body: payload });
        const data = await readJsonOrText(response);
        if (response.ok && data && data.job_id) {
          jobInput.value = data.job_id;
          const result = await getTranscriptForJob(data);
          showTranscript(result.ok ? result.text : `Error: ${result.error}`);
          if (result.ok) runSilenceDetection();
        } else {
          const message = extractErrorMessage(data, "Failed to submit job");
          showTranscript(`Error: ${message}`);
        }
      } catch (err) {
        showTranscript(`Error: ${err.message || "Network request failed"}`);
      }
    });

    document.getElementById("statusBtn").addEventListener("click", async () => {
      const jobId = jobInput.value.trim();
      if (!jobId) return showTranscript("Enter a job id first.");
      try {
        showTranscript("Checking status...");
        const result = await waitForTranscript(jobId);
        showTranscript(result.ok ? result.text : `Error: ${result.error}`);
      } catch (err) {
        showTranscript(`Error: ${err.message || "Network request failed"}`);
      }
    });

    document.getElementById("resultBtn").addEventListener("click", async () => {
      const jobId = jobInput.value.trim();
      if (!jobId) return showTranscript("Enter a job id first.");
      try {
        showTranscript("Loading result...");
        const result = await fetchTranscript(jobId);
        showTranscript(result.ok ? result.text : `Error: ${result.error}`);
      } catch (err) {
        showTranscript(`Error: ${err.message || "Network request failed"}`);
      }
    });
  </script>
</body>
</html>"""


@router.post("/v1/analysis-jobs", response_model=AnalysisJobAccepted, status_code=202)
async def create_analysis_job(
    request: Request,
    media_file: UploadFile = File(...),
    style_mode: str = Form(default="preset"),
    style_value: str = Form(default="clear"),
    input_language_hint: str | None = Form(default=None),
    include_raw_transcript: bool = Form(default=True),
    include_timestamps: bool = Form(default=True),
) -> AnalysisJobAccepted:
    service = _service_from_request(request)
    return service.create_job(
        upload_file=media_file,
        style_mode=style_mode,
        style_value=style_value,
        input_language_hint=input_language_hint,
        include_raw_transcript=include_raw_transcript,
        include_timestamps=include_timestamps,
    )


@router.get("/v1/analysis-jobs/{job_id}", response_model=AnalysisJobStatus)
def get_analysis_job_status(request: Request, job_id: str) -> AnalysisJobStatus:
    service = _service_from_request(request)
    return service.get_status(job_id)


@router.get("/v1/analysis-jobs/{job_id}/result", response_model=AnalysisJobResult)
def get_analysis_job_result(request: Request, job_id: str) -> AnalysisJobResult:
    service = _service_from_request(request)
    return service.get_result(job_id)


_media_proc = FfmpegMediaProcessor()


@router.post("/v1/detect-silence")
async def detect_silence(
    media_file: UploadFile = File(...),
    silence_threshold_db: float = Form(default=-30),
    min_silence_duration: float = Form(default=0.4),
) -> JSONResponse:
    suffix = Path(media_file.filename or "upload").suffix or ".mp4"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(await media_file.read())
        tmp.close()
        regions = _media_proc.detect_silence(
            Path(tmp.name),
            threshold_db=silence_threshold_db,
            min_duration=min_silence_duration,
        )
        return JSONResponse({"regions": regions})
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    finally:
        Path(tmp.name).unlink(missing_ok=True)


@router.post("/v1/auto-cut")
async def auto_cut(
    request: Request,
    media_file: UploadFile = File(...),
    cut_regions: str = Form(...),
    job_id: str | None = Form(default=None),
    captions_enabled: bool = Form(default=True),
):
    suffix = Path(media_file.filename or "upload").suffix or ".mp4"
    content_type = media_file.content_type or ""
    if captions_enabled and not content_type.startswith("video/"):
        return JSONResponse(
            {"error": "Captioned final video is only supported for video uploads"},
            status_code=400,
        )

    input_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    output_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    output_tmp.close()
    subtitle_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".ass")
    subtitle_tmp.close()
    captioned_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    captioned_tmp.close()
    try:
        input_tmp.write(await media_file.read())
        input_tmp.close()

        regions = json.loads(cut_regions)
        duration = _media_proc._probe_duration(Path(input_tmp.name))

        cuts = sorted(regions, key=lambda r: r["start_s"])
        keep_ranges: list[tuple[float, float]] = []
        cursor = 0.0
        for cut in cuts:
            start, end = cut["start_s"], cut["end_s"]
            if start > cursor:
                keep_ranges.append((cursor, start))
            cursor = max(cursor, end)
        if cursor < duration:
            keep_ranges.append((cursor, duration))

        if not keep_ranges:
            return JSONResponse({"error": "Nothing left after cuts"}, status_code=400)

        _media_proc.trim_keep_ranges(
            Path(input_tmp.name), Path(output_tmp.name), keep_ranges
        )

        final_output_path = Path(output_tmp.name)
        if captions_enabled:
            service = _service_from_request(request)
            render_options = _caption_options_for_video(
                _media_proc,
                Path(output_tmp.name),
                font_path=service._settings.caption_font_path,
                font_name=service._settings.caption_font_name,
            )
            cues = []
            if job_id:
                try:
                    result = service.get_result(job_id)
                    cues = shape_caption_cues(
                        remap_cues_after_cuts(
                            segments_to_raw_cues(result.transcript.segments),
                            cuts,
                        ),
                        render_options,
                    )
                except Exception:
                    cues = []

            if not cues:
                try:
                    transcription = _transcription_provider_from_request(request).transcribe(
                        Path(output_tmp.name),
                        None,
                    )
                except (TranscriptionProviderError, RuntimeError) as exc:
                    raise RuntimeError(f"Caption transcription failed: {exc}") from exc
                cues = segments_to_caption_cues(transcription.segments, render_options)

            if not cues:
                raise RuntimeError("No usable caption cues were produced")
            _media_proc.write_ass_subtitles(cues, Path(subtitle_tmp.name), render_options)
            _media_proc.burn_subtitles_into_video(
                Path(output_tmp.name),
                Path(subtitle_tmp.name),
                Path(captioned_tmp.name),
                render_options,
            )
            final_output_path = Path(captioned_tmp.name)

        def _cleanup() -> None:
            Path(output_tmp.name).unlink(missing_ok=True)
            Path(subtitle_tmp.name).unlink(missing_ok=True)
            Path(captioned_tmp.name).unlink(missing_ok=True)

        return FileResponse(
            str(final_output_path),
            media_type="video/mp4",
            filename="autocut.mp4",
            background=BackgroundTask(_cleanup),
        )
    except (RuntimeError, json.JSONDecodeError, KeyError) as exc:
        Path(output_tmp.name).unlink(missing_ok=True)
        Path(subtitle_tmp.name).unlink(missing_ok=True)
        Path(captioned_tmp.name).unlink(missing_ok=True)
        return JSONResponse({"error": str(exc)}, status_code=400)
    finally:
        Path(input_tmp.name).unlink(missing_ok=True)


@router.post("/v1/auto-cut/editor-session", response_model=AutoCutEditorSessionResponse)
async def create_auto_cut_editor_session(
    request: Request,
    media_file: UploadFile = File(...),
    cut_regions: str = Form(...),
    job_id: str | None = Form(default=None),
):
    content_type = media_file.content_type or ""
    if not content_type.startswith("video/"):
        return JSONResponse({"error": "Caption editor requires a video upload"}, status_code=400)

    suffix = Path(media_file.filename or "upload").suffix or ".mp4"
    input_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    preview_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    preview_tmp.close()
    try:
        input_tmp.write(await media_file.read())
        input_tmp.close()

        cuts = _parse_cut_regions(cut_regions)
        duration = _media_proc._probe_duration(Path(input_tmp.name))
        keep_ranges = _build_keep_ranges(cuts, duration)
        if not keep_ranges:
            return JSONResponse({"error": "Nothing left after cuts"}, status_code=400)

        _media_proc.trim_keep_ranges(Path(input_tmp.name), Path(preview_tmp.name), keep_ranges)

        container = _container_from_request(request)
        render_options = _caption_options_for_video(
            _media_proc,
            Path(preview_tmp.name),
            font_path=container.settings.caption_font_path,
            font_name=container.settings.caption_font_name,
        )
        editable_cues = _build_editor_cues(request, Path(preview_tmp.name), cuts, job_id)
        if not editable_cues:
            raise RuntimeError("No usable caption cues were produced")

        session_id = uuid4().hex
        preview_key = _editor_session_preview_key(session_id)
        manifest_key = _editor_session_manifest_key(session_id)
        caption_track = _caption_track_from_options(render_options)
        manifest = {
            "preview_video_key": preview_key,
            "duration_seconds": round(float(_media_proc._probe_duration(Path(preview_tmp.name))), 3),
            "play_res_x": render_options.play_res_x,
            "play_res_y": render_options.play_res_y,
            "font_name": render_options.font_name,
            "font_path": render_options.font_path,
            "font_size": render_options.font_size,
            "primary_color": render_options.primary_color,
            "outline_color": render_options.outline_color,
            "outline_width": render_options.outline_width,
            "angle": render_options.angle,
            "alignment": render_options.alignment,
            "margin_left": render_options.margin_left,
            "margin_right": render_options.margin_right,
            "max_chars_per_line": render_options.max_chars_per_line,
            "max_lines": render_options.max_lines,
            "soft_wrap_threshold": render_options.soft_wrap_threshold,
            "soft_wrap_increment_limit": render_options.soft_wrap_increment_limit,
            "default_vertical_position_pct": caption_track.vertical_position_pct,
        }
        container.storage.put_file(preview_key, Path(preview_tmp.name))
        container.storage.put_bytes(manifest_key, json.dumps(manifest).encode("utf-8"))

        return AutoCutEditorSessionResponse(
            session_id=session_id,
            preview_video_url=f"/v1/auto-cut/editor-session/{session_id}/preview",
            duration_seconds=manifest["duration_seconds"],
            cut_regions=cuts,
            cues=editable_cues,
            caption_track=caption_track,
        )
    except (RuntimeError, json.JSONDecodeError, ValueError, KeyError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    finally:
        Path(input_tmp.name).unlink(missing_ok=True)
        Path(preview_tmp.name).unlink(missing_ok=True)


@router.get("/v1/auto-cut/editor-session/{session_id}/preview")
def get_auto_cut_editor_preview(request: Request, session_id: str):
    container = _container_from_request(request)
    try:
        payload = container.storage.get_bytes(_editor_session_preview_key(session_id))
    except FileNotFoundError:
        return JSONResponse({"error": "Editor session not found"}, status_code=404)
    except Exception:
        return JSONResponse({"error": "Editor preview is unavailable"}, status_code=404)
    return Response(content=payload, media_type="video/mp4")


@router.post("/v1/auto-cut/editor-session/{session_id}/render")
async def render_auto_cut_editor_session(
    request: Request,
    session_id: str,
    body: RenderEditedCaptionsRequest,
):
    container = _container_from_request(request)
    preview_key = _editor_session_preview_key(session_id)
    manifest_key = _editor_session_manifest_key(session_id)
    try:
        manifest = json.loads(container.storage.get_bytes(manifest_key).decode("utf-8"))
        preview_bytes = container.storage.get_bytes(preview_key)
    except FileNotFoundError:
        return JSONResponse({"error": "Editor session not found"}, status_code=404)
    except Exception:
        return JSONResponse({"error": "Editor session not found"}, status_code=404)

    track_settings = CaptionTrackSettings(
        vertical_position_pct=_clamp_vertical_position_pct(body.caption_track.vertical_position_pct)
    )
    cues = normalize_edited_cues(body.cues)
    if not cues:
        return JSONResponse({"error": "At least one valid caption cue is required"}, status_code=400)

    preview_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    subtitle_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".ass")
    subtitle_tmp.close()
    output_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    output_tmp.close()
    try:
        preview_tmp.write(preview_bytes)
        preview_tmp.close()

        render_options = _render_options_from_manifest(manifest, track_settings)
        _media_proc.write_ass_subtitles(cues, Path(subtitle_tmp.name), render_options)
        _media_proc.burn_subtitles_into_video(
            Path(preview_tmp.name),
            Path(subtitle_tmp.name),
            Path(output_tmp.name),
            render_options,
        )

        def _cleanup() -> None:
            Path(preview_tmp.name).unlink(missing_ok=True)
            Path(subtitle_tmp.name).unlink(missing_ok=True)
            Path(output_tmp.name).unlink(missing_ok=True)
            _delete_storage_key(container.storage, preview_key)
            _delete_storage_key(container.storage, manifest_key)

        return FileResponse(
            output_tmp.name,
            media_type="video/mp4",
            filename="autocut.mp4",
            background=BackgroundTask(_cleanup),
        )
    except RuntimeError as exc:
        Path(preview_tmp.name).unlink(missing_ok=True)
        Path(subtitle_tmp.name).unlink(missing_ok=True)
        Path(output_tmp.name).unlink(missing_ok=True)
        return JSONResponse({"error": str(exc)}, status_code=400)
