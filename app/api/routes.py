from __future__ import annotations

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse

from app.container import get_container
from app.schemas import AnalysisJobAccepted, AnalysisJobResult, AnalysisJobStatus

router = APIRouter()


def _service_from_request(request: Request):
    container = getattr(request.app.state, "container", None) or get_container()
    return container.create_analysis_service()


@router.get("/healthz")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


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
    .preview-wrap {
      position: relative;
      width: 100%;
      aspect-ratio: 16 / 9;
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
  </style>
</head>
<body>
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

  <div class="card">
    <h3>Response</h3>
    <div id="previewPanel">
      <div class="preview-wrap">
        <video id="previewVideo" class="preview-video" preload="metadata"></video>
        <div id="previewPlaceholder" class="preview-placeholder">No video loaded</div>
      </div>
      <div class="preview-controls">
        <button id="playPauseBtn" type="button">Play</button>
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
      const cw = 160, ch = 90;
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
