"""Reel Generator API routes and UI."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, Body, File, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.background import BackgroundTask

from app.container import get_settings
from app.media import FfmpegMediaProcessor
from app.providers import ElevenLabsVoiceCloningProvider, MistralReelScriptProvider, VoiceCloningProviderError
from app.providers import LLMProviderError

router = APIRouter()

_REEL_UI_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AI Reel Generator</title>
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
      max-width: 720px;
      margin: 0 auto;
      padding: 24px 16px 36px;
      background: radial-gradient(circle at top right, #172442 0%, var(--bg) 40%);
      color: var(--text);
    }
    nav { margin-bottom: 20px; }
    nav a { color: var(--muted); text-decoration: none; }
    nav a:hover { color: var(--brand); }
    h1 { margin: 0 0 8px; font-size: 24px; }
    h3 { margin: 0 0 10px; color: #dce7ff; font-size: 16px; }
    .card {
      border: 1px solid var(--border);
      background: linear-gradient(180deg, var(--panel) 0%, #11192b 100%);
      border-radius: 12px;
      padding: 14px;
      margin: 14px 0;
    }
    label { display: block; font-size: 13px; margin-bottom: 6px; color: #c9d8f8; }
    textarea {
      width: 100%;
      min-height: 80px;
      padding: 10px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel-strong);
      color: var(--text);
      resize: vertical;
    }
    input[type="file"] { padding: 6px 0; color: var(--muted); }
    button {
      padding: 8px 14px;
      border: 1px solid var(--brand);
      border-radius: 8px;
      background: var(--brand);
      color: white;
      cursor: pointer;
      font-weight: 600;
      margin-right: 8px;
      margin-top: 6px;
    }
    button:hover { background: var(--brand-hover); }
    button:disabled { opacity: 0.5; cursor: not-allowed; }
    .ghost { background: transparent; color: #ccdbff; border-color: #5371b7; }
    .ghost:hover { background: rgba(79, 124, 255, 0.12); }
    .script-section { margin: 10px 0; }
    .script-section label { font-weight: 600; }
    .script-section [contenteditable] {
      min-height: 24px;
      padding: 8px;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: var(--panel-strong);
    }
    .status { font-size: 13px; color: var(--muted); margin-top: 6px; }
    .status.ok { color: var(--ok); }
    .status.err { color: #ff6b6b; }
    .step { margin-bottom: 24px; }
    select {
      padding: 8px 10px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel-strong);
      color: var(--text);
      min-width: 200px;
    }
    audio, video { width: 100%; max-width: 100%; border-radius: 8px; margin-top: 8px; }
  </style>
</head>
<body>
  <nav><a href="/">← Transcript & Auto-Cut</a> | <a href="/reel-generator">Reel Generator</a></nav>
  <h1>AI Reel Generator</h1>
  <p class="status">Create viral Instagram Reels with AI-generated scripts and your cloned voice.</p>

  <div class="step">
    <div class="card">
      <h3>Step 1: Voice Setup</h3>
      <label>Upload 1–3 voice samples (MP3/WAV, 1+ min total recommended)</label>
      <input type="file" id="voiceFiles" accept="audio/*" multiple />
      <br />
      <label>Voice name</label>
      <input type="text" id="voiceName" placeholder="My Voice" value="My Voice" />
      <br />
      <button id="cloneVoiceBtn" type="button">Clone My Voice</button>
      <span id="voiceStatus" class="status"></span>
      <br />
      <label>Or select existing voice</label>
      <select id="voiceSelect">
        <option value="">-- Load voices --</option>
      </select>
      <button id="loadVoicesBtn" type="button" class="ghost">Refresh</button>
    </div>
  </div>

  <div class="step">
    <div class="card">
      <h3>Step 2: Reel Input</h3>
      <label>Rough idea / topic</label>
      <textarea id="roughIdea" placeholder="e.g. 5 productivity hacks that changed my life"></textarea>
      <label>B-roll clips (5–6 videos, in order)</label>
      <input type="file" id="brollFiles" accept="video/*" multiple />
      <br />
      <button id="generateScriptBtn" type="button">Generate Script</button>
      <span id="scriptStatus" class="status"></span>
    </div>
  </div>

  <div class="step" id="scriptStep" style="display:none">
    <div class="card">
      <h3>Step 3: Script Review</h3>
      <div class="script-section">
        <label>Hook</label>
        <div id="scriptHook" contenteditable="true"></div>
      </div>
      <div class="script-section">
        <label>Body</label>
        <div id="scriptBody" contenteditable="true"></div>
      </div>
      <div class="script-section">
        <label>CTA</label>
        <div id="scriptCta" contenteditable="true"></div>
      </div>
      <div class="script-section">
        <label>Hashtags</label>
        <div id="scriptHashtags" contenteditable="true"></div>
      </div>
      <button id="regenerateScriptBtn" type="button" class="ghost">Regenerate</button>
      <button id="generateVoiceoverBtn" type="button">Generate Voiceover</button>
      <span id="voiceoverStatus" class="status"></span>
      <br />
      <audio id="voiceoverAudio" controls style="margin-top:10px"></audio>
    </div>
  </div>

  <div class="step" id="assembleStep" style="display:none">
    <div class="card">
      <h3>Step 4: Assemble Reel</h3>
      <button id="assembleBtn" type="button">Assemble Reel</button>
      <span id="assembleStatus" class="status"></span>
      <br />
      <video id="finalReel" controls style="margin-top:10px"></video>
      <br />
      <a id="downloadReel" href="#" download="reel.mp4" style="color:var(--brand)">Download</a>
    </div>
  </div>

  <script>
    const voiceFiles = document.getElementById("voiceFiles");
    const voiceName = document.getElementById("voiceName");
    const cloneVoiceBtn = document.getElementById("cloneVoiceBtn");
    const voiceStatus = document.getElementById("voiceStatus");
    const voiceSelect = document.getElementById("voiceSelect");
    const loadVoicesBtn = document.getElementById("loadVoicesBtn");
    const roughIdea = document.getElementById("roughIdea");
    const brollFiles = document.getElementById("brollFiles");
    const generateScriptBtn = document.getElementById("generateScriptBtn");
    const scriptStatus = document.getElementById("scriptStatus");
    const scriptStep = document.getElementById("scriptStep");
    const scriptHook = document.getElementById("scriptHook");
    const scriptBody = document.getElementById("scriptBody");
    const scriptCta = document.getElementById("scriptCta");
    const scriptHashtags = document.getElementById("scriptHashtags");
    const regenerateScriptBtn = document.getElementById("regenerateScriptBtn");
    const generateVoiceoverBtn = document.getElementById("generateVoiceoverBtn");
    const voiceoverStatus = document.getElementById("voiceoverStatus");
    const voiceoverAudio = document.getElementById("voiceoverAudio");
    const assembleStep = document.getElementById("assembleStep");
    const assembleBtn = document.getElementById("assembleBtn");
    const assembleStatus = document.getElementById("assembleStatus");
    const finalReel = document.getElementById("finalReel");
    const downloadReel = document.getElementById("downloadReel");

    let currentVoiceId = null;
    let currentScript = null;
    let voiceoverBlob = null;

    function setStatus(el, msg, ok) {
      el.textContent = msg || "";
      el.className = "status" + (ok === true ? " ok" : ok === false ? " err" : "");
    }

    async function loadVoices() {
      try {
        setStatus(voiceStatus, "Loading...");
        const r = await fetch("/v1/reel/voices");
        const data = await r.json();
        voiceSelect.innerHTML = '<option value="">-- Select voice --</option>';
        (data.voices || []).forEach(v => {
          const opt = document.createElement("option");
          opt.value = v.voice_id;
          opt.textContent = v.name || v.voice_id;
          voiceSelect.appendChild(opt);
        });
        setStatus(voiceStatus, "Loaded " + (data.voices?.length || 0) + " voices", true);
      } catch (e) {
        setStatus(voiceStatus, "Error: " + e.message, false);
      }
    }

    loadVoicesBtn.addEventListener("click", loadVoices);

    voiceSelect.addEventListener("change", () => {
      currentVoiceId = voiceSelect.value || null;
      if (currentVoiceId) setStatus(voiceStatus, "Voice selected", true);
    });

    cloneVoiceBtn.addEventListener("click", async () => {
      const files = voiceFiles.files;
      if (!files?.length) {
        setStatus(voiceStatus, "Select at least one audio file", false);
        return;
      }
      try {
        cloneVoiceBtn.disabled = true;
        setStatus(voiceStatus, "Cloning...");
        const fd = new FormData();
        fd.append("name", voiceName.value || "My Voice");
        for (let i = 0; i < files.length; i++) fd.append("files", files[i]);
        const r = await fetch("/v1/reel/clone-voice", { method: "POST", body: fd });
        const data = await r.json();
        if (data.error) throw new Error(data.error);
        currentVoiceId = data.voice_id;
        setStatus(voiceStatus, "Voice cloned: " + currentVoiceId, true);
        await loadVoices();
        voiceSelect.value = currentVoiceId;
      } catch (e) {
        setStatus(voiceStatus, "Error: " + e.message, false);
      } finally {
        cloneVoiceBtn.disabled = false;
      }
    });

    generateScriptBtn.addEventListener("click", async () => {
      const idea = roughIdea.value?.trim();
      const files = brollFiles.files;
      if (!idea) {
        setStatus(scriptStatus, "Enter a rough idea", false);
        return;
      }
      const clipCount = files?.length ? Math.min(files.length, 6) : 5;
      try {
        generateScriptBtn.disabled = true;
        setStatus(scriptStatus, "Generating...");
        const r = await fetch("/v1/reel/generate-script", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ rough_idea: idea, clip_count: clipCount }),
        });
        const data = await r.json();
        if (data.error) throw new Error(data.error);
        currentScript = data;
        scriptHook.textContent = data.hook || "";
        scriptBody.textContent = (data.body || []).join("\\n\\n");
        scriptCta.textContent = data.cta || "";
        scriptHashtags.textContent = (data.hashtags || []).join(" ");
        scriptStep.style.display = "block";
        setStatus(scriptStatus, "Script ready", true);
      } catch (e) {
        setStatus(scriptStatus, "Error: " + e.message, false);
      } finally {
        generateScriptBtn.disabled = false;
      }
    });

    regenerateScriptBtn.addEventListener("click", () => generateScriptBtn.click());

    function getFullNarration() {
      const hook = scriptHook.textContent?.trim() || "";
      const body = (scriptBody.textContent || "").split(/\\n+/).filter(Boolean).join(" ");
      const cta = scriptCta.textContent?.trim() || "";
      return (hook + " " + body + " " + cta).trim() || (currentScript?.full_narration || "");
    }

    generateVoiceoverBtn.addEventListener("click", async () => {
      if (!currentVoiceId) {
        setStatus(voiceoverStatus, "Select or clone a voice first", false);
        return;
      }
      const text = getFullNarration();
      if (!text) {
        setStatus(voiceoverStatus, "Generate a script first", false);
        return;
      }
      try {
        generateVoiceoverBtn.disabled = true;
        setStatus(voiceoverStatus, "Generating voiceover...");
        const r = await fetch("/v1/reel/generate-voiceover", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ voice_id: currentVoiceId, text }),
        });
        if (!r.ok) {
          const d = await r.json().catch(() => ({}));
          throw new Error(d.error || r.statusText);
        }
        voiceoverBlob = await r.blob();
        voiceoverAudio.src = URL.createObjectURL(voiceoverBlob);
        assembleStep.style.display = "block";
        setStatus(voiceoverStatus, "Voiceover ready", true);
      } catch (e) {
        setStatus(voiceoverStatus, "Error: " + e.message, false);
      } finally {
        generateVoiceoverBtn.disabled = false;
      }
    });

    assembleBtn.addEventListener("click", async () => {
      const files = brollFiles.files;
      if (!files?.length) {
        setStatus(assembleStatus, "Upload B-roll clips", false);
        return;
      }
      if (!voiceoverBlob) {
        setStatus(assembleStatus, "Generate voiceover first", false);
        return;
      }
      try {
        assembleBtn.disabled = true;
        setStatus(assembleStatus, "Assembling...");
        const fd = new FormData();
        for (let i = 0; i < files.length; i++) fd.append("clips", files[i]);
        fd.append("voiceover", voiceoverBlob, "voiceover.mp3");
        const r = await fetch("/v1/reel/assemble", { method: "POST", body: fd });
        if (!r.ok) {
          const d = await r.json().catch(() => ({}));
          throw new Error(d.error || r.statusText);
        }
        const blob = await r.blob();
        finalReel.src = URL.createObjectURL(blob);
        downloadReel.href = finalReel.src;
        downloadReel.download = "reel.mp4";
        setStatus(assembleStatus, "Reel ready", true);
      } catch (e) {
        setStatus(assembleStatus, "Error: " + e.message, false);
      } finally {
        assembleBtn.disabled = false;
      }
    });
  </script>
</body>
</html>
"""


