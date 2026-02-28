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
    <pre id="out">{}</pre>
  </div>

  <script>
    const out = document.getElementById("out");
    const jobInput = document.getElementById("job_id");

    function show(value) {
      out.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
    }

    async function readJsonOrText(response) {
      const contentType = response.headers.get("content-type") || "";
      if (contentType.includes("application/json")) {
        return await response.json();
      }
      return await response.text();
    }

    document.getElementById("createForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const media = document.getElementById("media_file").files[0];
      if (!media) {
        show("Please choose a file first.");
        return;
      }

      const payload = new FormData();
      payload.append("media_file", media);
      const hint = document.getElementById("input_language_hint").value.trim();
      if (hint) payload.append("input_language_hint", hint);
      payload.append("include_raw_transcript", String(document.getElementById("include_raw_transcript").checked));
      payload.append("include_timestamps", String(document.getElementById("include_timestamps").checked));

      show("Submitting...");
      const response = await fetch("/v1/analysis-jobs", { method: "POST", body: payload });
      const data = await readJsonOrText(response);
      show(data);
      if (response.ok && data && data.job_id) {
        jobInput.value = data.job_id;
      }
    });

    document.getElementById("statusBtn").addEventListener("click", async () => {
      const jobId = jobInput.value.trim();
      if (!jobId) return show("Enter a job_id first.");
      show("Loading status...");
      const response = await fetch(`/v1/analysis-jobs/${encodeURIComponent(jobId)}`);
      show(await readJsonOrText(response));
    });

    document.getElementById("resultBtn").addEventListener("click", async () => {
      const jobId = jobInput.value.trim();
      if (!jobId) return show("Enter a job_id first.");
      show("Loading result...");
      const response = await fetch(`/v1/analysis-jobs/${encodeURIComponent(jobId)}/result`);
      show(await readJsonOrText(response));
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
