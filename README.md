# AIEdit

AIEdit is a hackathon MVP for turning raw clips into creator-ready short-form videos.

It combines:
- AI captions and transcript cleanup
- auto-cutting dead air from talking videos
- a browser-based caption editor
- AI reel scripting from a rough idea
- voice cloning and voiceover generation
- final vertical reel assembly with optional burned-in captions

The goal is simple: help creators make AI-assisted videos that still feel natural, personal, and platform-native instead of obviously AI-generated.

## What Judges Should Know

- This project is a **FastAPI web app**, not a mobile app.
- It includes **two built-in browser UIs**:
  - `/` for transcript upload, auto-cut, and caption editing
  - `/reel-generator` for AI reel creation
- The easiest local setup uses:
  - SQLite
  - local filesystem storage
  - inline processing
- That means **no Redis, no Postgres, and no Docker are required** for a demo run.

## 3-Minute Local Setup

### 1. Prerequisites

Install:
- Python `3.13+`
- `ffmpeg`

Examples:

```bash
# macOS (Homebrew)
brew install ffmpeg

# Ubuntu / Debian
sudo apt-get update && sudo apt-get install -y ffmpeg
```

### 2. Install Python Dependencies

From the project root:

```bash
python3 -m pip install -e ".[dev]"
```

### 3. Configure Environment

Create a local env file:

```bash
cp .env.example .env
```

Minimum notes:
- The app can start without Redis/Postgres config changes.
- For real AI features, add provider keys in `.env`.

Recommended keys:
- `ELEVENLABS_API_KEY` for transcription
- `ELEVENLABS_VOICE_API_KEY` for voice cloning / TTS (can be the same key)
- `MISTRAL_API_KEY` for AI reel script generation

If you do not add provider keys:
- the server can still boot
- the UI can load
- AI-dependent actions will fail when called

### 4. Run the App

```bash
python3 -m uvicorn app.main:app --reload
```

The app will usually start at:

```text
http://127.0.0.1:8000
```

### 5. Open the Demo

Open these pages in a browser:
- [http://127.0.0.1:8000/](http://127.0.0.1:8000/) for transcript, auto-cut, and caption editing
- [http://127.0.0.1:8000/reel-generator](http://127.0.0.1:8000/reel-generator) for reel generation

Health check:
- [http://127.0.0.1:8000/healthz](http://127.0.0.1:8000/healthz)

Expected response:

```json
{"status":"ok"}
```

## Demo Flow

### Flow 1: Transcript + Auto-Cut + Caption Editor

1. Open `/`
2. Upload a video or audio file
3. The app transcribes speech
4. Silence is detected and removable dead-air cuts are suggested
5. Captions are generated and mapped to the edited timeline
6. You can preview, adjust cues, and render a final captioned export

This flow is useful for:
- talking-head clips
- camera-roll videos that need cleaner pacing
- quick subtitle generation

### Flow 2: AI Reel Generator

1. Open `/reel-generator`
2. Upload B-roll clips
3. Provide a rough idea
4. Generate hook suggestions
5. Generate a structured reel script
6. Optionally clone a voice and create voiceover
7. Assemble a vertical reel and optionally burn in captions

This flow is useful for:
- short-form social content
- creator-style reels
- rapid content ideation from rough footage

## Feature Summary

### Caption and Editing Features

- Upload media and transcribe it
- Auto-detect silence
- Remove dead air
- Generate synced captions
- Edit caption timing and text in-browser
- Export final video with captions
- Export SRT / timeline outputs for editing workflows

### Reel Creation Features

- Generate viral hook suggestions
- Turn rough ideas into a structured reel script
- Analyze example creator content
- Clone a voice for more authentic voiceover
- Generate TTS voiceover
- Assemble multiple clips into a final vertical reel
- Export plain reel and captioned reel versions

## Tech Stack

- FastAPI
- SQLAlchemy
- SQLite (local default)
- MoviePy
- FFmpeg
- ElevenLabs
- Mistral
- Celery / Redis (optional deployment path)
- local filesystem storage or S3-compatible storage

## Local Defaults

The provided `.env.example` is already set up for the simplest local run:

- `AIEDIT_DATABASE_URL=sqlite+pysqlite:///./aiedit.db`
- `AIEDIT_TASK_EXECUTION_MODE=inline`
- `AIEDIT_STORAGE_BACKEND=local`
- `AIEDIT_LOCAL_STORAGE_PATH=.local-storage`

That means the local demo uses:
- a file-backed SQLite database
- no worker process
- no queue service
- local disk instead of cloud object storage

## API Endpoints

### Core

- `GET /healthz`
- `GET /`
- `GET /reel-generator`

### Analysis Jobs

- `POST /v1/analysis-jobs`
- `GET /v1/analysis-jobs/{job_id}`
- `GET /v1/analysis-jobs/{job_id}/result`

### Reel Routes

- `GET /v1/reel/voices`
- `POST /v1/reel/clone-voice`
- `POST /v1/reel/analyze-example`
- `POST /v1/reel/suggest-hooks`
- `POST /v1/reel/generate-script`
- `POST /v1/reel/generate-voiceover`
- `POST /v1/reel/assemble`
- `POST /v1/reel/caption-video`
- `POST /v1/reel/captions-overlay`

## Troubleshooting

### `uvicorn` starts but some actions fail

Most likely cause:
- missing `ELEVENLABS_API_KEY`
- missing `MISTRAL_API_KEY`
- missing `ffmpeg`

### `ffmpeg` not found

Install it first, then restart the server.

### Port `8000` already in use

Run on another port:

```bash
python3 -m uvicorn app.main:app --reload --port 8001
```

### Need the original heavier deployment shape

The repo also includes `docker-compose.yml`, but judges do not need it for the basic local demo.

## Project Structure

```text
app/
  api/
    routes.py          # transcript + auto-cut UI and endpoints
    reel_routes.py     # reel generator UI and endpoints
  captions.py          # caption timing and rendering helpers
  media.py             # FFmpeg/media pipeline helpers
  providers.py         # ElevenLabs + Mistral integrations
  services.py          # analysis job lifecycle
  main.py              # FastAPI app entrypoint
tests/                 # pytest coverage
.env.example           # local demo configuration
```

## One-Line Pitch

AIEdit helps creators turn rough footage into polished short-form videos with captions, smarter pacing, AI-generated reel ideas, and authentic voice-driven outputs.
