import re

with open('app/api/routes.py', 'r') as f:
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
      max-width: 1000px;
      margin: 0 auto;
      padding: 0;
      background: var(--bg);
      color: var(--text);
      display: flex;
      flex-direction: column;
      min-height: 100vh;
    }
    nav { 
      padding: 24px; 
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
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
    .layout-container {
      display: flex;
      flex: 1;
      overflow: hidden;
    }
    .left-col {
      width: 380px;
      min-width: 380px;
      border-right: 1px solid var(--border);
      padding: 32px 24px;
      overflow-y: auto;
    }
    .right-col {
      flex: 1;
      padding: 32px 40px;
      background: var(--panel);
      display: flex;
      flex-direction: column;
      align-items: center;
      overflow-y: auto;
    }
    h1 { margin: 0 0 12px; font-size: 24px; font-weight: 600; letter-spacing: -0.02em; }
    h3 { margin: 0 0 16px; font-size: 14px; font-weight: 600; color: var(--text); text-transform: uppercase; letter-spacing: 0.05em; }
    .subtitle { color: var(--muted); margin-bottom: 32px; font-size: 14px; line-height: 1.5; }
    
    .section { margin-bottom: 40px; }
    .section-divider {
      height: 1px;
      background: var(--border);
      margin: 32px 0;
    }
    
    label { display: block; font-size: 13px; font-weight: 500; margin-bottom: 8px; color: var(--text); }
    .input-group { margin-bottom: 20px; }
    
    input[type="text"], select, textarea {
      width: 100%;
      padding: 10px 12px;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: transparent;
      color: var(--text);
      font-family: inherit;
      font-size: 14px;
      transition: border-color 0.15s;
    }
    input[type="text"]:focus, select:focus, textarea:focus {
      border-color: #71717a;
      outline: none;
    }
    input[type="text"]::placeholder, textarea::placeholder { color: #52525b; }
    
    .file-dropzone {
      border: 1px dashed var(--border);
      border-radius: 6px;
      padding: 12px;
      text-align: center;
      transition: border-color 0.15s;
    }
    .file-dropzone:hover { border-color: #71717a; }
    input[type="file"] { 
      width: 100%;
      font-size: 13px;
      color: var(--muted);
    }
    input[type="file"]::file-selector-button {
      background: var(--panel);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 6px 12px;
      border-radius: 4px;
      cursor: pointer;
      margin-right: 12px;
      font-size: 13px;
    }
    
    .toggle-row {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 12px;
      font-size: 13px;
      color: var(--muted);
      cursor: pointer;
    }
    .toggle-row input[type="checkbox"] {
      appearance: none;
      width: 32px;
      height: 18px;
      background: var(--panel);
      border-radius: 10px;
      border: 1px solid var(--border);
      position: relative;
      cursor: pointer;
      transition: 0.2s;
    }
    .toggle-row input[type="checkbox"]::before {
      content: '';
      position: absolute;
      width: 12px;
      height: 12px;
      border-radius: 50%;
      background: var(--muted);
      top: 2px;
      left: 2px;
      transition: 0.2s;
    }
    .toggle-row input[type="checkbox"]:checked {
      background: var(--text);
      border-color: var(--text);
    }
    .toggle-row input[type="checkbox"]:checked::before {
      background: var(--bg);
      transform: translateX(14px);
    }
    .toggle-row:hover { color: var(--text); }
    
    button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 10px 16px;
      border-radius: 6px;
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.15s;
      white-space: nowrap;
    }
    .btn-primary {
      background: var(--brand);
      color: #000;
      border: 1px solid var(--brand);
      width: 100%;
    }
    .btn-primary:hover { background: var(--brand-hover); }
    .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
    
    .btn-ghost {
      background: transparent;
      color: var(--text);
      border: 1px solid var(--border);
    }
    .btn-ghost:hover:not(:disabled) { background: var(--border); }
    .btn-ghost:disabled { opacity: 0.5; color: var(--muted); border-color: transparent; }
    
    .action-row {
      display: flex;
      gap: 8px;
      margin-top: 12px;
    }
    .action-row button { flex: 1; }
    
    /* Previews & Stage */
    .stage-header {
      display: flex;
      justify-content: flex-end;
      width: 100%;
      max-width: 420px;
      margin-bottom: 16px;
      gap: 8px;
    }
    #previewPanel.visible { display: flex; flex-direction: column; width: 100%; align-items: center; }
    #previewPanel { display: none; width: 100%; }
    
    .preview-wrap {
      position: relative;
      width: 100%;
      max-width: 420px;
      aspect-ratio: 9 / 16;
      background: #000;
      border-radius: 8px;
      overflow: hidden;
      border: 1px solid var(--border);
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
      color: #52525b;
      font-size: 14px;
      pointer-events: none;
    }
    
    .preview-controls {
      display: flex;
      align-items: center;
      justify-content: space-between;
      width: 100%;
      max-width: 420px;
      margin-top: 12px;
    }
    .preview-time {
      font-size: 12px;
      color: var(--muted);
      font-variant-numeric: tabular-nums;
    }
    
    /* Timeline styling override for minimal look */
    .tl-container {
      position: relative;
      height: 36px;
      cursor: pointer;
      user-select: none;
      width: 100%;
      max-width: 420px;
      margin: 12px auto 0;
    }
    .tl-track {
      position: absolute;
      top: 16px;
      left: 0;
      right: 0;
      height: 4px;
      background: var(--border);
      border-radius: 2px;
    }
    .tl-fill {
      height: 100%;
      width: 0%;
      background: var(--muted);
      border-radius: 2px;
    }
    .tl-playhead {
      position: absolute;
      top: 12px;
      width: 12px;
      height: 12px;
      margin-left: -6px;
      border-radius: 50%;
      background: var(--text);
      left: 0%;
      z-index: 2;
    }
    .tl-playhead:hover, .tl-playhead.dragging { transform: scale(1.3); }
    .tl-hover-line {
      position: absolute;
      top: 12px;
      width: 1px;
      height: 12px;
      background: var(--text);
      pointer-events: none;
      display: none;
      z-index: 1;
    }
    .tl-preview-overlay {
      position: absolute;
      bottom: 36px;
      transform: translateX(-50%);
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 4px;
      pointer-events: none;
      opacity: 0;
      transition: opacity 0.15s ease;
      z-index: 10;
    }
    .tl-preview-overlay.show { opacity: 1; }
    .tl-preview-canvas { display: block; border-radius: 2px; background: #000; }
    .tl-preview-time { display: block; text-align: center; font-size: 11px; color: var(--muted); margin-top: 4px; }
    .tl-cut-region {
      position: absolute;
      top: 16px;
      height: 4px;
      background: rgba(239, 68, 68, 0.4);
      pointer-events: none;
      z-index: 1;
    }
    
    #captionEditorCard { display: none; width: 100%; flex-direction: column; align-items: center; }
    #captionEditorCard.visible { display: flex; }
    
    .editor-timeline {
      position: relative;
      width: 100%;
      max-width: 420px;
      height: 60px;
      margin: 16px auto 0;
      border-radius: 6px;
      border: 1px solid var(--border);
      background: var(--bg);
      overflow: hidden;
      user-select: none;
    }
    .editor-track-fill {
      position: absolute;
      inset: 0 auto 0 0;
      width: 0%;
      background: rgba(255, 255, 255, 0.05);
      pointer-events: none;
    }
    .editor-track-playhead {
      position: absolute;
      top: 0;
      bottom: 0;
      width: 1px;
      background: var(--text);
      pointer-events: none;
      z-index: 4;
    }
    .editor-track-hover {
      position: absolute;
      top: 0;
      bottom: 0;
      width: 1px;
      background: var(--muted);
      pointer-events: none;
      display: none;
      z-index: 3;
    }
    .caption-block {
      position: absolute;
      top: 12px;
      height: 36px;
      border-radius: 4px;
      background: var(--panel);
      color: var(--text);
      font-size: 11px;
      font-weight: 500;
      line-height: 36px;
      padding: 0 8px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      cursor: grab;
      border: 1px solid var(--border);
      z-index: 2;
    }
    .caption-block.selected { border-color: var(--text); }
    .caption-handle {
      position: absolute;
      top: 0;
      width: 6px;
      height: 100%;
      background: transparent;
      cursor: ew-resize;
    }
    .caption-handle:hover { background: rgba(255,255,255,0.1); }
    .caption-handle.start { left: 0; }
    .caption-handle.end { right: 0; }
    
    .editor-ruler {
      position: relative;
      height: 16px;
      width: 100%;
      max-width: 420px;
      margin: 24px auto 0;
      border-bottom: 1px solid var(--border);
    }
    .editor-ruler-tick {
      position: absolute;
      bottom: 0;
      width: 1px;
      height: 6px;
      background: var(--border);
    }
    .editor-ruler-tick span {
      position: absolute;
      top: -14px;
      left: 50%;
      transform: translateX(-50%);
      font-size: 9px;
      color: var(--muted);
    }
    
    .cue-inspector {
      width: 100%;
      max-width: 420px;
      margin: 24px auto 0;
    }
    .cue-inspector textarea {
      min-height: 60px;
      margin-bottom: 12px;
    }
    .cue-inspector-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 12px;
      margin-bottom: 16px;
    }
    input[type="number"] {
      width: 100%;
      padding: 8px 10px;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: transparent;
      color: var(--text);
      font-variant-numeric: tabular-nums;
      font-size: 13px;
    }
    input[type="number"]:focus { border-color: #71717a; outline: none; }
    input[type="range"] {
      width: 100%;
      accent-color: var(--text);
    }
    
    .cue-nav {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding-top: 16px;
      border-top: 1px solid var(--border);
    }
    .cue-nav-actions { display: flex; gap: 8px; }
    .cue-meta { font-size: 12px; color: var(--muted); }
    
    #out {
      background: transparent;
      border: 1px solid var(--border);
      color: var(--muted);
      padding: 16px;
      border-radius: 6px;
      font-size: 12px;
      max-height: 200px;
      overflow: auto;
      margin-top: 24px;
      width: 100%;
      max-width: 420px;
      display: none;
    }
    #out:not(:empty) { display: block; }
    
    .download-link {
      display: inline-block;
      margin-top: 16px;
      color: var(--text);
      text-decoration: underline;
      font-size: 13px;
    }
    .download-link:hover { color: #fff; }
    
    .autocut-info {
      font-size: 13px;
      color: var(--muted);
      margin: 12px 0;
      text-align: center;
    }
    .autocut-info span { color: var(--text); font-weight: 500; }
    
    .editor-caption-overlay {
      position: absolute;
      left: 50%;
      bottom: 22%;
      transform: translateX(-50%);
      width: calc(100% - 32px);
      text-align: center;
      white-space: pre-line;
      font-weight: 700;
      font-size: clamp(20px, 4vw, 36px);
      line-height: 1.2;
      -webkit-text-stroke: 3px rgba(0, 0, 0, 0.95);
      paint-order: stroke fill;
      pointer-events: none;
      z-index: 3;
    }
    
    /* Responsive tweaks */
    @media (max-width: 768px) {
      .layout-container { flex-direction: column; }
      .left-col { width: 100%; min-width: 100%; border-right: none; border-bottom: 1px solid var(--border); }
      .right-col { padding: 24px 16px; }
    }
"""
    html_new = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AIEdit API Playground</title>
""" + new_css + """  </style>
</head>
<body>
  <nav>
    <a href="/" class="active">Transcript & Auto-Cut</a>
    <a href="/reel-generator">Reel Generator</a>
  </nav>

  <div class="layout-container">
    <!-- LEFT COLUMN: Input & Config -->
    <div class="left-col" id="leftPanel">
      <h1>Transcript & Auto-Cut</h1>
      <div class="subtitle">Upload footage to generate captions and automatically cut dead air.</div>

      <div class="section">
        <h3>Create Job</h3>
        <form id="createForm">
          <div class="input-group">
            <label for="media_file">Media File</label>
            <div class="file-dropzone">
              <input id="media_file" name="media_file" type="file" accept="audio/*,video/*" required />
            </div>
          </div>
          <div class="input-group">
            <label for="input_language_hint">Language Hint</label>
            <input id="input_language_hint" name="input_language_hint" type="text" placeholder="e.g. en (optional)" />
          </div>
          
          <label class="toggle-row">
            <input id="include_raw_transcript" name="include_raw_transcript" type="checkbox" checked />
            Include raw transcript
          </label>
          <label class="toggle-row" style="margin-bottom: 20px;">
            <input id="include_timestamps" name="include_timestamps" type="checkbox" checked />
            Include timestamps
          </label>
          
          <button type="submit" class="btn-primary">Submit Job</button>
        </form>
      </div>

      <div class="section-divider"></div>

      <div class="section">
        <h3>Status / Result</h3>
        <div class="input-group">
          <label for="job_id">Job ID</label>
          <input id="job_id" type="text" placeholder="Paste job id..." />
        </div>
        <div class="action-row">
          <button id="statusBtn" class="btn-ghost" type="button">Get Status</button>
          <button id="resultBtn" class="btn-ghost" type="button">Get Result</button>
        </div>
      </div>
    </div>

    <!-- RIGHT COLUMN: Stage (Video & Editor) -->
    <div class="right-col">
      <!-- Standard Preview Mode -->
      <div id="previewPanel">
        <div class="stage-header">
          <button id="autoCutBtn" class="btn-ghost" type="button" disabled>Open Editor</button>
        </div>
        <div class="preview-wrap">
          <video id="previewVideo" class="preview-video" preload="metadata"></video>
          <div id="previewPlaceholder" class="preview-placeholder">No media loaded</div>
        </div>
        <div class="preview-controls">
          <button id="playPauseBtn" class="btn-ghost" type="button">Play</button>
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

      <!-- Editor Mode -->
      <div id="captionEditorCard">
        <div class="stage-header">
          <button id="renderEditorBtn" class="btn-ghost" type="button">Render Video</button>
          <button id="exportSrtBtn" class="btn-ghost" type="button">Export SRT</button>
        </div>
        <div class="preview-wrap">
          <video id="editorVideo" class="preview-video" preload="metadata"></video>
          <div id="editorCaptionOverlay" class="editor-caption-overlay hidden"></div>
        </div>
        <div class="preview-controls">
          <button id="editorPlayBtn" class="btn-ghost" type="button">Play</button>
          <span id="editorTimeDisplay" class="preview-time">0:00 / 0:00</span>
        </div>
        
        <div id="editorRuler" class="editor-ruler"></div>
        <div id="editorTimeline" class="editor-timeline">
          <div id="editorTrack" class="editor-track">
            <div id="editorTrackFill" class="editor-track-fill"></div>
            <div id="editorTrackPlayhead" class="editor-track-playhead"></div>
            <div id="editorTrackHover" class="editor-track-hover"></div>
          </div>
          <div id="editorMiniPreview" class="tl-preview-overlay" style="bottom: 72px;">
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
          
          <div>
            <label for="captionHeightInput">Caption Height</label>
            <input id="captionHeightInput" type="range" min="10" max="90" step="1" />
          </div>
          
          <div class="cue-nav">
            <div class="cue-nav-actions">
              <button id="prevCueBtn" class="btn-ghost" type="button">Previous</button>
              <button id="nextCueBtn" class="btn-ghost" type="button">Next</button>
            </div>
            <span id="cueMeta" class="cue-meta">No cue selected</span>
          </div>
          
          <div id="editorStatus" style="font-size: 13px; margin-top: 12px; color: var(--muted);"></div>
          <a id="editorDownloadLink" class="download-link hidden" href="#" download="autocut.mp4">Download Reel</a>
        </div>
      </div>

      <pre id="out"></pre>
    </div>
  </div>
"""

    # Do the slice and replace
    body_content_end = content.find('  <script>', html_end)
    script_content = content[body_content_end:]
    
    new_content = content[:html_start+24] + html_new + script_content
    with open('app/api/routes.py', 'w') as f:
        f.write(new_content)
    print("Rewritten successfully")
