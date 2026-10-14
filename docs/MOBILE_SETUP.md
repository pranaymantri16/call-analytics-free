# Android APK → existing FastAPI → existing analytics → ERPNext

Mobile endpoints now live in the existing FastAPI app. Audio becomes a normal
`calls` row in the same PostgreSQL database and shared audio volume. The existing
`process_call` Celery task does STT/diarization, Ollama summary and ERPNext enqueue.
No new analytics engine or parallel standalone server is required.

## Start/rebuild

From `D:\call-analytics-free\call-analytics-free`, with Docker Desktop running:

```powershell
docker compose up -d --build backend worker beat
docker compose ps
```

This also starts their PostgreSQL/Redis/Ollama dependencies. Existing audio/database
volumes are reused. Do not run `docker compose down -v`. All three application
containers must have the updated code. Celery beat recovers durable pending uploads
after a Redis outage or interrupted API dispatch.

Your .env maps BACKEND_PORT=8000 and FRONTEND_PORT=3000. Port 3000 is the frontend;
mobile requests go directly to FastAPI on port 8000.

## Provision the installed APK

1. Install the APK, open it and copy its device ID from the dashboard.
2. Run on the PC:

```powershell
.\scripts\Register-MobileDevice.ps1 -DeviceId 'PASTE-APK-DEVICE-ID'
docker compose up -d --force-recreate backend worker beat
```

The script preserves existing .env settings and existing device tokens, creates a
random token for this device and enables mobile ingestion. Re-registering the same
ID rotates that token. It prints the new token once for you to enter in APK Settings.
Do not commit .env or share the token.

3. Find the PC's Wi-Fi IPv4 address with `ipconfig`. Enter the APK server URL as
   `http://<PC-WIFI-IP>:8000/` and enter the device token. For example, substitute
   your actual address; no IP is embedded in the APK.
4. Use Diagnostics > Test backend; it should say Connected.
5. Authorize the dedicated call-recording folder, check call-log permission and
   explicitly switch monitoring ON. Installation alone does not enable monitoring.
6. Make a new recorded call, wait for file stability and discovery. Once matched,
   the recording uploads automatically. Check the existing frontend's call list:
   queued → processing → completed; ERPNext sync follows the existing configuration.

The phone and PC must share Wi-Fi without client isolation. Phone `localhost`
points at the phone. Allow inbound TCP 8000 on the Windows Private firewall profile
for LocalSubnet; do not disable the firewall or open public router ports. Debug APK
supports trusted-LAN HTTP. Release APK requires trusted HTTPS.

## Contract and failure handling

- `GET /api/mobile/health`: authenticated database health.
- `POST /api/mobile/recordings`: multipart `audio` + JSON-string `metadata`,
  `Authorization: Bearer <token>`, `Idempotency-Key: device_id:recording_id`.
- `GET /api/mobile/recordings/{id}/status?device_id=<id>`: reflects the linked existing
  call status. The server recording ID is the existing integer Call ID as a string.
- The APK contract already matches these routes; a rebuild is not required to connect.
- Wrong token 401; wrong device 403; conflicting content/metadata 409; size limit
  413; invalid container 415; checksum/metadata error 422. Default backend audio
  limit is the existing MAX_UPLOAD_MB=200 setting.
- One transaction persists Call + receipt + pending dispatch intent. Unique
  device/recording/key constraints prevent duplicate calls from phone retries.
- Dispatch is at least once. PostgreSQL session advisory locks prevent concurrent
  execution for the same Call; completed mobile tasks skip replay. Existing ERPNext
  outbox/idempotency remains in place. After a crash during uncommitted analysis,
  transcription may restart; completed durable results are not rerun.
- API/broker failure after persistence leaves recoverable pending work. Beat retries
  broker outages with backoff and re-dispatches stale queued/processing mobile calls
  after 15 minutes. Do not disable beat when expecting recovery.
- A backend analysis failure is visible as failed in the existing frontend. Upload
  receipt and processing completion are distinct; inspect worker logs/configuration.
- No audio or phone metadata is written into new mobile diagnostic logs. Mobile
  metadata stays in `mobile_recordings.metadata_json` (actual number, contact name,
  direction, call timestamps, filename and checksum). Existing CRM fields that
  require real CRM references are not guessed from contact names or numbers.

The additive `mobile_recordings` table is registered through the project's existing
`init_db/create_all` initialization. Existing tables and yesterday's CRM schema
are not replaced. Take normal database backups before deployment.

## Verification

Integrated backend + existing ERPNext regression tests: **35 passed, 3 skipped**
in the initial SQLite test harness. The seven new upload tests cover upload-to-existing-Call mapping,
concurrent retry deduplication, auth/checksum/conflicts, processing status, broker
recovery, completed-task replay and the existing processing/CRM enqueue path.
AI responses and CRM sends in tests are mocked; no real customer data was processed.
The complete suite was subsequently executed inside the running backend container
against isolated PostgreSQL test schemas: **38 passed, 1 skipped** (39 total).
This includes real database row-lock concurrency and the new advisory-lock test.
The only skipped test is the opt-in live ERPNext test. No real CRM request was sent.
FastAPI `/health` returned 200 and all three mobile route paths were verified in
the live OpenAPI schema after backend/worker/beat rebuild and startup.
No devices are registered initially; ingestion remains disabled until provisioning.
Target phone/real Whisper/Ollama/ERPNext end-to-end test remains pending.
