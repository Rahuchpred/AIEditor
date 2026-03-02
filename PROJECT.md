# AIEdit — AI-Powered Video Editor

> Hackathon MVP: Turn raw footage into polished, captioned content using AI — authentically, with your own voice and B-roll.

---

## What It Does

AIEdit is a backend-powered video editing tool that combines **ElevenLabs** (transcription + voice cloning + TTS), **Mistral AI** (script generation), and **FFmpeg** (media processing) to automate the tedious parts of content creation while keeping it authentic.

---

## Demo Features

### Feature 1: Smart Caption Editor with Auto-Cut

**Flow:**
1. User uploads a video
2. ElevenLabs Scribe transcribes it with word-level timing
3. Silence segments (≥0.4s) are auto-detected and cut out
4. Captions are generated and synced to the trimmed timeline
5. A **mini caption editor** lets users adjust cues — drag timing, edit text, reposition — like a real editing app
6. Final render burns styled captions into the video

**Key tech:** FFmpeg silencedetect → auto-cut → caption remapping → ASS subtitle rendering → MoviePy burn-in with portrait-safe layout.

### Feature 2: AI Reel Generator (Authentic AI Video)

**Flow:**
1. User uploads 4-5 B-roll clips (min 2) and records a rough idea via browser dictation
2. Mistral AI takes the rough idea + a catalog of **10,000 viral hooks** and improves the script — selecting the best hook, structuring body segments per clip, adding a CTA
3. User auto-clones their voice with ElevenLabs (instant voice clone from samples)
4. TTS generates voiceover in the user's cloned voice
5. Captions are auto-generated from the voiceover and burned in
6. Clips are trimmed, scaled to 9:16, concatenated with audio → final reel

**The result:** An AI-generated video that uses **your real B-roll** and **your real voice** — authentic content, AI-assisted.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **API** | FastAPI + Pydantic |
| **Database** | SQLAlchemy 2.0 (SQLite dev / PostgreSQL prod) |
| **Media** | FFmpeg + MoviePy 2.0 |
| **Transcription** | ElevenLabs Scribe v1 |
| **Voice Clone + TTS** | ElevenLabs Instant Voice Clone |
| **Script AI** | Mistral AI |
| **Task Queue** | Celery + Redis (optional; inline mode for dev) |
| **Storage** | Local filesystem or S3/MinIO |
| **Experiment Tracking** | Weights & Biases (optional) |

---

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│   Frontend   │────▶│  FastAPI API  │────▶│  Media Pipeline  │
│  (Upload UI) │     │   Routes     │     │  FFmpeg/MoviePy  │
└─────────────┘     └──────┬───────┘     └────────┬────────┘
                           │                       │
                    ┌──────▼───────┐        ┌──────▼────────┐
                    │  AI Providers │        │    Storage     │
                    │ ElevenLabs   │        │  Local / S3    │
                    │ Mistral AI   │        └───────────────┘
                    └──────────────┘
```

---

## API Endpoints

### Transcription & Analysis
- `POST /v1/analysis-jobs` — Upload media, start transcription job
- `GET /v1/analysis-jobs/{id}` — Check job status
- `GET /v1/analysis-jobs/{id}/result` — Get transcript + metrics

### Caption Editor (Auto-Cut)
- `POST /v1/auto-cut/editor` — Create editor session (preview + cues + cuts)
- `GET /v1/auto-cut/editor-session/{id}/preview` — Stream preview video
- `POST /v1/auto-cut/editor-session/{id}/render` — Render final video with edited captions

### Reel Generator
- `GET /v1/reel/voices` — List available voices
- `POST /v1/reel/clone-voice` — Clone voice from audio samples
- `POST /v1/reel/suggest-hooks` — AI-ranked hooks from 10K catalog
- `POST /v1/reel/generate-script` — Generate reel script with Mistral
- `POST /v1/reel/generate-voiceover` — TTS with cloned voice
- `POST /v1/reel/assemble` — Assemble final reel (clips + audio + captions)

### Utility
- `GET /healthz` — Health check
- `GET /reel-generator` — Reel generator UI

---

## Caption System

- Word-level timing from ElevenLabs transcription
- Smart text wrapping (portrait: 18 chars, landscape: 32 chars)
- Cue normalization (min 600ms, max 3500ms)
- Timeline remapping after auto-cut regions
- ASS subtitle format with customizable styling (font, colors, outline)
- Portrait-safe rendering (auto-detects orientation, adjusts positioning)

---

## Hook Catalog System

- **10,000+ viral hooks** stored as JSON
- Token-based matching + phrase scoring for semantic ranking
- Section bonuses for contextual relevance
- Mistral AI final ranking by semantic fit to user's idea
- Fallback to full catalog if not enough matches

---

## Quick Start

```bash
# 1. Clone & install
pip install -e ".[dev]"

# 2. Configure
cp .env.example .env
# Set ELEVENLABS_API_KEY and MISTRAL_API_KEY

# 3. Run
uvicorn app.main:create_app --factory --reload

# 4. Test
pytest
```

---

## Project Structure

```
app/
├── api/
│   ├── routes.py          # Transcription + caption editor endpoints
│   └── reel_routes.py     # Reel generator endpoints + UI
├── captions.py            # Caption logic (cues, ASS, remapping)
├── media.py               # FFmpeg wrapper (inspect, trim, concat, silence)
├── providers.py           # ElevenLabs + Mistral integrations
├── services.py            # Job lifecycle management
├── hook_catalog.py        # Hook ranking system
├── reel_prompts.py        # Mistral prompt templates
├── models.py              # SQLAlchemy models
├── schemas.py             # Pydantic schemas
├── config.py              # Settings (dual-key support)
├── storage.py             # Object storage abstraction
├── container.py           # Dependency injection
├── db.py                  # Database setup
└── main.py                # FastAPI app factory

tests/                     # pytest test suite
output/hooks/              # Viral hooks JSON catalog
```

---

## Hackathon Focus

This project demonstrates that **AI-generated content doesn't have to feel fake**. By combining:
- **Your own video footage** (B-roll you actually shot)
- **Your own voice** (cloned, not a generic TTS voice)
- **AI for the hard parts** (scripting, timing, editing)

You get content that's **AI-assisted but authentically yours**.
