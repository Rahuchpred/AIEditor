import re

with open('app/api/reel_routes.py', 'r') as f:
    content = f.read()

# Replace the HTML block
html_start = content.find('    return """<!doctype html>')
html_end = content.find('  </style>\n</head>\n<body>\n')

if html_start != -1 and html_end != -1:
    new_css = """  <style>
    :root {
      --bg: #0a0a0a;
      --panel: #171717;
      --text: #f4f4f5;
      --muted: #a1a1aa;
      --border: #27272a;
      --brand: #ffffff;
      --brand-hover: #e4e4e7;
    }
    * { box-sizing: border-box; }
    body {
      font-family: 'Inter', system-ui, -apple-system, sans-serif;
      max-width: 800px;
      margin: 0 auto;
      padding: 0 24px 80px;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }
    nav { 
      padding: 24px 0; 
      border-bottom: 1px solid var(--border);
      margin-bottom: 40px;
      display: flex;
      gap: 16px;
    }
    nav a { 
      text-decoration: none; 
      color: var(--muted); 
      font-size: 14px;
      font-weight: 500;
      transition: color 0.15s;
    }
    nav a:hover, nav a.active { color: var(--text); }
    
    h1 { margin: 0 0 8px; font-size: 32px; font-weight: 600; letter-spacing: -0.02em; }
    .status { font-size: 14px; color: var(--muted); margin-bottom: 40px; }
    .status.ok { color: #4ade80; }
    .status.err { color: #f87171; }
    
    h2 { font-size: 20px; font-weight: 600; margin: 48px 0 24px; color: var(--text); border-bottom: 1px solid var(--border); padding-bottom: 12px; }
    h3 { margin: 0 0 8px; font-size: 14px; color: var(--muted); font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; }
    
    label { display: block; font-size: 14px; font-weight: 500; margin-bottom: 8px; color: var(--text); }
    .input-group { margin-bottom: 24px; position: relative; }
    
    input[type="text"], select, textarea {
      width: 100%;
      padding: 12px 16px;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: transparent;
      color: var(--text);
      font-family: inherit;
      font-size: 15px;
      transition: border-color 0.15s;
    }
    input[type="text"]:focus, select:focus, textarea:focus { border-color: #71717a; outline: none; }
    input[type="text"]::placeholder, textarea::placeholder { color: #52525b; }
    
    textarea.notion-block {
      border: none;
      border-left: 2px solid var(--border);
      border-radius: 0;
      padding: 8px 0 8px 16px;
      background: transparent;
      font-size: 16px;
      min-height: 120px;
    }
    textarea.notion-block:focus {
      border-color: var(--muted);
    }
    
    .file-dropzone {
      border: 1px dashed var(--border);
      border-radius: 6px;
      padding: 16px;
      transition: border-color 0.15s;
      display: flex;
      align-items: center;
    }
    .file-dropzone:hover { border-color: #71717a; }
    input[type="file"] { width: 100%; font-size: 13px; color: var(--muted); }
    input[type="file"]::file-selector-button {
      background: transparent;
      border: 1px solid var(--border);
      color: var(--text);
      padding: 6px 16px;
      border-radius: 4px;
      cursor: pointer;
      margin-right: 16px;
      font-size: 13px;
      transition: background 0.15s;
    }
    input[type="file"]::file-selector-button:hover { background: var(--panel); }
    
    button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 10px 20px;
      border-radius: 6px;
      font-size: 14px;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.15s;
      white-space: nowrap;
    }
    .btn-primary {
      background: var(--brand);
      color: #000;
      border: 1px solid var(--brand);
    }
    .btn-primary:hover { background: var(--brand-hover); }
    .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
    
    .btn-ghost {
      background: transparent;
      color: var(--text);
      border: 1px solid var(--border);
    }
    .btn-ghost:hover:not(:disabled) { background: var(--panel); }
    .btn-ghost:disabled { opacity: 0.5; color: var(--muted); border-color: transparent; cursor: not-allowed; }
    
    .dictation-btn {
      position: absolute;
      right: 16px;
      bottom: 16px;
      padding: 6px 12px;
      font-size: 12px;
      border-radius: 4px;
      background: #000;
      border: 1px solid var(--border);
      color: var(--muted);
    }
    .dictation-btn:hover:not(:disabled) { color: var(--text); border-color: #71717a; }
    .dictation-btn.active {
      background: rgba(239, 68, 68, 0.1);
      border-color: #ef4444;
      color: #fca5a5;
    }
    
    .hook-grid {
      display: flex;
      flex-direction: column;
      gap: 16px;
      margin-top: 16px;
      margin-bottom: 24px;
    }
    .hook-card {
      border: 1px solid transparent;
      border-left: 2px solid var(--border);
      padding: 12px 16px;
      cursor: pointer;
      transition: all 0.15s;
    }
    .hook-card:hover { border-left-color: #71717a; background: rgba(255,255,255,0.02); }
    .hook-card.selected {
      border: 1px solid var(--border);
      border-left: 2px solid var(--text);
      background: var(--panel);
      border-radius: 0 6px 6px 0;
    }
    .hook-card p { margin: 0 0 8px; font-size: 15px; }
    .hook-meta { font-size: 13px; color: var(--muted); margin-bottom: 8px; }
    .hook-source { color: var(--text); font-size: 12px; text-decoration: underline; opacity: 0.7; }
    .hook-source:hover { opacity: 1; }
    
    .script-section { margin-bottom: 24px; }
    .script-section [contenteditable] {
      min-height: 24px;
      padding: 12px 0;
      border: none;
      outline: none;
      font-size: 16px;
      line-height: 1.6;
      color: var(--text);
    }
    .script-section [contenteditable]:empty:before {
      content: attr(placeholder);
      color: #52525b;
      font-style: italic;
    }
    .script-section [contenteditable]:focus {
      border-bottom: 1px solid var(--border);
    }
    
    .checkbox-row {
      display: inline-flex;
      align-items: center;
      gap: 12px;
      cursor: pointer;
    }
    .checkbox-row input[type="checkbox"] {
      appearance: none;
      width: 18px;
      height: 18px;
      border: 1px solid var(--border);
      border-radius: 4px;
      background: transparent;
      cursor: pointer;
      position: relative;
    }
    .checkbox-row input[type="checkbox"]:checked {
      background: var(--brand);
      border-color: var(--brand);
    }
    .checkbox-row input[type="checkbox"]:checked::after {
      content: '';
      position: absolute;
      left: 6px;
      top: 2px;
      width: 4px;
      height: 10px;
      border: solid #000;
      border-width: 0 2px 2px 0;
      transform: rotate(45deg);
    }
    
    .asset-preview-shell {
      width: 100%;
      max-width: 420px;
      aspect-ratio: 9 / 16;
      margin: 32px auto 0;
      border-radius: 8px;
      overflow: hidden;
      background: #000;
      border: 1px solid var(--border);
    }
    .asset-preview-shell video {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    .asset-preview-controls {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 16px;
      margin-top: 16px;
    }
    .asset-preview-empty {
      margin-top: 32px;
      padding: 24px;
      border: 1px dashed var(--border);
      border-radius: 8px;
      color: var(--muted);
      text-align: center;
      font-size: 14px;
    }
    .asset-links {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 12px;
      margin-top: 24px;
    }
    .download-link { color: var(--text); text-decoration: underline; font-size: 14px; opacity: 0.8; }
    .download-link:hover { opacity: 1; }
    
    audio { width: 100%; margin-top: 16px; background: transparent; }
    audio::-webkit-media-controls-enclosure {
      border-radius: 6px;
      background-color: var(--panel);
    }
    
    #stylePreview {
      margin-top: 12px;
      padding: 16px;
      border-left: 2px solid var(--border);
      font-size: 14px;
      color: var(--muted);
      white-space: pre-wrap;
    }
    
    .hidden { display: none !important; }
"""
    html_new = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AI Reel Generator</title>
""" + new_css + """  </style>
</head>
<body>
  <nav>
    <a href="/">Transcript & Auto-Cut</a>
    <a href="/reel-generator" class="active">Reel Generator</a>
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
    
    <div class="input-group" style="padding-bottom: 16px; border-bottom: 1px solid var(--panel);">
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

    <div class="input-group" style="margin-top: 24px;">
      <label for="roughIdea">Rough idea / topic</label>
      <div style="position: relative;">
        <textarea id="roughIdea" class="notion-block" placeholder="e.g. 5 productivity hacks that changed my life"></textarea>
        <button id="roughIdeaDictationBtn" type="button" class="dictation-btn" aria-pressed="false">
          Start Dictation
        </button>
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
    
    <div style="display: flex; gap: 16px; margin-top: 32px;">
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
"""

    # Do the slice and replace
    body_content_end = content.find('  <script>', html_end)
    script_content = content[body_content_end:]
    
    new_content = content[:html_start+24] + html_new + script_content
    with open('app/api/reel_routes.py', 'w') as f:
        f.write(new_content)
    print("Rewritten reel_routes.py successfully")
