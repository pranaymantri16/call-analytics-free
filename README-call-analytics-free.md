# Call Analytics Free — Local Call Summary & Intelligence

A local-first, full-stack call analytics application that turns recorded customer calls into searchable transcripts, structured summaries, customer-interest signals, action items, and caller-performance metrics.

> **Status:** Development scaffold / MVP. Validate the full stack in your environment and complete the security checklist before using real customer recordings or relying on performance scores.

## Table of contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [Technology stack](#technology-stack)
- [Project structure](#project-structure)
- [Requirements](#requirements)
- [Quick start with Docker](#quick-start-with-docker)
- [Environment variables](#environment-variables)
- [Using the application](#using-the-application)
- [API reference](#api-reference)
- [Speech processing and summarization](#speech-processing-and-summarization)
- [Local development without Docker](#local-development-without-docker)
- [Troubleshooting](#troubleshooting)
- [Privacy and security](#privacy-and-security)
- [Limitations and future improvements](#limitations-and-future-improvements)
- [License](#license)

## Overview

The application accepts recordings through an upload endpoint or a trusted webhook. FastAPI saves the recording and creates a call record in PostgreSQL. Celery uses Redis to queue processing. Faster-Whisper transcribes audio locally; Pyannote.audio can optionally diarize speakers; a local Ollama model generates a structured summary. The Next.js dashboard presents call status, transcripts, summaries, customer interest, topics, action items, and caller metrics.

### Cost model

No paid inference APIs are required. Transcription, diarization (when enabled), and LLM inference run locally. “$0 recurring API cost” does not mean zero total cost: you need hardware, electricity, storage, and internet access for initial container and model downloads. Pyannote model access may require a Hugging Face account, acceptance of model terms, and a token for downloading the model; inference remains local.

## Features

- Upload WAV, MP3, M4A, OGG, and FLAC audio.
- Receive call-completed webhooks with an audio URL.
- Queue processing in a Celery worker.
- Local Faster-Whisper transcription and optional Pyannote.audio diarization.
- Ollama-generated structured call summaries.
- Customer-interest classification: `High`, `Medium`, or `Low`.
- Key topics, action items, and heuristic agent-performance score (1–10).
- PostgreSQL storage for callers, customers, calls, transcripts, and analysis.
- Search and status filtering for calls.
- Dashboard metrics, caller performance, interest distribution, and color-coded transcripts.

## Architecture

```text
Audio upload / trusted webhook
             |
             v
        FastAPI backend ------> PostgreSQL
             |
         Redis queue
             |
             v
        Celery worker
             |
       +-----+------+
       |            |
 Faster-Whisper  Pyannote.audio (optional)
       |            |
       +-----+------+
             v
        Local Ollama LLM
             |
             v
        PostgreSQL
             |
             v
        Next.js dashboard
```

### Docker services

| Service | Responsibility | Local address |
|---|---|---|
| `frontend` | Next.js dashboard | `http://localhost:3000` |
| `backend` | FastAPI API | `http://localhost:8000` |
| `worker` | Background audio processing | Internal service |
| `postgres` | Relational database | `localhost:5432` |
| `redis` | Celery queue and result backend | `localhost:6379` |
| `ollama` | Local LLM inference | `http://localhost:11434` |

Within Docker, services communicate using service names such as `postgres`, `redis`, and `ollama`. `localhost` inside a container refers to that same container, not another service.

## Technology stack

- **Backend:** Python 3.11, FastAPI, SQLAlchemy 2.x async, asyncpg, Celery, Redis, HTTPX.
- **Speech/AI:** Faster-Whisper, Pyannote.audio (optional), Ollama, `llama3.2` by default.
- **Frontend:** Next.js 14 App Router, React 18, TypeScript, Tailwind CSS, Lucide React.
- **Infrastructure:** Docker Compose, PostgreSQL, Redis, persistent Docker volumes.

## Project structure

```text
call-analytics-free/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── models/             # caller.py, customer.py, call.py
│   │   ├── services/           # stt_service.py, llm_service.py
│   │   ├── tasks/              # celery_tasks.py
│   │   └── api/                # calls.py, webhooks.py, analytics.py
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── app/                # dashboard and calls/[id] detail page
│   │   ├── components/         # TranscriptViewer.tsx
│   │   └── lib/                # API client/types
│   ├── package.json
│   └── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

## Requirements

- Windows 10/11, macOS, or Linux.
- Docker Desktop with its engine running, or Docker Engine and the Compose plugin.
- On Windows, Docker Desktop's Linux container engine and typically WSL 2.
- Internet access for initial container and AI model downloads.
- Sufficient disk space, RAM, and CPU capacity. CPU inference is supported but can be slow; GPU acceleration requires compatible container/runtime configuration.

Verify Docker:

```powershell
docker version
docker compose version
```

`docker version` should show both Client and Server sections. If it cannot connect to the server, start Docker Desktop and wait until its engine is running.

## Quick start with Docker

Run these commands from the repository root—the folder containing `docker-compose.yml` and `.env.example`.

### 1. Create the environment file

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

macOS/Linux:

```bash
cp .env.example .env
```

Edit `.env`. Replace example passwords and secrets before using the application with sensitive data.

### 2. Optional Pyannote setup

To enable speaker diarization, sign in to Hugging Face, accept the access terms for `pyannote/speaker-diarization-3.1` if required, create a suitable access token, and set `HF_TOKEN` in `.env`. If the token is missing or the pipeline cannot load, the current code falls back to a single speaker; it will not truly separate participants in that mode.

### 3. Build images

```powershell
docker compose build
```

If Docker Desktop fails exporting the backend/worker images due to an image-name conflict, try building sequentially:

```powershell
docker compose build backend
docker compose build worker
docker compose build frontend
```

The backend and worker share a Dockerfile. If an image-export error persists, capture the error and inspect the images before trying destructive cleanup. Do not delete Docker volumes as an initial troubleshooting step; they may contain database data and downloaded models.

### 4. Start services

Foreground mode:

```powershell
docker compose up
```

Background mode:

```powershell
docker compose up -d
```

The first build can take a long time because Docker downloads base images and installs AI dependencies. Ollama pulls the configured LLM, Faster-Whisper downloads its model on first use, and Pyannote may download its model when enabled.

### 5. Check services and logs

```powershell
docker compose ps
docker compose ps -a
docker compose logs --tail=100
```

Per-service logs:

```powershell
docker compose logs --tail=100 backend
docker compose logs --tail=100 worker
docker compose logs --tail=100 ollama
docker compose logs --tail=100 frontend
```

### 6. Open the app

- Dashboard: <http://localhost:3000>
- FastAPI docs: <http://localhost:8000/docs>
- API health: <http://localhost:8000/health>
- Ollama: <http://localhost:11434>

## Environment variables

The `.env.example` file is the initial configuration template.

| Variable | Purpose | Example/default |
|---|---|---|
| `POSTGRES_DB` | Database name | `callanalytics` |
| `POSTGRES_USER` | Database user | `callanalytics` |
| `POSTGRES_PASSWORD` | Database password | Replace example value |
| `DATABASE_URL` | SQLAlchemy database URL | Compose supplies the internal `postgres` hostname |
| `REDIS_URL` | Celery broker/backend | `redis://redis:6379/0` in Compose |
| `OLLAMA_BASE_URL` | Ollama address | `http://ollama:11434` in Compose |
| `OLLAMA_MODEL` | LLM for summaries | `llama3.2` |
| `WHISPER_MODEL` | Whisper model size | `small` |
| `WHISPER_DEVICE` | Inference device | `cpu` |
| `WHISPER_COMPUTE_TYPE` | Whisper precision | `int8` |
| `HF_TOKEN` | Optional Hugging Face model-download token | Empty by default |
| `WEBHOOK_SECRET` | Shared webhook secret | Replace example value |
| `MAX_UPLOAD_MB` | Maximum configured audio size | `200` |
| `BACKEND_PORT` | Published API port | `8000` |
| `FRONTEND_PORT` | Published UI port | `3000` |
| `NEXT_PUBLIC_API_BASE_URL` | Browser-visible API URL | `http://localhost:8000` |

**Configuration notes:** Use `http://ollama:11434` for container-to-container connections, but `http://localhost:11434` when the backend runs directly on your host. The browser-facing frontend API URL is normally `http://localhost:8000`. Never commit `.env` or access tokens. The default CPU Whisper setting is the simplest starting point; GPU use needs additional setup.

## Using the application

### Upload from the dashboard

1. Open <http://localhost:3000>.
2. Select **Upload recording** and choose a supported audio file.
3. The API creates a call and queues background processing.
4. Find the call in Recent Calls and open it to see the transcript and analysis.

Processing is asynchronous, so a new call initially shows `queued` or `processing`.

### Upload through the API

```powershell
curl.exe -X POST "http://localhost:8000/api/v1/calls/upload" `
  -F "file=@sample.wav" `
  -F "caller_name=Agent A" `
  -F "customer_name=Customer B"
```

Example response:

```json
{
  "id": 1,
  "status": "queued"
}
```

Use the returned ID to inspect the call:

```powershell
curl.exe "http://localhost:8000/api/v1/calls/1"
```

### Webhook integration

`POST /api/v1/webhooks/call-completed` accepts JSON such as:

```json
{
  "audio_url": "http://host.docker.internal:9000/recordings/call.wav",
  "caller_name": "Agent A",
  "customer_name": "Customer B",
  "external_call_id": "provider-call-123"
}
```

If `WEBHOOK_SECRET` is configured, send the matching value in the `X-Webhook-Secret` header. The audio URL must be reachable from the backend container. `host.docker.internal` can be used to reach a host service from Docker Desktop.

**Security warning:** The current webhook downloads a caller-supplied URL. Do not expose this endpoint publicly without strict destination allowlisting, network restrictions, and request authentication; otherwise it may be vulnerable to server-side request forgery (SSRF).

## API reference

Interactive API documentation: <http://localhost:8000/docs>

### `GET /health`

Returns a simple API health response. It does not guarantee that the worker or Ollama is ready.

### `POST /api/v1/calls/upload`

Content type: `multipart/form-data`.

| Field | Required | Description |
|---|---|---|
| `file` | Yes | WAV, MP3, M4A, OGG, or FLAC recording |
| `caller_name` | No | Display name; defaults to `Caller` |
| `customer_name` | No | Display name; defaults to `Customer` |

The current implementation reads the uploaded file into memory before saving it. Improve this to stream large uploads before production deployment.

### `POST /api/v1/webhooks/call-completed`

Accepts `audio_url`, `caller_name`, `customer_name`, and optional `external_call_id`. If configured, the shared secret is supplied in `X-Webhook-Secret`.

### `GET /api/v1/calls`

Query parameters:

- `search`: search caller name, customer name, summary, or transcript.
- `status`: optional `queued`, `processing`, `completed`, or `failed` filter.
- `limit`: number of records, capped at 100.
- `offset`: pagination offset.

Example:

```bash
curl "http://localhost:8000/api/v1/calls?status=completed&limit=20&offset=0"
```

### `GET /api/v1/calls/{call_id}`

Returns call details, transcript segments, summary, interest classification, topics, action items, score, and error information where available.

### `GET /api/v1/analytics/summary`

Returns total/completed/in-progress/failed counts, average score, customer-interest distribution, and per-caller call counts and average scores.

## Speech processing and summarization

### Faster-Whisper and Pyannote.audio

The default transcription model is `small`, configurable through `WHISPER_MODEL`. A smaller model such as `base` may be faster and use less memory, while larger models may improve accuracy at the cost of compute. Models are downloaded on first use and cached.

When Pyannote is available, speaker turns are matched to transcript segments by temporal overlap. **Current role mapping is heuristic:** the first detected speaker is labeled `Caller` and the second `Customer`. The code cannot know the real-world role from the audio alone. Reversed speaking order, transfers, multiple speakers, or overlapping speech can produce incorrect labels. Without Pyannote, the fallback uses one speaker and does not perform real diarization.

### Ollama structured summaries

The LLM is configured by `OLLAMA_MODEL` and `OLLAMA_BASE_URL`. The requested output contains:

```json
{
  "call_summary": "Short factual overview of the call",
  "customer_interest_level": "Medium",
  "key_topics": ["pricing", "product features"],
  "action_items": ["Send the customer product details"],
  "agent_performance_score": 7
}
```

The interest levels are `High`, `Medium`, and `Low`; the score is an AI-generated heuristic, not an objective measurement. Models can omit information or produce incorrect conclusions. Review outputs before making consequential decisions.

## Local development without Docker

This approach assumes PostgreSQL, Redis, and Ollama are already installed and running. Use Python 3.11 for the backend.

### Backend setup (PowerShell)

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Set host-accessible environment values, for example:

```text
DATABASE_URL=postgresql+asyncpg://callanalytics:YOUR_PASSWORD@localhost:5432/callanalytics
REDIS_URL=redis://localhost:6379/0
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
AUDIO_DIR=./data/audio
```

Create the PostgreSQL database/user first. From `backend/`, run the API:

```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

In a second terminal, activate the same virtual environment and start the worker:

```powershell
celery -A app.tasks.celery_tasks.celery_app worker --loglevel=INFO --pool=solo
```

### Frontend setup

In another terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000> and ensure `NEXT_PUBLIC_API_BASE_URL` points to `http://localhost:8000`.

## Troubleshooting

### `dockerDesktopLinuxEngine` pipe not found

Docker Desktop's Linux engine is unavailable. Start Docker Desktop and wait until it is running. Then check:

```powershell
wsl --status
wsl -l -v
wsl --update
docker context ls
docker version
```

### `image ... already exists` during image export

Try sequential builds:

```powershell
docker compose build backend
docker compose build worker
docker compose build frontend
docker compose up
```

If it continues, save the full error and inspect:

```powershell
docker compose ps -a
docker image ls call-analytics-free-backend
docker image ls call-analytics-free-worker
docker compose build worker
```

Do not delete volumes as a first response.

### `docker compose ps` shows no containers

If Compose failed during image building, containers may never have been created. Run:

```powershell
docker compose config --quiet
docker compose config --services
docker compose up --build
```

If startup exits, inspect `docker compose ps -a` and `docker compose logs --tail=100`.

### Backend cannot connect to PostgreSQL

- Check `docker compose ps` and `docker compose logs postgres backend`.
- In Compose, the database host must be `postgres`, not `localhost`.
- Check database name, username, and password.
- The MVP creates tables with SQLAlchemy `create_all`; use database migrations for production.

### Worker cannot connect to Redis

- Check `docker compose ps redis` and `docker compose logs redis worker`.
- Inside Compose, use `redis://redis:6379/0`.
- Ensure API and worker use the same Redis URL.

### Ollama model missing or not ready

- Check `docker compose logs ollama`.
- Wait for the initial model pull to finish.
- Confirm `OLLAMA_MODEL` is installed in Ollama.
- Use `http://ollama:11434` inside Compose and `http://localhost:11434` from the host.
- Confirm internet access and disk space for model downloads.

### Pyannote fails

Confirm model terms were accepted and `HF_TOKEN` is valid. Check worker logs. Without a working pipeline, the app falls back to one speaker.

### Frontend cannot reach the API

Check <http://localhost:8000/health>, verify `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`, and inspect browser developer tools plus `docker compose logs frontend backend`. Rebuild the frontend if changing build-time public configuration.

### Call remains queued or processing

Inspect:

```powershell
docker compose logs --tail=200 worker
docker compose logs --tail=100 redis
docker compose logs --tail=100 ollama
```

Check that the worker is running and can reach PostgreSQL, Redis, and Ollama. Initial model downloads and CPU inference can take time.

## Privacy and security

Recordings and transcripts may contain sensitive information. Before processing real calls:

- Obtain appropriate consent and authorization.
- Add authentication, authorization, and tenant isolation.
- Restrict webhook access to trusted callers and validate request signatures.
- Use destination allowlists and network restrictions for webhook downloads to prevent SSRF.
- Stream uploads, enforce limits, and validate file content rather than trusting extensions.
- Keep secrets out of source control and rotate credentials.
- Use TLS outside a trusted local environment.
- Define retention and deletion policies for audio, transcripts, and analysis.
- Protect persistent volumes and backups.
- Add audit logs, rate limits, monitoring, and alerts.
- Have a human review AI summaries and performance assessments before consequential decisions.

This scaffold is not a complete production security model. Do not expose it directly to the public internet.

## Limitations and future improvements

- Authentication, roles, and multi-tenant access control.
- Alembic migrations.
- Webhook signatures, idempotency, retry handling, and SSRF protections.
- Streaming uploads and robust audio validation.
- Reliable mapping of diarized speakers to actual caller/agent roles.
- Better support for overlapping speech and calls with more than two speakers.
- Improved Celery status tracking, retries, and failure recovery.
- API and frontend automated tests.
- Date-range analytics, audio playback, transcript timestamp navigation, and CSV/JSON exports.
- Retention controls and observability for latency, model resource use, and failures.
- Human review workflow for summaries and agent assessments.

## License

No project-specific license is included. Add a `LICENSE` file before distributing the repository and check the licenses and usage terms for all dependencies and pretrained models.
