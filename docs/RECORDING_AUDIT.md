# Recording audit trail: APK to CRM

Open **Recording audit trail** from the local dashboard or visit
<http://localhost:3000/audit>. Each call detail page also links to its filtered history.

## Start or update

1. Set a nonempty `ERPNEXT_ADMIN_TOKEN` in your private `.env`. The existing token
   for integration administration is reused; do not put it in `.env.example` or a
   `NEXT_PUBLIC_` variable.
2. From the repository root, run:

   ```powershell
   docker compose up --build -d backend worker beat frontend
   ```

3. Open the audit page, paste that token into **Admin token**, and choose
   **Save connection**. The backend verifies it before the browser saves it.
   It is remembered across refreshes, navigation and browser restarts on this
   browser profile, until you use **Change token** or **Forget saved token**
   (or clear the site's browser storage). An invalid replacement preserves the
   previous saved connection. It is stored in localStorage for this application
   origin and backend URL, not in source code or the database.
4. Upload from your APK as usual, then refresh the audit page. Optionally enable
   automatic refresh every 10 seconds.

The API creates an additive `recording_audit` table through the existing startup
`init_db()` mechanism. Start the API before workers on a fresh database. No existing
tables need column migrations. Logs persist in PostgreSQL across container restarts.

## What you can inspect

| Stage | Events and details |
| --- | --- |
| mobile | Received APK metadata, multipart filename/type, idempotency key, device/recording IDs; accepted storage checksum, byte count and relative filename; duplicate uploads; returned acknowledgement; rejected uploads and safe reasons |
| dispatch | Processing queue attempt, receipt reference, broker outcome and next retry time |
| analysis | Start, transcription text/segments/duration, completed summary/topics/actions/interest/score, or a safe failure code |
| crm | Outbox queueing, disabled integration, exact outgoing payload snapshot, endpoint path, attempt number, response status/body, elapsed time, error/retry time, exhausted retries and manual requeue |

The landing page groups history into one card per internal **Call ID**, with its
analysis status, summary, CRM state and event counts. Click a card to open
`/audit/calls/{call_id}` and inspect that call's full event history. Rejected uploads
with no accepted call are available through **Uploads without a call ID**.

Filter by internal **Call ID**, **Device ID**, APK **recording ID**, stage and outcome.
Device/recording filters include linked processing and CRM events, not just upload
events. Select **Inspect** to see full event JSON, and **Download event JSON** to
save an individual debugging snapshot locally. Call groups are paginated, 30 at a
time, ordered by newest call ID. Counts reflect events matching your filters.
Event summaries inside each call are paginated, 50
at a time; full bodies are loaded only when inspected. Turn off automatic refresh
to browse older pages.

Each upload has a correlation ID. Every CRM attempt has a separate correlation ID
shared by its request and result. Call ID joins the entire recording lifecycle.
CRM attempt numbers reset when an operator manually requeues, but older audit
events and correlation IDs remain available.

Use **Current call snapshot** after entering a Call ID to inspect current persisted
APK metadata, analysis and sync status. This also works for recordings created
before logging was installed. Historical requests/responses cannot be reconstructed:
the event history starts with this update and does not pretend older data was logged.

The outgoing payload intentionally follows the existing contract. For example, APK
phone/contact metadata may be visible on an incoming event but absent from the CRM
request. Logging makes that mapping inspectable; it does not add unsupported CRM
fields or change the payload schema.

## Access and redaction

All audit APIs require `Authorization: Bearer <ERPNEXT_ADMIN_TOKEN>`. Without a
configured token they return 503; invalid/missing credentials return 401. Responses
use `Cache-Control: no-store`. Customer phone numbers, contact names, transcripts
and analysis remain visible to authorized operators, so grant this token only to
people who should inspect that information. Downloaded JSON contains that data too.

Authorization headers, cookies, keys, passwords, known configured credentials,
remote traceback fields, binary audio and signed URL query strings are redacted
or omitted. Ordinary server logs contain only event IDs/types and call IDs, not
the full customer payload. No separate log file exposes the snapshots.

For valid supported payloads, the audit stores the complete structured data after
redaction. Bounds and intentional exclusions:

- APK metadata above its existing 16 KiB limit is rejected and not copied in full.
- Non-JSON invalid metadata has at most a 16 KiB preview, with credential redaction.
- An event above 4 MiB becomes an explicit truncation marker with redacted-data
  length, SHA-256 and a 128 KiB preview. Normal CRM payloads are limited to 2 MiB.
- CRM JSON replies up to 128 KiB are captured and redacted. Larger replies and
  non-JSON replies retain status, size and SHA-256 instead of the raw body.
- A timeout/network failure has no fabricated response body; inspect its error code.
- Analysis exceptions use a generic safe code in the audit; raw exception messages
  and stack traces are not copied into the audit snapshots.
- Authentication failures record a safe event, without the supplied token or body.
- Missing multipart fields and malformed multipart requests rejected by FastAPI
  before the endpoint executes are not recording events. Use HTTP access logs for
  those requests. Disabled mobile ingress does not retain request bodies.

The audit trail is a debugging history, not a tamper-evident compliance ledger.
Database administrators can still modify it. There is no automatic retention purge;
plan retention and backups according to your needs because full transcripts and
retries consume database space. Redaction is defense in depth, not a reason to send
credentials inside arbitrary customer text or metadata.

## Failure behavior

Accepted metadata and stored-file audit events participate in the application's
database transactions where possible. CRM requests are recorded with the durable
claim before HTTP delivery, and results with the resulting sync state. If a worker
dies during a request, the request event may have no matching result; later attempts
use a new correlation ID, and the existing lease recovery still applies.

Logging uses savepoints and safe warnings. An unavailable audit table does not turn
an otherwise valid upload into a failure; that event can be missing and a warning
is emitted. Database outages that prevent the main pipeline from committing still
affect the main pipeline normally. This is best-effort debugging history, not a
guarantee that every event survives every infrastructure failure.

## Protected APIs

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v1/recording-audit/groups` | One card per call; filters plus `before_call_id` pagination; includes separate unassigned-event count |
| GET | `/api/v1/recording-audit` | Event summaries; `call_id`, `device_id`, `recording_id`, `stage`, `outcome`, `limit`, `before_id` filters |
| GET | `/api/v1/recording-audit/events/{event_id}` | One event including redacted details |
| GET | `/api/v1/recording-audit/calls/{call_id}` | Current persisted metadata, analysis and CRM sync state |

The list response includes `next_before_id`; supply it as `before_id` for the next
older page. `limit` ranges from 1 through 100. The APIs are read-only. Existing
ERPNext retry administration remains under `/api/v1/integrations/erpnext`.
For groups use `next_before_call_id` as `before_call_id`. For uploads without a
call ID, use `unassigned=true` on the event-list endpoint.

## Browser regression check

With the frontend running and Microsoft Edge installed, optionally run:

```powershell
python -m pip install playwright
python frontend/tests/audit_browser_smoke.py
```

The test mocks every audit API response and uses a dummy token. It checks grouped
cards, call drill-down, remembered access after reload/navigation, rejected token
replacement and explicit forgetting, without touching real customer data.

## Tests

From `backend`:

```powershell
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
```

Tests cover incoming metadata and acknowledgements, rejected and duplicate uploads,
audit-store failures, API access/pagination/filtering, secret redaction and bounded
snapshots, outgoing payload identity, real HTTP response snapshots, timeouts and
separate retry history. Real ERPNext requests are mocked. Set `TEST_POSTGRES_URL`
to an isolated disposable asyncpg PostgreSQL URL to also validate database locks
and concurrency. See [ERPNext integration tests](erpnext-integration.md#tests).
