# ERPNext integration

## Existing application and integration points

`backend/app/main.py` starts FastAPI and creates registered SQLAlchemy tables.
Upload and webhook routes create a `Call`, store audio in `AUDIO_DIR`, then queue
`process_call`. The Celery task transcribes through Faster-Whisper/diarization,
summarizes through Ollama, and commits all results on `calls`. There are no
separate transcript, summary, or action-item tables. Action items and topics are
JSON arrays of strings; transcript is plain text. `segments` contains diarization
data and is not exported in schema 1.0. Internal Caller/Customer rows are names,
not ERPNext identities. Existing routes have no general authentication; the
webhook has an optional shared secret. There was no existing test framework or
monitoring exporter; these tests use standard-library unittest and httpx mocks.

The integration adds:

```text
upload/webhook -> Celery transcription -> Ollama -> completed Call
                                              + pending erpnext_sync row
                                              -> one database commit
                                              -> separate Celery sync task
                                              -> authenticated ERPNext POST
                                              -> persisted outcome
Celery beat -> recovery scan -> missing outbox rows / due retries / expired leases
```

`erpnext_sync` is an additive table created by the existing `init_db()` mechanism.
No existing columns or dashboard contracts change. Start the API before workers
on a fresh database; workers do not create tables. A savepoint isolates an outbox
insertion failure: analysis can still commit, and recovery recreates the missing
row. Broker dispatch failures likewise leave durable work in PostgreSQL.
Synchronization never runs inside the transcription or LLM operations.

## Environment and enabling

Copy `.env.example` to `.env` and set values privately. No real credentials are
included in the example. These settings must match in API, workers, and beat.

| Variable | Default | Purpose |
| --- | --- | --- |
| `ERPNEXT_ENABLED` | `false` | Enable delivery and recovery; disabled needs no ERPNext credentials |
| `ERPNEXT_BASE_URL` | empty | Origin only, e.g. `https://erp.example.com`; no credentials, path, query, or fragment |
| `ERPNEXT_API_KEY` | empty | Dedicated Frappe integration user's API key |
| `ERPNEXT_API_SECRET` | empty | API secret, stored as a masked configuration value |
| `ERPNEXT_ANALYSIS_ENDPOINT` | `/api/method/call_analytics_integration.api.receive_call_analysis` | Custom receiving method path |
| `ERPNEXT_REQUEST_TIMEOUT` | `30` | Seconds, greater than 0 and at most 300; total HTTP deadline plus bounded connect/read/write/pool timeouts |
| `ERPNEXT_MAX_RETRIES` | `5` | Additional automatic attempts after the first; 0 through 20 |
| `ERPNEXT_ALLOW_HTTP` | `false` | Explicit trusted-development exception to HTTPS; keep false in production |
| `ERPNEXT_ADMIN_TOKEN` | empty | Separate high-entropy Bearer secret protecting the new admin API |

Enabled configuration is validated at API startup and Celery module initialization;
misconfiguration fails with `invalid_configuration` without displaying credentials.
Certificate verification remains enabled; redirects are rejected. Environment
HTTP proxy settings are intentionally ignored to keep credentials on the configured
connection. Use a trusted origin and restrict production outbound network access.

