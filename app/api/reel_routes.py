"""Reel Generator API routes and UI."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, Body, File, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.background import BackgroundTask

from app.captions import default_caption_render_options, segments_to_caption_cues
from app.container import get_settings
from app.hook_catalog import HookCatalogError, get_hook_catalog_service
from app.media import FfmpegMediaProcessor
from app.providers import (
    ElevenLabsVoiceCloningProvider,
    HttpElevenLabsTranscriptionProvider,
    LLMProviderError,
    MistralReelScriptProvider,
    TranscriptionProviderError,
    VoiceCloningProviderError,
)

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
    .ghost:disabled { background: transparent; }
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
    .hook-grid {
      display: grid;
      gap: 10px;
      margin-top: 14px;
    }
    .hook-card {
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 12px;
      background: rgba(24, 35, 58, 0.7);
    }
    .hook-card.selected {
      border-color: var(--brand);
      box-shadow: 0 0 0 1px rgba(79, 124, 255, 0.35);
    }
    .hook-card p {
      margin: 0 0 8px;
      line-height: 1.45;
    }
    .hook-meta {
      font-size: 12px;
      color: var(--muted);
      margin-bottom: 8px;
    }
    .hook-source {
      color: #bfd0ff;
      font-size: 12px;
      text-decoration: none;
    }
    .hook-source:hover { color: white; }
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
      <h3>Step 2: Idea + Hook Selection</h3>
      <label>Rough idea / topic</label>
      <textarea id="roughIdea" placeholder="e.g. 5 productivity hacks that changed my life"></textarea>
      <label>B-roll clips (5–6 videos, in order)</label>
      <input type="file" id="brollFiles" accept="video/*" multiple />
      <br />
      <button id="suggestHooksBtn" type="button">Suggest Hooks</button>
      <button id="generateScriptBtn" type="button" disabled>Generate Script</button>
      <span id="scriptStatus" class="status"></span>
      <div id="hookSuggestions" class="hook-grid" style="display:none"></div>
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
      <h3>Step 4: Assemble Reel + Captions</h3>
      <button id="assembleBtn" type="button">Assemble Reel + Captions</button>
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
    const suggestHooksBtn = document.getElementById("suggestHooksBtn");
    const generateScriptBtn = document.getElementById("generateScriptBtn");
    const scriptStatus = document.getElementById("scriptStatus");
    const hookSuggestions = document.getElementById("hookSuggestions");
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
    let currentHookSuggestions = [];
    let currentSelectedHookId = null;
    let currentSelectedHookText = null;
    let voiceoverBlob = null;

    function setStatus(el, msg, ok) {
      el.textContent = msg || "";
      el.className = "status" + (ok === true ? " ok" : ok === false ? " err" : "");
    }

    function resetScriptOutput() {
      currentScript = null;
      voiceoverBlob = null;
      scriptHook.textContent = "";
      scriptBody.textContent = "";
      scriptCta.textContent = "";
      scriptHashtags.textContent = "";
      scriptStep.style.display = "none";
      assembleStep.style.display = "none";
      voiceoverAudio.removeAttribute("src");
      finalReel.removeAttribute("src");
      downloadReel.href = "#";
    }

    function renderHookSuggestions() {
      hookSuggestions.innerHTML = "";
      if (!currentHookSuggestions.length) {
        hookSuggestions.style.display = "none";
        return;
      }
      hookSuggestions.style.display = "grid";
      currentHookSuggestions.forEach((item) => {
        const card = document.createElement("div");
        card.className = "hook-card" + (item.id === currentSelectedHookId ? " selected" : "");

        const hookText = document.createElement("p");
        hookText.textContent = item.hook_text || "";
        card.appendChild(hookText);

        const meta = document.createElement("div");
        meta.className = "hook-meta";
        meta.textContent = ((item.section ? item.section + " · " : "") + (item.reason || "")).trim();
        card.appendChild(meta);

        if (item.source_url) {
          const source = document.createElement("a");
          source.className = "hook-source";
          source.href = item.source_url;
          source.target = "_blank";
          source.rel = "noreferrer";
          source.textContent = "View source";
          card.appendChild(source);
        }

        const chooseBtn = document.createElement("button");
        chooseBtn.type = "button";
        chooseBtn.className = item.id === currentSelectedHookId ? "ghost" : "";
        chooseBtn.textContent = item.id === currentSelectedHookId ? "Selected" : "Choose";
        chooseBtn.addEventListener("click", () => {
          currentSelectedHookId = item.id;
          currentSelectedHookText = item.hook_text || null;
          generateScriptBtn.disabled = false;
          renderHookSuggestions();
          setStatus(scriptStatus, "Hook selected. Generate the script next.", true);
        });
        card.appendChild(document.createElement("br"));
        card.appendChild(chooseBtn);

        hookSuggestions.appendChild(card);
      });
    }

    function clearHookSelection() {
      currentHookSuggestions = [];
      currentSelectedHookId = null;
      currentSelectedHookText = null;
      generateScriptBtn.disabled = true;
      renderHookSuggestions();
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

    roughIdea.addEventListener("input", () => {
      clearHookSelection();
      resetScriptOutput();
      setStatus(scriptStatus, "");
    });

    suggestHooksBtn.addEventListener("click", async () => {
      const idea = roughIdea.value?.trim();
      if (!idea) {
        setStatus(scriptStatus, "Enter a rough idea", false);
        return;
      }
      try {
        suggestHooksBtn.disabled = true;
        generateScriptBtn.disabled = true;
        resetScriptOutput();
        setStatus(scriptStatus, "Finding hooks...");
        const r = await fetch("/v1/reel/suggest-hooks", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ rough_idea: idea, limit: 4 }),
        });
        const data = await r.json();
        if (data.error) throw new Error(data.error);
        currentHookSuggestions = data.suggestions || [];
        currentSelectedHookId = null;
        currentSelectedHookText = null;
        renderHookSuggestions();
        if (!currentHookSuggestions.length) {
          throw new Error("No hook suggestions were returned");
        }
        setStatus(scriptStatus, "Choose one of the suggested hooks.", true);
      } catch (e) {
        clearHookSelection();
        setStatus(scriptStatus, "Error: " + e.message, false);
      } finally {
        suggestHooksBtn.disabled = false;
      }
    });

    generateScriptBtn.addEventListener("click", async () => {
      const idea = roughIdea.value?.trim();
      const files = brollFiles.files;
      if (!idea) {
        setStatus(scriptStatus, "Enter a rough idea", false);
        return;
      }
      if (!currentSelectedHookId) {
        setStatus(scriptStatus, "Choose a hook first", false);
        return;
      }
      const clipCount = files?.length ? Math.min(files.length, 6) : 5;
      try {
        generateScriptBtn.disabled = true;
        setStatus(scriptStatus, "Generating...");
        const r = await fetch("/v1/reel/generate-script", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            rough_idea: idea,
            selected_hook_id: currentSelectedHookId,
            clip_count: clipCount
          }),
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
        fd.append("captions_enabled", "true");
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


def _compact_reel_error(exc: Exception) -> str:
    raw_message = str(exc).strip()
    if not raw_message:
        return "Reel assembly failed"

    lines = [line.strip() for line in raw_message.splitlines() if line.strip()]
    preferred_terms = ("error", "invalid", "failed", "unconnected", "required", "no ")
    for line in reversed(lines):
        lower_line = line.lower()
        if any(term in lower_line for term in preferred_terms):
            return f"Reel assembly failed: {line[:220]}"
    return f"Reel assembly failed: {lines[-1][:220]}"


def _reel_caption_transcription_provider(settings):
    api_key = settings.elevenlabs_reel_api_key
    if not api_key:
        raise TranscriptionProviderError("Missing ElevenLabs API key")
    caption_settings = settings.model_copy(update={"elevenlabs_api_key": api_key})
    return HttpElevenLabsTranscriptionProvider(caption_settings)


@router.get("/reel-generator", response_class=HTMLResponse)
def reel_generator_ui() -> str:
    """Serve the Reel Generator UI page."""
    return _REEL_UI_HTML


@router.post("/v1/reel/suggest-hooks")
async def suggest_hooks(body: dict = Body(...)) -> JSONResponse:
    """Suggest the best hook options for a rough idea."""
    settings = get_settings()
    if not settings.mistral_api_key:
        return JSONResponse({"error": "Mistral API key not configured"}, status_code=503)

    rough_idea = body.get("rough_idea", "").strip()
    limit = max(1, min(int(body.get("limit", 4)), 10))
    if not rough_idea:
        return JSONResponse({"error": "rough_idea is required"}, status_code=400)

    try:
        catalog = get_hook_catalog_service(settings.hooks_catalog_path)
        candidates = catalog.shortlist(rough_idea, limit=max(30, limit))
        provider = MistralReelScriptProvider(settings)
        suggestions = provider.suggest_hooks(rough_idea, candidates, limit=limit)
        return JSONResponse({"suggestions": [item.model_dump() for item in suggestions]})
    except HookCatalogError as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)
    except LLMProviderError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.post("/v1/reel/generate-script")
async def generate_script(body: dict = Body(...)) -> JSONResponse:
    """Generate a viral reel script from rough idea using Mistral."""
    settings = get_settings()
    if not settings.mistral_api_key:
        return JSONResponse({"error": "Mistral API key not configured"}, status_code=503)
    rough_idea = body.get("rough_idea", "").strip()
    selected_hook_id = body.get("selected_hook_id", "").strip()
    clip_count = int(body.get("clip_count", 5))
    if not rough_idea:
        return JSONResponse({"error": "rough_idea is required"}, status_code=400)
    if not selected_hook_id:
        return JSONResponse({"error": "selected_hook_id is required"}, status_code=400)
    try:
        catalog = get_hook_catalog_service(settings.hooks_catalog_path)
        selected_hook = catalog.get_hook(selected_hook_id)
        if selected_hook is None:
            return JSONResponse({"error": "selected_hook_id was not found"}, status_code=400)
        provider = MistralReelScriptProvider(settings)
        script = provider.generate_reel_script(rough_idea, selected_hook, clip_count)
        return JSONResponse(script.model_dump())
    except HookCatalogError as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)
    except LLMProviderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/v1/reel/clone-voice")
async def clone_voice(
    name: str = Form(...),
    audio_files: list[UploadFile] = File(..., alias="files"),
) -> JSONResponse:
    """Create an ElevenLabs voice clone from uploaded audio samples."""
    settings = get_settings()
    if not settings.elevenlabs_reel_api_key:
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
    if not settings.elevenlabs_reel_api_key:
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
    if not settings.elevenlabs_reel_api_key:
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
    captions_enabled: bool = Form(default=True),
):
    """Assemble B-roll clips with voiceover into final reel."""
    if not clips:
        return JSONResponse({"error": "At least one clip is required"}, status_code=400)

    settings = get_settings()
    media_proc = FfmpegMediaProcessor()
    temp_dir = tempfile.mkdtemp()
    clip_paths: list[Path] = []
    voiceover_path: Path | None = None
    output_path = Path(temp_dir) / "reel.mp4"
    subtitle_path = Path(temp_dir) / "captions.ass"
    captioned_output_path = Path(temp_dir) / "reel-captioned.mp4"

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
        final_output_path = output_path

        if captions_enabled:
            try:
                transcription = _reel_caption_transcription_provider(settings).transcribe(voiceover_path, None)
            except (TranscriptionProviderError, RuntimeError) as exc:
                raise RuntimeError(f"Caption transcription failed: {exc}") from exc

            cues = segments_to_caption_cues(transcription.segments)
            if not cues:
                raise RuntimeError("No usable caption cues were produced")

            render_options = default_caption_render_options(
                font_path=settings.caption_font_path,
                font_name=settings.caption_font_name,
                font_size=52,
                bottom_margin=130,
                max_chars_per_line=28,
            )
            media_proc.write_ass_subtitles(cues, subtitle_path, render_options)
            media_proc.burn_subtitles_into_video(output_path, subtitle_path, captioned_output_path, render_options)
            final_output_path = captioned_output_path

        def cleanup():
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)

        return FileResponse(
            str(final_output_path),
            media_type="video/mp4",
            filename="reel.mp4",
            background=BackgroundTask(cleanup),
        )
    except Exception as e:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        return JSONResponse({"error": _compact_reel_error(e)}, status_code=400)
