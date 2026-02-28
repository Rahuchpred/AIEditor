# AIEdit Feature 4 MVP

Backend API for asynchronous media transcription from uploaded audio/video.

## Stack
- FastAPI for HTTP endpoints
- Celery with Redis for job dispatch
- PostgreSQL for job metadata
- S3-compatible object storage for media and result payloads
- ElevenLabs for transcription

## API
- `POST /v1/analysis-jobs`
- `GET /v1/analysis-jobs/{job_id}`
- `GET /v1/analysis-jobs/{job_id}/result`
- `GET /healthz`

## Local Development
1. Install dependencies: `python3 -m pip install -e '.[dev]'`
2. Copy `.env.example` to `.env` and set real provider credentials.
   The app accepts both docs-style keys and `AIEDIT_` aliases:
   - ElevenLabs (required): `ELEVENLABS_API_KEY` or `AIEDIT_ELEVENLABS_API_KEY`
   - Mistral (optional / not used in transcript-only mode): `MISTRAL_API_KEY` or `AIEDIT_MISTRAL_API_KEY`
   Optional overrides:
   - `AIEDIT_ELEVENLABS_API_URL`, `ELEVENLABS_MODEL_ID`/`AIEDIT_ELEVENLABS_MODEL_ID`
   - `AIEDIT_MISTRAL_API_URL`, `MISTRAL_MODEL`/`AIEDIT_MISTRAL_MODEL`
3. Run the API: `uvicorn app.main:app --reload`

The default local setup uses:
- SQLite for job metadata
- local filesystem storage
- inline processing, so no Redis or Celery worker is required

Use `docker-compose.yml` only if you want the original Postgres + Redis + S3-compatible deployment shape.

## Storage Layout
- `jobs/{job_id}/input.<ext>`
- `jobs/{job_id}/normalized.wav`
- `jobs/{job_id}/result.json`

## Retention Defaults
- Original uploads: 7 days
- Normalized audio: 7 days
- Results: 30 days

Retention cleanup is not automated in this MVP. It should be enforced by object storage lifecycle rules.
