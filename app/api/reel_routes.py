"""Reel Generator API routes and UI."""

from __future__ import annotations

import asyncio
from collections import deque
import json
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Body, File, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.background import BackgroundTask

from app.captions import default_caption_render_options, segments_to_caption_cues, write_ass_subtitles
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
from app.schemas import TimedTextSegment

router = APIRouter()

_MAX_REEL_DOWNLOADS = 8
_REEL_DOWNLOADS: dict[str, tuple[bytes, str, str]] = {}
_REEL_DOWNLOAD_ORDER: deque[str] = deque()


def _store_reel_download(source_path: Path, *, filename: str) -> tuple[str, str]:
    asset_id = uuid4().hex
    _REEL_DOWNLOADS[asset_id] = (source_path.read_bytes(), "video/mp4", filename)
    _REEL_DOWNLOAD_ORDER.append(asset_id)
    while len(_REEL_DOWNLOAD_ORDER) > _MAX_REEL_DOWNLOADS:
        stale_asset_id = _REEL_DOWNLOAD_ORDER.popleft()
        _REEL_DOWNLOADS.pop(stale_asset_id, None)
    return asset_id, f"/v1/reel/downloads/{asset_id}"


def _get_reel_download_payload(asset_id: str) -> tuple[bytes, str, str] | None:
    return _REEL_DOWNLOADS.get(asset_id)