On ERPNext, create a dedicated user with only the permissions your custom receiving
method needs and generate its API key/secret. Requests use Frappe's
`Authorization: token API_KEY:API_SECRET` authentication. See the official
[Frappe REST API documentation](https://docs.frappe.io/framework/user/en/api/rest).
The integration assumes neither existence nor availability of your custom method.

For Docker, from the repository root:

```sh
docker compose up --build -d
```

The root Compose file now includes a separate beat service. For a non-Docker setup,
install `backend/requirements.txt`, set PostgreSQL/Redis/Ollama and audio settings
for your host, then run from `backend` in separate terminals:

```sh
uvicorn app.main:app --host 127.0.0.1 --port 8000
celery -A app.tasks.celery_tasks.celery_app worker --loglevel=INFO --pool=solo
celery -A app.tasks.celery_tasks.celery_app beat --loglevel=INFO
```

Run one beat scheduler, as required by
[Celery's periodic task guidance](https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html).
Recovery runs every 60 seconds in batches of 200. Keep it running even if initial
dispatch usually succeeds. A completed call backlog is automatically queued when
enabling integration, including calls completed while it was disabled. Review the
scope of that historical data before enabling delivery. Disabling and restarting
API/workers/beat stops new requests and recovery; durable rows remain for re-enabling.

For a trusted development ERPNext instance, an HTTP origin is allowed only with
`ERPNEXT_ALLOW_HTTP=true`. Prefer local HTTPS. Do not use production credentials on
an untrusted development connection.

## Version 1.0 JSON contract

The machine-readable schema is [erpnext-analysis.schema.json](erpnext-analysis.schema.json).
The representative body is [erpnext-analysis.example.json](erpnext-analysis.example.json).
Bodies have a maximum serialized UTF-8 size of 2 MiB. Unknown fields, non-finite
numbers, invalid enums, negative duration, and naive timestamps are rejected.
Timezone-aware timestamps are normalized to UTC. No values are inferred from
caller/customer names, transcript text, or local filenames.

| JSON field | Source / semantics |
| --- | --- |
| `schema_version` | Fixed string `1.0` |
| `call_id` | Original `Call.id` serialized as a string; stable on all retries |
| `recording_id` | Same internal ID; one recording per existing Call, no separate recording entity |
| `customer_reference`, `lead_reference`, `contact_reference`, `employee_reference` | Null; existing code has no ERPNext linkage |
| `call_datetime` | `Call.created_at`, ingestion time; actual telephony start time is not stored |
| `duration_seconds` | Existing duration or null; finite number >= 0 |
| `direction` | Null; existing model has no inbound/outbound information |
| `analysis_status` | Fixed `Completed`; only persisted completed calls qualify |
| `transcript` | Existing plain text transcript or null |
| `summary` | `Call.call_summary` or null |
| `customer_interest_level` | Existing `High`, `Medium`, `Low`, or null |
| `key_topics`, `action_items` | Existing string arrays; missing arrays become `[]` |
| `agent_performance_score` | Existing integer 1-10 or null |
| `recording` | Currently `{"storage_type":"local","object_key":null}` |
| `source_updated_at` | `Call.processed_at`; latest persisted analysis completion time |

The provider's optional `external_call_id` is not substituted for the internal ID.
The current schema intentionally has null-only CRM references because there is no
persisted verified mapping yet. Add an explicit mapping model and contract evolution
before populating them. The current application has no reanalysis API; if analysis
is changed externally after a row is synced, explicitly requeue it to deliver updates.

Sample request (substitute environment variables privately; never save expanded
credentials in shell history or logs):

```sh
curl --request POST "$ERPNEXT_BASE_URL$ERPNEXT_ANALYSIS_ENDPOINT" \
  --header "Authorization: token $ERPNEXT_API_KEY:$ERPNEXT_API_SECRET" \
  --header "Content-Type: application/json" \
  --data-binary @docs/erpnext-analysis.example.json
```

Required successful HTTP response: any 2xx with exactly the matching string ID and
acceptance status inside Frappe's `message` object:

```json
{"message":{"status":"accepted","call_id":"42"}}
```

Additional response keys are allowed. Acceptance must mean the receiver's durable
database transaction succeeded. A malformed JSON response, missing `message`, wrong
ID, or different status is a permanent protocol error requiring investigation and
manual retry. The connectivity check calls `frappe.auth.get_logged_user`; it verifies
authentication only, does not export the user identity, and explicitly reports
`analysis_endpoint_verified: false`.

## Required work in your Frappe app

You implement the authenticated, POST-only whitelisted method at the configured
endpoint. Do not allow guest access. Read the raw JSON body, validate schema version,
size and all fields, and perform an atomic create-or-update keyed by `call_id` with
a database unique constraint. Store or map the fields above to your custom call
analysis DocType and any child tables you choose for topics and action items.
Resolve null CRM references only through your explicit business rules; do not
require fabricated Customer, Lead, Contact, or Employee IDs from this client.

Repeated identical requests must return the same acceptance, creating one record.
Use `source_updated_at` to reject or ignore stale updates so a delayed old delivery
cannot overwrite newer analysis. Return acceptance for an already-applied request,
including one where the client timed out after your commit. Unique ID alone is not
enough unless concurrent upserts are also safe. This provides at-least-once delivery,
not distributed exactly-once semantics. A single source database should own the ID
namespace for this endpoint; independent analytics deployments need an agreed
source namespace before sharing it.

Return 400/422 for permanent validation problems, 401/403 for authentication or
permission failures, 429 for throttling, and appropriate 5xx for temporary outages.
Do not return 2xx before committing data. Implement recording access separately;
the local reference does not identify a playable remote recording.

## Durable delivery, retries and administration

Each sync row tracks call ID, pending/processing/synced/failed status, attempt count,
last attempt, sanitized last error, last success, next retry, HTTP category and a
leased attempt token. PostgreSQL row locks with `SKIP LOCKED` serialize claims;
the worker commits `processing` before making an HTTP request. Leases expire after
the configured request timeout plus 60 seconds. Fencing tokens stop an expired
worker from overwriting the outcome of a newer worker. The receiver must still
deduplicate requests when a response or worker is lost.

Network errors, timeouts, HTTP 408/429 and 500/502/503/504 retry at 30, 60, 120, ...
seconds, capped at 3600 seconds. Actual dispatch happens at the next recovery tick
and depends on worker availability. Other errors, including 401/403/400/422, redirects
and protocol validation failures, become failed immediately. Expired attempts count
toward the same retry budget. `Retry-After` is not interpreted. Duplicate queued jobs
are harmless: synced, unexpired processing, and not-yet-due records are skipped.

There is no existing application-wide authorization to reuse. The new routes require
a separately configured admin Bearer token; when absent, every route returns 503
before reading call data or doing HTTP work. Set a cryptographically random token,
serve this API over HTTPS, and grant it only to trusted operators. These new controls
do not add authentication to the application's pre-existing routes.

| Method and path (prefix `/api/v1/integrations/erpnext`) | Behavior |
| --- | --- |
| `GET /status` | Enabled flag and backlog counts/oldest pending age |
| `GET /status?check_connectivity=true` | Also perform safe authentication/connectivity check |
| `GET /calls/{call_id}` | Sync state and safe error code, or `not_queued` |
| `POST /calls/{call_id}/retry` | Reset retry-cycle attempt count and enqueue completed call; 202 after durable commit |

All require `Authorization: Bearer <ERPNEXT_ADMIN_TOKEN>`. Retry returns 409 for a
disabled integration, incomplete call, or active lease; unknown calls return 404.
Manual retries may also resend a synced call to repair remote data; idempotency
must still apply. Last successful timestamp is retained; attempt count measures the
current retry cycle. The HTTP category and last attempt continue to describe the
previous request until the next delivery. Failed rows do not auto-requeue forever.

## Logging, metrics and troubleshooting

Workers emit JSON log messages for attempt, success, retry, permanent failure,
dispatch deferral, outbox deferral and backlog. Fields include call ID, attempt,
HTTP response category and time since completion. Backlog gauges are computed from
durable state and are also exposed by the protected status API. Ship these logs to
your monitoring system for attempt/success/failure counters and latency trends;
there is no new metrics-exporter dependency. Credentials, request headers, full
payloads, remote response bodies and recording URLs are not logged.

- `invalid_configuration`: check all enabled settings, origin syntax and HTTPS;
  restart API, workers and beat after changing configuration.
- `http_401`/`http_403`: verify the dedicated user's key/secret and method permissions,
  then retry the call through the protected API.
- `http_400`/`http_422`/`invalid_payload`/`payload_too_large`: inspect the source call
  and receiver contract privately. Invalid source data is not silently truncated.
- `invalid_response`/`invalid_acknowledgement`: correct the receiving method's
  response shape and matching string ID, then requeue.
- `network_timeout`/`network_failure`/`http_429`/temporary 5xx: inspect DNS, trusted
  certificates, reachability and ERPNext availability. The database retains retries.
- Pending work that never advances: verify beat and workers run with the same enabled
  settings, the API created the table, and PostgreSQL/Redis are available. Recovery
  scans repair missed broker messages; exhausted crashes become failed.
- Sync failure does not change `Call.status`, transcript, summary or dashboard data.

## Recording storage boundary

Current upload and webhook ingestion write only local files. No S3 upload, permanent
public URL, audio bytes or filesystem path is sent. `recording_storage.py` is the
small reference adapter boundary. Future work must add private uploads, persisted
upload-completion metadata, verified bucket/object keys, an explicit export setting,
schema support for `storage_type: s3`, and authorized playback using short-lived
access. Merely setting an environment variable or recognizing a filename must not
turn a local recording into an S3 reference. No storage migration is included here.

## Tests

Normal automated tests require no live ERPNext, Redis, speech model or LLM:

```sh
cd backend
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
```

There was no pre-existing framework. Standard-library unittest covers mapping,
missing/invalid data, size, disabled/missing config, token headers, HTTP failures,
timeouts, acknowledgements, retry limits, restart recovery, stale-worker fencing,
admin access, manual retry, sanitization, and analysis surviving outbox/broker errors.
The normal durable-state harness uses a temporary SQLite file and a test-only UTC
adapter. It tests persisted state, not PostgreSQL row-lock semantics.

To test the same suite against real PostgreSQL, set `TEST_POSTGRES_URL` to an asyncpg
SQLAlchemy URL for a disposable test database. Tests create and drop randomized
schemas in that database; the user needs schema-creation privileges. This enables
the concurrency test. Do not use a production database.

Optional live receiver smoke test: set `ERPNEXT_RUN_LIVE_TEST=1`, all real enabled
ERPNext settings, and `ERPNEXT_LIVE_TEST_CALL_ID=test-<unique-synthetic-id>` before
running the suite. It writes the synthetic analysis twice, so use a test ERPNext
instance and inspect its database yourself to confirm one record. Automated mocks
simulate receiver upsert behavior; they do not prove your Frappe implementation.
The live smoke test checks authentication and acknowledgements, not remote record
counts, and is disabled by default.

Implementation-session result: 31 tests ran, 28 passed, 3 skipped (two real PostgreSQL
locking/concurrency tests and opt-in live ERPNext). Docker's engine was unavailable; no live
ERPNext, PostgreSQL-lock concurrency or full speech/LLM pipeline run was performed.