@router.get("/reel-generator", response_class=HTMLResponse)
def reel_generator_ui() -> str:
    """Serve the Reel Generator UI page."""
    return _REEL_UI_HTML


@router.post("/v1/reel/generate-script")
async def generate_script(body: dict = Body(...)) -> JSONResponse:
    """Generate a viral reel script from rough idea using Mistral."""
    settings = get_settings()
    if not settings.mistral_api_key:
        return JSONResponse({"error": "Mistral API key not configured"}, status_code=503)
    rough_idea = body.get("rough_idea", "").strip()
    clip_count = int(body.get("clip_count", 5))
    if not rough_idea:
        return JSONResponse({"error": "rough_idea is required"}, status_code=400)
    try:
        provider = MistralReelScriptProvider(settings)
        script = provider.generate_reel_script(rough_idea, clip_count)
        return JSONResponse(script.model_dump())
    except LLMProviderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/v1/reel/clone-voice")
async def clone_voice(
    name: str = Form(...),
    audio_files: list[UploadFile] = File(..., alias="files"),
) -> JSONResponse:
    """Create an ElevenLabs voice clone from uploaded audio samples."""
    settings = get_settings()
    if not settings.elevenlabs_api_key:
        return JSONResponse({"error": "ElevenLabs API key not configured"}, status_code=503)
    if not audio_files:
        return JSONResponse({"error": "At least one audio file is required"}, status_code=400)
    audio_tuples: list[tuple[str, bytes]] = []
    for f in audio_files:
        content = await f.read()
        fn = f.filename or "audio.mp3"
        audio_tuples.append((fn, content))
    try:
        provider = ElevenLabsVoiceCloningProvider(settings)
        voice_id = provider.clone_voice(name, audio_tuples)
        return JSONResponse({"voice_id": voice_id})
    except VoiceCloningProviderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.get("/v1/reel/voices")
