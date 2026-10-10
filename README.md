# Call Analytics Free — local-first call intelligence

A local-first MVP for uploading call recordings, transcribing them with Faster-Whisper, optionally diarizing speakers with pyannote.audio, summarizing with Ollama, and viewing call analytics in Next.js.

## What “$0 recurring API cost” means
- Runtime inference is local: no paid transcription, LLM, database, or queue API.
- You still need a computer with enough CPU/RAM (and ideally a compatible GPU), disk space for models, and Docker.
- pyannote's pretrained diarization model may require a Hugging Face account/token and accepting the model terms before downloading. This is model-download authentication, not a hosted inference API. Set `HF_TOKEN`; if unavailable, the pipeline falls back to one-speaker labels.
- Ollama downloads `llama3.2` on first startup. Model downloads require internet once; afterwards inference is local.
- Only process calls you are authorized to record and analyze. Protect audio/transcripts and configure retention/access controls before production use.

## Architecture
- FastAPI: upload, webhook, calls, detail, analytics
- Celery + Redis: background processing
- Faster-Whisper: local transcription
- pyannote.audio: local diarization when configured
- Ollama: local JSON summary
- PostgreSQL: callers, customers, calls
- Next.js 14: dashboard and transcript detail

## Run with Docker Compose
1. Install Docker Desktop (Windows/macOS) or Docker Engine + Compose (Linux).
2. Copy `.env.example` to `.env` and edit values.
3. For pyannote, accept the terms for the selected model on Hugging Face and set `HF_TOKEN` in `.env`. If you do not want diarization yet, leave it blank.
4. From this directory:
   ```bash
   docker compose up --build
   ```
   First startup downloads containers and AI models and may take a while.
5. Open:
   - Dashboard: http://localhost:3000
   - API docs: http://localhost:8000/docs
   - Ollama: http://localhost:11434
6. Upload a WAV/MP3 using the dashboard or API:
   ```bash
   curl -X POST http://localhost:8000/api/v1/calls/upload \
     -F "file=@sample.wav" \
     -F "caller_name=Agent A" \
     -F "customer_name=Customer B"
   ```
   The response includes a call `id`. Processing runs in the Celery worker; refresh the dashboard to see the status.

## Webhook
`POST /api/v1/webhooks/call-completed` accepts JSON:
```json
{
  "audio_url": "http://host.docker.internal:9000/recordings/call.wav",
  "caller_name": "Agent A",
  "customer_name": "Customer B",
  "external_call_id": "provider-call-123"
}
```
The URL must be reachable from inside the backend container. This endpoint downloads the recording from the supplied URL, so only expose it to trusted systems; see security notes below. The webhook has a shared-secret option via `WEBHOOK_SECRET` and `X-Webhook-Secret`.

## Useful API routes
- `POST /api/v1/calls/upload` — multipart audio upload
- `POST /api/v1/webhooks/call-completed` — webhook with `audio_url`
- `GET /api/v1/calls?search=&status=&limit=50&offset=0`
- `GET /api/v1/calls/{call_id}`
- `GET /api/v1/analytics/summary`
- `GET /health`

## Configuration
See `.env.example`. `OLLAMA_BASE_URL=http://ollama:11434` is correct inside Compose. Do not use `localhost` between containers.

## Push to GitHub

Create an empty repository on GitHub without adding a README, license, or gitignore, then run these commands from this project directory. Replace `YOUR_USERNAME` with your GitHub username and adjust the repository name if needed.

```bash
git add .
git status
git diff --cached
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/call-analytics-free.git
git push -u origin main
```

If starting from a downloaded copy without a `.git` directory, run `git init` first. Before committing, review the staged files for credentials and private call data. The `.gitignore` excludes local `.env` files, dependencies, build output, recordings, runtime data, and model caches; `.env.example` and backend model source files remain tracked. Commit dependency lockfiles when generated.

## Local development without Docker
Run PostgreSQL, Redis, and Ollama yourself; install backend dependencies from `backend/requirements.txt`; start FastAPI and a Celery worker. For the frontend run `npm install && npm run dev` from `frontend/`. Set `DATABASE_URL`, `REDIS_URL`, and `OLLAMA_BASE_URL` to addresses reachable from your host.

## Production hardening checklist
- Add authentication/authorization, tenant isolation, audit logs, rate limits, and TLS.
- Add audio size/type limits, malware scanning, URL allowlists for webhook fetches, and request signatures.
- Configure a data retention policy and deletion workflow.
- Treat LLM scores as heuristic signals, not objective employee evaluations. Review scores with human oversight.
- Set resource limits and monitor model memory usage. CPU-only inference can be slow.


## Language and audio-format behavior

- The transcript remains in the spoken language (for example, Hindi, Hinglish, or English).
- Generated `call_summary`, `key_topics`, and `action_items` are instructed to be in English regardless of the source language. As with any local LLM, review output for accuracy.
- Uploads and webhooks accept common FFmpeg-decodable formats, including WAV, MP3, M4A, MP4, AAC, OGG, OPUS, FLAC, WMA, AIFF, AMR, WebM, MKV, MOV, and other listed extensions. Format support depends on the file containing a valid audio stream and FFmpeg being available.
- Before transcription and diarization, FFmpeg converts input audio to mono 16 kHz PCM WAV. This gives Faster-Whisper and pyannote a consistent input format. FFmpeg is installed in the backend Docker image.
- No application can decode literally every possible audio format. Unsupported codecs, corrupt files, or video containers without an audio stream will return a processing error.