_REEL_UI_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AI Reel Generator</title>
  <style>
    :root {
      --bg: #ffffff;
      --panel: #fcfcfc;
      --text: #000000;
      --muted: #737373;
      --border: #e5e5e5;
      --brand: #000000;
      --brand-hover: #333333;
      --ok: #16a34a;
      --err: #ef4444;
    }
    * { box-sizing: border-box; }
    body {
      font-family: 'Inter', system-ui, -apple-system, sans-serif;
      max-width: 800px;
      margin: 0 auto;
      padding: 0 32px 80px;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
    }
    nav { 
      padding: 32px 0; 
      margin-bottom: 40px;
      display: flex;
      gap: 24px;
    }
    nav a { 
      text-decoration: none; 
      color: var(--muted); 
      font-size: 14px;
      font-weight: 500;
    }
    nav a.active, nav a:hover { color: var(--text); }
    
    h1 { margin: 0 0 8px; font-size: 32px; font-weight: 700; letter-spacing: -0.02em; }
    .status { font-size: 14px; color: var(--muted); margin-bottom: 48px; }
    .status.ok { color: var(--ok); }
    .status.err { color: var(--err); }
    
    h2 { font-size: 20px; font-weight: 600; margin: 56px 0 24px; color: var(--text); padding-bottom: 12px; border-bottom: 1px solid var(--border); }
    h3 { margin: 0 0 8px; font-size: 13px; color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; }
    
    label { display: block; font-size: 14px; font-weight: 500; margin-bottom: 8px; color: var(--text); }
    .input-group { margin-bottom: 24px; position: relative; }
    
    input[type="text"], select, textarea {
      width: 100%;
      padding: 12px 16px;
      border: 1px solid var(--border);
      border-radius: 4px;
      background: #ffffff;
      color: var(--text);
      font-family: inherit;
      font-size: 15px;
    }
    input[type="text"]:focus, select:focus, textarea:focus { border-color: #a3a3a3; outline: none; }
    
    /* Notion block style for textareas */
    textarea.notion-block {
      border: none;
      border-left: 2px solid var(--border);
      border-radius: 0;
      padding: 8px 16px;
      background: transparent;
      font-size: 16px;
      min-height: 120px;
    }
    textarea.notion-block:focus { border-left-color: var(--text); }
    
    .file-dropzone { border: 1px dashed var(--border); border-radius: 4px; padding: 12px; display: flex; align-items: center; background: #ffffff; }
    input[type="file"] { width: 100%; font-size: 14px; color: var(--muted); }
    input[type="file"]::file-selector-button {
      background: #ffffff; border: 1px solid var(--border); color: var(--text);
      padding: 6px 16px; border-radius: 4px; cursor: pointer; margin-right: 16px; font-size: 13px; font-weight: 500;
    }
    input[type="file"]::file-selector-button:hover { background: var(--panel); }
    
    button { display: inline-flex; align-items: center; justify-content: center; padding: 10px 20px; border-radius: 4px; font-size: 14px; font-weight: 500; cursor: pointer; white-space: nowrap; }
    .btn-primary { background: var(--brand); color: #ffffff; border: 1px solid var(--brand); }
    .btn-primary:hover { background: var(--brand-hover); }
    .btn-primary:disabled { opacity: 0.5; }
    
    .btn-ghost { background: #ffffff; color: var(--text); border: 1px solid var(--border); }
    .btn-ghost:hover:not(:disabled) { background: #f5f5f5; border-color: #d4d4d4;}
    .btn-ghost:disabled { opacity: 0.5; }
    
    .dictation-btn {
      position: absolute; right: 16px; bottom: 16px; padding: 6px 12px; font-size: 12px; border-radius: 4px;
      background: #ffffff; border: 1px solid var(--border); color: var(--text);
    }
    .dictation-btn.active { background: #fee2e2; border-color: #ef4444; color: #b91c1c; }
    
    .hook-grid { display: flex; flex-direction: column; gap: 12px; margin-top: 24px; }
    .hook-card { border: 1px solid var(--border); border-radius: 4px; padding: 16px; cursor: pointer; background: #ffffff; }
    .hook-card:hover { border-color: #a3a3a3; }
    .hook-card.selected { border-color: var(--text); box-shadow: 0 0 0 1px var(--text); }
    .hook-card p { margin: 0 0 8px; font-size: 15px; }
    .hook-meta { font-size: 13px; color: var(--muted); margin-bottom: 8px; }
    .hook-source { color: var(--text); font-size: 13px; text-decoration: underline; }
    
    .script-section { margin-bottom: 32px; }
    .script-section [contenteditable] {
      min-height: 24px; padding: 8px 0; border: none; outline: none; font-size: 16px; line-height: 1.6; color: var(--text);
    }
    .script-section [contenteditable]:focus { border-bottom: 1px solid var(--border); }
    .script-section [contenteditable]:empty:before { content: attr(placeholder); color: #a3a3a3; font-style: italic; }
    
    .checkbox-row { display: inline-flex; align-items: center; gap: 12px; cursor: pointer; font-size: 15px; }
    .checkbox-row input[type="checkbox"] { accent-color: var(--brand); width: 18px; height: 18px; }
    
    .asset-preview-shell { width: 100%; max-width: 420px; aspect-ratio: 9 / 16; margin: 32px auto 0; border-radius: 8px; overflow: hidden; background: #000; border: 1px solid var(--border); box-shadow: 0 4px 24px rgba(0,0,0,0.08); }
    .asset-preview-shell video { width: 100%; height: 100%; object-fit: cover; display: block; }
    .asset-preview-controls { display: flex; align-items: center; justify-content: center; gap: 16px; margin-top: 16px; }
    .asset-preview-empty { margin-top: 32px; padding: 24px; border: 1px dashed var(--border); border-radius: 4px; color: var(--muted); text-align: center; font-size: 14px; background: #fafafa; }
    
    .asset-links { display: flex; flex-direction: column; align-items: center; gap: 12px; margin-top: 24px; }
    .download-link { color: var(--text); text-decoration: underline; font-size: 14px; font-weight: 500; }
    
    audio { width: 100%; margin-top: 16px; }
    .hidden { display: none !important; }
    
    #stylePreview { margin-top: 16px; padding: 16px; border-left: 2px solid var(--border); font-size: 14px; color: var(--muted); white-space: pre-wrap; background: #fafafa; }
  </style>
</head>
<body>
  <nav>
    <a href="/">Transcript & Auto-Cut</a>
    <a href="/reel-generator" class="active" style="color:var(--text); font-weight:600;">Reel Generator</a>
  </nav>

  <h1>AI Reel Generator</h1>
  <p class="status">Create viral Instagram Reels with AI-generated scripts and your cloned voice.</p>

  <div id="step1">
    <h2>1. Voice Setup</h2>
    
    <div class="input-group">
      <label>Upload 1–3 voice samples (MP3/WAV, 1+ min total recommended)</label>
      <div class="file-dropzone">
        <input type="file" id="voiceFiles" accept="audio/*" multiple />
      </div>
    </div>
    
    <div style="display: flex; gap: 16px; align-items: flex-end; margin-bottom: 32px;">
      <div style="flex: 1;">
        <label>Voice name</label>
        <input type="text" id="voiceName" placeholder="My Voice" value="My Voice" />
      </div>
      <button id="cloneVoiceBtn" type="button" class="btn-primary">Clone My Voice</button>
    </div>
    
    <div class="input-group">
      <label>Or select existing voice</label>
      <div style="display: flex; gap: 16px;">
        <select id="voiceSelect" style="flex: 1;">
          <option value="">-- Load voices --</option>
        </select>
        <button id="loadVoicesBtn" type="button" class="btn-ghost">Refresh</button>
      </div>
    </div>
    <span id="voiceStatus" class="status" style="display: block; margin-top: -8px;"></span>
  </div>

  <div id="step2">
    <h2>2. Idea & Hook Selection</h2>
    
    <div class="input-group" style="padding-bottom: 24px; border-bottom: 1px solid var(--panel);">
      <label>Example video (optional — style reference)</label>
      <div style="display: flex; gap: 16px; align-items: center;">
        <div class="file-dropzone" style="flex: 1;">
          <input type="file" id="exampleVideoFile" accept="video/*,audio/*" />
        </div>
        <button id="analyzeStyleBtn" type="button" class="btn-ghost" disabled>Analyze Style</button>
      </div>
      <span id="styleStatus" class="status"></span>
      <div id="stylePreview" style="display:none;"></div>
    </div>

    <div class="input-group" style="margin-top: 32px;">
      <label for="roughIdea">Rough idea / topic</label>
      <div style="position: relative;">
        <textarea id="roughIdea" class="notion-block" placeholder="e.g. 5 productivity hacks that changed my life"></textarea>
        <button id="roughIdeaDictationBtn" type="button" class="dictation-btn" aria-pressed="false">Start Dictation</button>
      </div>
      <div id="dictationStatus" class="status" style="margin-top: 8px;"></div>
    </div>
    
    <div class="input-group">
      <label>B-roll clips (5–6 videos, in order)</label>
      <div class="file-dropzone">
        <input type="file" id="brollFiles" accept="video/*" multiple />
      </div>
    </div>
    
    <div style="display: flex; gap: 16px; margin-top: 32px;">
      <button id="suggestHooksBtn" type="button" class="btn-ghost">Suggest Hooks</button>
      <button id="generateScriptBtn" type="button" class="btn-primary" disabled>Generate Script</button>
    </div>
    <span id="scriptStatus" class="status" style="display: block; margin-top: 12px;"></span>
    
    <div id="hookSuggestions" class="hook-grid" style="display:none"></div>
  </div>

  <div id="scriptStep" style="display:none">
    <h2>3. Script Review</h2>
    
    <div class="script-section">
      <h3>Hook</h3>
      <div id="scriptHook" contenteditable="true" placeholder="Your hook goes here..."></div>
    </div>
    <div class="script-section">
      <h3>Body</h3>
      <div id="scriptBody" contenteditable="true" placeholder="Your script body... (separate scenes with line breaks)"></div>
    </div>
    <div class="script-section">
      <h3>Call to Action</h3>
      <div id="scriptCta" contenteditable="true" placeholder="Call to action..."></div>
    </div>
    <div class="script-section">
      <h3>Hashtags</h3>
      <div id="scriptHashtags" contenteditable="true" placeholder="#hashtags"></div>
    </div>
    
    <div style="display: flex; gap: 16px; margin-top: 40px;">
      <button id="regenerateScriptBtn" type="button" class="btn-ghost">Regenerate</button>
      <button id="generateVoiceoverBtn" type="button" class="btn-primary">Generate Voiceover</button>
    </div>
    <span id="voiceoverStatus" class="status" style="display: block; margin-top: 12px;"></span>
    
    <audio id="voiceoverAudio" controls></audio>
  </div>

  <div id="assembleStep" style="display:none">
    <h2>4. Final Assembly</h2>
    
    <div style="display: flex; flex-direction: column; align-items: flex-start; gap: 24px;">
      <label class="checkbox-row" for="includeCaptionedVersion">
        <input id="includeCaptionedVersion" type="checkbox" checked />
        <span>Also prepare a captioned download version</span>
      </label>
      
      <button id="assembleBtn" type="button" class="btn-primary">Prepare Reel Versions</button>
    </div>
    <span id="assembleStatus" class="status" style="display: block; margin-top: 12px;"></span>
    
    <div id="reelPreviewEmpty" class="asset-preview-empty">Preview will appear after you prepare the reel.</div>
    
    <div id="reelPreviewShell" class="asset-preview-shell hidden" aria-hidden="true">
      <video id="finalReel" preload="metadata" playsinline></video>
    </div>
    
    <div id="reelPreviewControls" class="asset-preview-controls hidden">
      <button id="reelPreviewToggleBtn" type="button" class="btn-ghost" disabled>Play Preview</button>
      <span id="reelPreviewTime" class="status" style="margin: 0; font-variant-numeric: tabular-nums;">0:00 / 0:00</span>
    </div>
    
    <div class="asset-links">
      <a id="downloadReel" class="download-link hidden" href="#" download="reel.mp4">Download B-roll Reel</a>
      <a id="downloadCaptionedReel" class="download-link hidden" href="#" download="reel-captioned.mp4">Download Reel With Captions</a>
    </div>
  </div>
  <script>
    const exampleVideoFile = document.getElementById("exampleVideoFile");
    const analyzeStyleBtn = document.getElementById("analyzeStyleBtn");
    const styleStatus = document.getElementById("styleStatus");
    const stylePreview = document.getElementById("stylePreview");
    const voiceFiles = document.getElementById("voiceFiles");
    const voiceName = document.getElementById("voiceName");
    const cloneVoiceBtn = document.getElementById("cloneVoiceBtn");
    const voiceStatus = document.getElementById("voiceStatus");
    const voiceSelect = document.getElementById("voiceSelect");
    const loadVoicesBtn = document.getElementById("loadVoicesBtn");
    const roughIdea = document.getElementById("roughIdea");
    const roughIdeaDictationBtn = document.getElementById("roughIdeaDictationBtn");
    const dictationStatus = document.getElementById("dictationStatus");
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
    const includeCaptionedVersion = document.getElementById("includeCaptionedVersion");
    const assembleStatus = document.getElementById("assembleStatus");
    const reelPreviewEmpty = document.getElementById("reelPreviewEmpty");
    const reelPreviewShell = document.getElementById("reelPreviewShell");
    const reelPreviewControls = document.getElementById("reelPreviewControls");
    const finalReel = document.getElementById("finalReel");
    const reelPreviewToggleBtn = document.getElementById("reelPreviewToggleBtn");
    const reelPreviewTime = document.getElementById("reelPreviewTime");
    const downloadReel = document.getElementById("downloadReel");
    const downloadCaptionedReel = document.getElementById("downloadCaptionedReel");
    const SpeechRecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition;

    let currentStyleNotes = null;
    let currentVoiceId = null;
    let currentScript = null;
    let currentHookSuggestions = [];
    let currentSelectedHookId = null;
    let currentSelectedHookText = null;
    let voiceoverBlob = null;
    let reelObjectUrl = null;
    let captionedReelObjectUrl = null;
    let speechRecognition = null;
    const dictationSupported = Boolean(SpeechRecognitionCtor);
    let dictationListening = false;
    let dictationStopping = false;
    let dictationBaseValue = "";
    let dictationInsertStart = 0;
    let dictationInsertEnd = 0;
    let dictationFinalText = "";
    let dictationInterimText = "";
    let dictationInternalInput = false;
    let dictationStopMessage = "";
    let dictationStopOk = undefined;

    function fmtTime(sec) {
      const total = Math.max(0, Math.floor(sec || 0));
      const minutes = Math.floor(total / 60);
      const seconds = total % 60;
      return minutes + ":" + String(seconds).padStart(2, "0");
    }

    function hasReelPreview() {
      return Boolean(finalReel.getAttribute("src"));
    }

    function syncReelPreviewState() {
      const hasPreview = hasReelPreview();
      reelPreviewEmpty.classList.toggle("hidden", hasPreview);
      reelPreviewShell.classList.toggle("hidden", !hasPreview);
      reelPreviewControls.classList.toggle("hidden", !hasPreview);
      reelPreviewShell.setAttribute("aria-hidden", hasPreview ? "false" : "true");
      reelPreviewToggleBtn.disabled = !hasPreview;
    }

    function updateReelPreviewTime() {
      const currentTime = Number.isFinite(finalReel.currentTime) ? finalReel.currentTime : 0;
      const duration = Number.isFinite(finalReel.duration) ? finalReel.duration : 0;
      reelPreviewTime.textContent = fmtTime(currentTime) + " / " + fmtTime(duration);
      reelPreviewToggleBtn.textContent = finalReel.paused ? "Play Preview" : "Pause Preview";
      reelPreviewToggleBtn.disabled = !hasReelPreview();
    }

    function setStatus(el, msg, ok) {
      el.textContent = msg || "";
      el.className = "status" + (ok === true ? " ok" : ok === false ? " err" : "");
    }

    function clearReelPreview() {
      finalReel.pause();
      finalReel.removeAttribute("src");
      finalReel.load();
      reelObjectUrl = null;
      captionedReelObjectUrl = null;
      downloadReel.href = "#";
      downloadReel.classList.add("hidden");
      downloadCaptionedReel.href = "#";
      downloadCaptionedReel.classList.add("hidden");
      syncReelPreviewState();
      updateReelPreviewTime();
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
      clearReelPreview();
    }

    reelPreviewToggleBtn.addEventListener("click", async () => {
      if (!finalReel.getAttribute("src")) {
        return;
      }
      if (finalReel.paused) {
        try {
          await finalReel.play();
        } catch (_error) {
          // Ignore autoplay/playback errors from the browser.
        }
      } else {
        finalReel.pause();
      }
      updateReelPreviewTime();
    });

    finalReel.addEventListener("loadedmetadata", updateReelPreviewTime);
    finalReel.addEventListener("timeupdate", updateReelPreviewTime);
    finalReel.addEventListener("play", updateReelPreviewTime);
    finalReel.addEventListener("pause", updateReelPreviewTime);
    finalReel.addEventListener("ended", updateReelPreviewTime);
    finalReel.addEventListener("emptied", updateReelPreviewTime);

    syncReelPreviewState();
    updateReelPreviewTime();

    function updateDictationButton() {
      if (!dictationSupported) {
        roughIdeaDictationBtn.disabled = true;
        roughIdeaDictationBtn.classList.remove("active");
        roughIdeaDictationBtn.textContent = "Unavailable";
        roughIdeaDictationBtn.setAttribute("aria-pressed", "false");
        return;
      }

      roughIdeaDictationBtn.disabled = dictationStopping;
      roughIdeaDictationBtn.classList.toggle("active", dictationListening);
      roughIdeaDictationBtn.textContent = dictationStopping
        ? "Stopping..."
        : (dictationListening ? "Stop Dictation" : "Start Dictation");
      roughIdeaDictationBtn.setAttribute("aria-pressed", dictationListening ? "true" : "false");
    }

    function setDictationStatus(msg, ok) {
      setStatus(dictationStatus, msg, ok);
    }

    function appendTranscriptChunk(base, chunk) {
      const normalizedChunk = (chunk || "").trim();
      if (!normalizedChunk) return base;
      return base ? (base + " " + normalizedChunk) : normalizedChunk;
    }

    function buildDictationValue() {
      const prefix = dictationBaseValue.slice(0, dictationInsertStart);
      const suffix = dictationBaseValue.slice(dictationInsertEnd);
      const insertion = [dictationFinalText, dictationInterimText].filter(Boolean).join(" ").trim();
      return prefix + insertion + suffix;
    }

    function applyDictationText(triggerInput) {
      const nextValue = buildDictationValue();
      const changed = roughIdea.value !== nextValue;
      roughIdea.value = nextValue;
      if (triggerInput && changed) {
        dictationInternalInput = true;
        try {
          roughIdea.dispatchEvent(new Event("input", { bubbles: true }));
        } finally {
          dictationInternalInput = false;
        }
      }
    }

    function finalizeDictation(statusMessage, ok) {
      const hadInterimText = Boolean(dictationInterimText);
      dictationInterimText = "";
      applyDictationText(hadInterimText);
      dictationListening = false;
      dictationStopping = false;
      dictationStopMessage = "";
      dictationStopOk = undefined;
      updateDictationButton();
      setDictationStatus(statusMessage || "", ok);
    }

    function stopDictation(statusMessage, ok) {
      if (!speechRecognition || !dictationListening || dictationStopping) {
        return;
      }

      const hadInterimText = Boolean(dictationInterimText);
      dictationInterimText = "";
      applyDictationText(hadInterimText);

      dictationStopping = true;
      dictationStopMessage = statusMessage || "Dictation stopped.";
      dictationStopOk = ok;
      updateDictationButton();
      setDictationStatus("Stopping...", undefined);
      try {
        speechRecognition.stop();
      } catch (error) {
        finalizeDictation(dictationStopMessage, dictationStopOk);
      }
    }

    function describeDictationError(errorCode) {
      if (errorCode === "not-allowed" || errorCode === "service-not-allowed") {
        return "Microphone access was denied.";
      }
      if (errorCode === "audio-capture") {
        return "No microphone was detected.";
      }
      if (errorCode === "network") {
        return "Speech recognition hit a network error.";
      }
      if (errorCode === "aborted") {
        return "Speech dictation was interrupted.";
      }
      return "Speech dictation could not start.";
    }

    function startDictation() {
      if (!dictationSupported || !speechRecognition || dictationListening) {
        return;
      }

      dictationBaseValue = roughIdea.value;
      const fallbackPosition = dictationBaseValue.length;
      dictationInsertStart = typeof roughIdea.selectionStart === "number" ? roughIdea.selectionStart : fallbackPosition;
      dictationInsertEnd = typeof roughIdea.selectionEnd === "number" ? roughIdea.selectionEnd : dictationInsertStart;
      dictationFinalText = "";
      dictationInterimText = "";
      dictationStopping = false;
      dictationStopMessage = "";
      dictationStopOk = undefined;
      dictationListening = true;
      updateDictationButton();
      setDictationStatus("Starting...", undefined);

      try {
        speechRecognition.start();
      } catch (error) {
        finalizeDictation("Speech dictation could not start.", false);
      }
    }

    if (dictationSupported) {
      speechRecognition = new SpeechRecognitionCtor();
      speechRecognition.continuous = true;
      speechRecognition.interimResults = true;
      speechRecognition.lang = "en-US";

      speechRecognition.onstart = () => {
        setDictationStatus("Listening...", true);
      };

      speechRecognition.onresult = (event) => {
        if (!dictationListening) {
          return;
        }

        let nextFinalText = dictationFinalText;
        let nextInterimText = "";
        let finalizedChanged = false;

        for (let i = event.resultIndex; i < event.results.length; i++) {
          const result = event.results[i];
          const transcript = Array.from(result)
            .map((choice) => choice.transcript || "")
            .join(" ")
            .trim();
          if (!transcript) {
            continue;
          }

          if (result.isFinal) {
            nextFinalText = appendTranscriptChunk(nextFinalText, transcript);
            finalizedChanged = true;
          } else {
            nextInterimText = appendTranscriptChunk(nextInterimText, transcript);
          }
        }

        dictationFinalText = nextFinalText;
        dictationInterimText = nextInterimText;
        applyDictationText(finalizedChanged);
      };

      speechRecognition.onerror = (event) => {
        finalizeDictation(describeDictationError(event.error), false);
      };

      speechRecognition.onend = () => {
        if (!dictationListening) {
          return;
        }
        finalizeDictation(dictationStopMessage || "Dictation stopped.", dictationStopOk);
      };
    } else {
      setDictationStatus("Speech dictation is not available in this browser.", undefined);
      updateDictationButton();
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
        chooseBtn.className = item.id === currentSelectedHookId ? "btn-ghost" : "btn-primary";
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
      if (dictationListening && !dictationInternalInput) {
        dictationBaseValue = roughIdea.value;
        dictationInsertStart = roughIdea.value.length;
        dictationInsertEnd = dictationInsertStart;
        dictationFinalText = "";
        dictationInterimText = "";
        stopDictation("Dictation stopped because you edited the idea.", undefined);
      }
      clearHookSelection();
      resetScriptOutput();
      setStatus(scriptStatus, "");
    });

    roughIdeaDictationBtn.addEventListener("click", () => {
      if (!dictationSupported) {
        return;
      }
      if (dictationListening) {
        stopDictation("Dictation stopped.", undefined);
        return;
      }
      startDictation();
    });

    exampleVideoFile.addEventListener("change", () => {
      if (exampleVideoFile.files?.length) {
        analyzeStyleBtn.disabled = false;
      } else {
        analyzeStyleBtn.disabled = true;
        currentStyleNotes = null;
        stylePreview.style.display = "none";
        setStatus(styleStatus, "");
      }
    });

    analyzeStyleBtn.addEventListener("click", async () => {
      const file = exampleVideoFile.files?.[0];
      if (!file) {
        setStatus(styleStatus, "Select an example video first", false);
        return;
      }
      try {
        analyzeStyleBtn.disabled = true;
        setStatus(styleStatus, "Analyzing style...");
        const fd = new FormData();
        fd.append("file", file);
        const r = await fetch("/v1/reel/analyze-example", { method: "POST", body: fd });
        const data = await r.json();
        if (data.error) throw new Error(data.error);
        currentStyleNotes = data.style_notes;
        stylePreview.textContent = data.style_notes;
        stylePreview.style.display = "block";
        setStatus(styleStatus, "Style captured", true);
      } catch (e) {
        currentStyleNotes = null;
        stylePreview.style.display = "none";
        setStatus(styleStatus, "Error: " + e.message, false);
      } finally {
        analyzeStyleBtn.disabled = !exampleVideoFile.files?.length;
      }
    });

    suggestHooksBtn.addEventListener("click", async () => {
      if (dictationListening) {
        stopDictation("Dictation stopped.", undefined);
      }
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
      if (dictationListening) {
        stopDictation("Dictation stopped.", undefined);
      }
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
            clip_count: clipCount,
            style_notes: currentStyleNotes
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
        clearReelPreview();
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
        const shouldPrepareCaptionedVersion = Boolean(includeCaptionedVersion?.checked);
        assembleBtn.disabled = true;
        setStatus(
          assembleStatus,
          shouldPrepareCaptionedVersion ? "Preparing reel versions..." : "Preparing B-roll reel..."
        );
        clearReelPreview();

        async function requestPlainReel() {
          const fd = new FormData();
          for (let i = 0; i < files.length; i++) fd.append("clips", files[i]);
          fd.append("voiceover", voiceoverBlob, "voiceover.mp3");
          fd.append("captions_enabled", "false");
          fd.append("response_mode", "json");
          const response = await fetch("/v1/reel/assemble", { method: "POST", body: fd });
          if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.error || response.statusText);
          }
          return response.json();
        }

        const reelPayload = await requestPlainReel();
        const reelAssetId = reelPayload.asset_id || "";
        reelObjectUrl = reelPayload.download_url || "";
        if (!reelAssetId || !reelObjectUrl) {
          throw new Error("The reel download could not be prepared");
        }
        finalReel.src = reelObjectUrl;
        finalReel.currentTime = 0;
        finalReel.pause();
        syncReelPreviewState();
        updateReelPreviewTime();
        downloadReel.href = reelObjectUrl;
        downloadReel.download = "reel.mp4";
        downloadReel.classList.remove("hidden");

        if (!shouldPrepareCaptionedVersion) {
          setStatus(assembleStatus, "B-roll reel is ready.", true);
          return;
        }

        try {
          const captionedFd = new FormData();
          captionedFd.append("source_asset_id", reelAssetId);
          captionedFd.append("voiceover", voiceoverBlob, "voiceover.mp3");
          captionedFd.append("narration_text", getFullNarration());
          captionedFd.append("response_mode", "json");
          const captionedResponse = await fetch("/v1/reel/caption-video", { method: "POST", body: captionedFd });
          if (!captionedResponse.ok) {
            const data = await captionedResponse.json().catch(() => ({}));
            throw new Error(data.error || captionedResponse.statusText);
          }
          const captionedPayload = await captionedResponse.json();
          captionedReelObjectUrl = captionedPayload.download_url || "";
          if (!captionedReelObjectUrl) {
            throw new Error("The captioned reel download could not be prepared");
          }
          downloadCaptionedReel.href = captionedReelObjectUrl;
          downloadCaptionedReel.download = "reel-captioned.mp4";
          downloadCaptionedReel.classList.remove("hidden");
          setStatus(assembleStatus, "Both reel versions are ready.", true);
        } catch (e) {
          setStatus(assembleStatus, "B-roll reel is ready. Captioned reel failed: " + e.message, false);
        }
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
def reel_generator_ui() -> HTMLResponse:
    """Serve the Reel Generator UI page."""
    return HTMLResponse(
        content=_REEL_UI_HTML,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.get("/v1/reel/downloads/{asset_id}")
def get_reel_download(asset_id: str):
    asset = _get_reel_download_payload(asset_id)
    if asset is None:
        return JSONResponse({"error": "Reel download is unavailable"}, status_code=404)
    payload, media_type, filename = asset
    return Response(
        content=payload,
        media_type=media_type,
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'inline; filename="{filename}"',
        },
    )


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
        suggestions = await asyncio.to_thread(provider.suggest_hooks, rough_idea, candidates, limit)
        return JSONResponse({"suggestions": [item.model_dump() for item in suggestions]})
    except HookCatalogError as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)
    except LLMProviderError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.post("/v1/reel/analyze-example")
async def analyze_example(
    file: UploadFile = File(...),
) -> JSONResponse:
    """Analyze an example video's script style for use in script generation."""
    settings = get_settings()
    if not settings.mistral_api_key:
        return JSONResponse({"error": "Mistral API key not configured"}, status_code=503)

    temp_dir = tempfile.mkdtemp()
    try:
        suffix = Path(file.filename or "video").suffix or ".mp4"
        video_path = Path(temp_dir) / f"example{suffix}"
        video_path.write_bytes(await file.read())

        wav_path = Path(temp_dir) / "example.wav"
        media_proc = FfmpegMediaProcessor()
        await asyncio.to_thread(media_proc.normalize_to_wav, video_path, wav_path)

        stt = _reel_caption_transcription_provider(settings)
        transcription = await asyncio.to_thread(stt.transcribe, wav_path, None)

        full_text = " ".join(seg.text for seg in transcription.segments).strip()
        if not full_text:
            return JSONResponse({"error": "No speech detected in the example video"}, status_code=400)

        provider = MistralReelScriptProvider(settings)
        style_notes = await asyncio.to_thread(provider.analyze_example_style, full_text)

        return JSONResponse({"style_notes": style_notes, "example_transcript": full_text})
    except TranscriptionProviderError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except LLMProviderError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    finally:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)


@router.post("/v1/reel/generate-script")
async def generate_script(body: dict = Body(...)) -> JSONResponse:
    """Generate a viral reel script from rough idea using Mistral."""
    settings = get_settings()
    if not settings.mistral_api_key:
        return JSONResponse({"error": "Mistral API key not configured"}, status_code=503)
    rough_idea = body.get("rough_idea", "").strip()
    selected_hook_id = body.get("selected_hook_id", "").strip()
    clip_count = int(body.get("clip_count", 5))
    style_notes = (body.get("style_notes") or "").strip() or None
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
        script = await asyncio.to_thread(
            provider.generate_reel_script, rough_idea, selected_hook, clip_count, style_notes,
        )
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
        voice_id = await asyncio.to_thread(provider.clone_voice, name, audio_tuples)
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
        voices = await asyncio.to_thread(provider.list_voices)
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
        audio_bytes = await asyncio.to_thread(provider.text_to_speech, voice_id, text)
        return Response(content=audio_bytes, media_type="audio/mpeg")
    except VoiceCloningProviderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/v1/reel/captions-overlay", response_model=None)
async def render_reel_captions_overlay(
    voiceover: UploadFile = File(...),
):
    """Render a standalone captions-only overlay video for the generated voiceover."""
    settings = get_settings()
    if not settings.elevenlabs_reel_api_key:
        return JSONResponse({"error": "ElevenLabs API key not configured"}, status_code=503)

    media_proc = FfmpegMediaProcessor()
    temp_dir = tempfile.mkdtemp()
    voiceover_path: Path | None = None
    subtitle_path = Path(temp_dir) / "captions.ass"
    overlay_path = Path(temp_dir) / "captions-overlay.mov"

    try:
        voiceover_suffix = Path(voiceover.filename or "voiceover").suffix or ".mp3"
        voiceover_path = Path(temp_dir) / f"voiceover{voiceover_suffix}"
        voiceover_path.write_bytes(await voiceover.read())

        try:
            transcription = await asyncio.to_thread(
                _reel_caption_transcription_provider(settings).transcribe,
                voiceover_path,
                None,
            )
        except (TranscriptionProviderError, RuntimeError) as exc:
            raise RuntimeError(f"Caption transcription failed: {exc}") from exc

        render_options = default_caption_render_options(
            frame_width=1080,
            frame_height=1920,
            font_path=settings.caption_font_path,
            font_name=settings.caption_font_name,
            font_size=52,
        )
        cues = segments_to_caption_cues(transcription.segments, render_options)
        if not cues:
            raise RuntimeError("No usable caption cues were produced")

        write_ass_subtitles(cues, subtitle_path, render_options)
        overlay_duration = max(
            float(await asyncio.to_thread(media_proc._probe_duration, voiceover_path)),
            max((cue.end_ms for cue in cues), default=0) / 1000.0,
        )
        await asyncio.to_thread(
            media_proc.render_caption_overlay_video,
            subtitle_path,
            overlay_path,
            overlay_duration,
            render_options,
        )

        def cleanup():
            import shutil

            shutil.rmtree(temp_dir, ignore_errors=True)

        return FileResponse(
            str(overlay_path),
            media_type="video/quicktime",
            filename="captions-overlay.mov",
            background=BackgroundTask(cleanup),
        )
    except Exception as e:
        import shutil

        shutil.rmtree(temp_dir, ignore_errors=True)
        return JSONResponse({"error": _compact_reel_error(e)}, status_code=400)


@router.post("/v1/reel/caption-video", response_model=None)
async def render_reel_with_captions(
    video: UploadFile | None = File(default=None),
    voiceover: UploadFile = File(...),
    narration_text: str = Form(default=""),
    source_asset_id: str = Form(default=""),
    response_mode: str = Form(default="file"),
):
    """Burn captions onto an already assembled reel."""
    settings = get_settings()
    media_proc = FfmpegMediaProcessor()
    temp_dir = tempfile.mkdtemp()
    input_video_path = Path(temp_dir) / "reel.mp4"
    voiceover_path: Path | None = None
    subtitle_path = Path(temp_dir) / "captions.ass"
    output_path = Path(temp_dir) / "reel-captioned.mp4"

    try:
        normalized_source_asset_id = source_asset_id.strip()
        normalized_response_mode = response_mode.strip().lower()
        if normalized_source_asset_id:
            asset = _get_reel_download_payload(normalized_source_asset_id)
            if asset is None:
                return JSONResponse({"error": "The plain reel is no longer available"}, status_code=400)
            payload, _media_type, _filename = asset
            input_video_path.write_bytes(payload)
        elif video is not None:
            input_video_path.write_bytes(await video.read())
        else:
            return JSONResponse({"error": "video or source_asset_id is required"}, status_code=400)

        voiceover_suffix = Path(voiceover.filename or "voiceover").suffix or ".mp3"
        voiceover_path = Path(temp_dir) / f"voiceover{voiceover_suffix}"
        voiceover_path.write_bytes(await voiceover.read())

        render_options = default_caption_render_options(
            frame_width=1080,
            frame_height=1920,
            font_path=settings.caption_font_path,
            font_name=settings.caption_font_name,
            font_size=52,
        )
        normalized_narration = " ".join((narration_text or "").split()).strip()
        if normalized_narration:
            duration_ms = max(
                1,
                round(float(await asyncio.to_thread(media_proc._probe_duration, voiceover_path)) * 1000),
            )
            cues = segments_to_caption_cues(
                [
                    TimedTextSegment(
                        start_ms=0,
                        end_ms=duration_ms,
                        text=normalized_narration,
                    )
                ],
                render_options,
            )
        else:
            try:
                transcription = await asyncio.to_thread(
                    _reel_caption_transcription_provider(settings).transcribe,
                    voiceover_path,
                    None,
                )
            except (TranscriptionProviderError, RuntimeError) as exc:
                raise RuntimeError(f"Caption transcription failed: {exc}") from exc
            cues = segments_to_caption_cues(transcription.segments, render_options)
        if not cues:
            raise RuntimeError("No usable caption cues were produced")

        write_ass_subtitles(cues, subtitle_path, render_options)
        await asyncio.to_thread(
            media_proc.burn_subtitles_into_video,
            input_video_path,
            subtitle_path,
            output_path,
            render_options,
        )

        def cleanup():
            import shutil

            shutil.rmtree(temp_dir, ignore_errors=True)

        if normalized_response_mode == "json":
            _asset_id, download_url = _store_reel_download(output_path, filename="reel-captioned.mp4")
            cleanup()
            return JSONResponse({"download_url": download_url})

        return FileResponse(
            str(output_path),
            media_type="video/mp4",
            filename="reel-captioned.mp4",
            background=BackgroundTask(cleanup),
        )
    except Exception as e:
        import shutil

        shutil.rmtree(temp_dir, ignore_errors=True)
        return JSONResponse({"error": _compact_reel_error(e)}, status_code=400)


@router.post("/v1/reel/assemble", response_model=None)
async def assemble_reel(
    clips: list[UploadFile] = File(..., alias="clips"),
    voiceover: UploadFile = File(...),
    captions_enabled: bool = Form(default=True),
    response_mode: str = Form(default="file"),
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
        normalized_response_mode = response_mode.strip().lower()
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
            await asyncio.to_thread(
                media_proc.auto_cut_clip, p, out,
                5.0, 7.0,
            )
            trimmed_paths.append(out)

        await asyncio.to_thread(
            media_proc.concat_clips_with_audio,
            trimmed_paths, voiceover_path, output_path,
            apply_rotation=False,
        )
        final_output_path = output_path

        if captions_enabled:
            try:
                transcription = await asyncio.to_thread(
                    _reel_caption_transcription_provider(settings).transcribe,
                    voiceover_path,
                    None,
                )
            except (TranscriptionProviderError, RuntimeError) as exc:
                raise RuntimeError(f"Caption transcription failed: {exc}") from exc

            render_options = default_caption_render_options(
                frame_width=1080,
                frame_height=1920,
                font_path=settings.caption_font_path,
                font_name=settings.caption_font_name,
                font_size=52,
            )
            cues = segments_to_caption_cues(transcription.segments, render_options)
            if not cues:
                raise RuntimeError("No usable caption cues were produced")

            write_ass_subtitles(cues, subtitle_path, render_options)
            await asyncio.to_thread(
                media_proc.burn_subtitles_into_video,
                output_path, subtitle_path, captioned_output_path, render_options,
            )
            final_output_path = captioned_output_path

        def cleanup():
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)

        if normalized_response_mode == "json":
            asset_id, download_url = _store_reel_download(
                final_output_path,
                filename="reel-captioned.mp4" if captions_enabled else "reel.mp4",
            )
            cleanup()
            return JSONResponse({"asset_id": asset_id, "download_url": download_url})

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