async def list_voices() -> JSONResponse:
    """List ElevenLabs voices (including cloned)."""
    settings = get_settings()
    if not settings.elevenlabs_api_key:
        return JSONResponse({"error": "ElevenLabs API key not configured"}, status_code=503)
    try:
        provider = ElevenLabsVoiceCloningProvider(settings)
        voices = provider.list_voices()
        return JSONResponse({"voices": voices})
    except VoiceCloningProviderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/v1/reel/generate-voiceover", response_model=None)
async def generate_voiceover(body: dict = Body(...)):
    """Generate TTS audio from script using cloned voice."""
    settings = get_settings()
    if not settings.elevenlabs_api_key:
        return JSONResponse({"error": "ElevenLabs API key not configured"}, status_code=503)
    voice_id = body.get("voice_id", "").strip()
    text = body.get("text", "").strip()
    if not voice_id or not text:
        return JSONResponse({"error": "voice_id and text are required"}, status_code=400)
    try:
        provider = ElevenLabsVoiceCloningProvider(settings)
        audio_bytes = provider.text_to_speech(voice_id, text)
        return Response(content=audio_bytes, media_type="audio/mpeg")
    except VoiceCloningProviderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/v1/reel/assemble", response_model=None)
async def assemble_reel(
    clips: list[UploadFile] = File(..., alias="clips"),
    voiceover: UploadFile = File(...),
):
    """Assemble B-roll clips with voiceover into final reel."""
    if not clips:
        return JSONResponse({"error": "At least one clip is required"}, status_code=400)

    media_proc = FfmpegMediaProcessor()
    temp_dir = tempfile.mkdtemp()
    clip_paths: list[Path] = []
    voiceover_path: Path | None = None
    output_path = Path(temp_dir) / "reel.mp4"

    try:
        for i, clip in enumerate(clips):
            suffix = Path(clip.filename or "clip").suffix or ".mp4"
            path = Path(temp_dir) / f"clip_{i}{suffix}"
            path.write_bytes(await clip.read())
            clip_paths.append(path)

        vo_suffix = Path(voiceover.filename or "voiceover").suffix or ".mp3"
        voiceover_path = Path(temp_dir) / f"voiceover{vo_suffix}"
        voiceover_path.write_bytes(await voiceover.read())

        trimmed_dir = Path(temp_dir) / "trimmed"
        trimmed_dir.mkdir()
        trimmed_paths: list[Path] = []
        for i, p in enumerate(clip_paths):
            out = trimmed_dir / f"t{i}.mp4"
            media_proc.auto_cut_clip(p, out, target_duration=5.0, max_duration=7.0)
            trimmed_paths.append(out)

        media_proc.concat_clips_with_audio(trimmed_paths, voiceover_path, output_path)

        def cleanup():
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)

        return FileResponse(
            str(output_path),
            media_type="video/mp4",
            filename="reel.mp4",
            background=BackgroundTask(cleanup),
        )
    except Exception as e:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        return JSONResponse({"error": str(e)}, status_code=400)
