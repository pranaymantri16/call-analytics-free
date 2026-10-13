# ERPNext setup guide for Call Analytics

This guide saves the setup steps from our conversation for reuse. It covers a
Frappe Cloud test receiver, a dashboard page, Postman checks, and connecting the
existing local analytics application. All credentials below are placeholders.

The example uses these names consistently:

| Item | Name |
| --- | --- |
| Test DocType | `Call Analysis Test - 2` |
| Integration role | `Call Analytics Integration` |
| Server Script | `Receive Call Analysis Test` |
| API Method | `receive_call_analysis_test` |
| Dashboard Workspace | `Call Analytics Test` |

Replace `https://YOUR-SITE.frappe.cloud` with your actual ERPNext origin throughout
this guide. A custom domain also works. Menu labels may vary with ERPNext version.

For the application's production architecture and full payload contract, see
[docs/erpnext-integration.md](docs/erpnext-integration.md). This guide's Server Script
is an initial sequential smoke-test receiver, not the final production Frappe app.

## 1. Check your Frappe Cloud bench

1. Open your Frappe Cloud dashboard and select your ERPNext site.
2. Check whether the site belongs to a private or shared bench group.
3. Server Scripts require a **private bench** on Frappe Cloud. Shared benches do not
   support this receiving-script approach.
4. If required, create a compatible private bench and move your test site to it,
   following Frappe Cloud's instructions. Review the applicable plan first.
5. Verify Server Scripts are enabled. Seeing the Server Script form or saving a
   script alone does not prove execution is enabled; the POST test below does.

Official references:

- [Enable Server Scripts](https://docs.frappe.io/cloud/enable-server-script)
- [Create a private bench](https://docs.frappe.io/cloud/benches/create-new)
- [Move a site to a private bench](https://docs.frappe.io/cloud/sites/move-site-to-private-bench)

Use the ERPNext browser interface for the steps below. Do not attempt to enable
developer mode on the Cloud site for this test. Standard app files belong in a
custom app deployed through your private bench.

## 2. Create the custom DocType

Log in to ERPNext as Administrator or a user allowed to manage DocTypes.

1. Click **Search** in the sidebar or use the top search bar.
2. Search **DocType**, open the list, and click **New**.
3. Set:
   - Name: `Call Analysis Test - 2`
   - Module: an available module such as CRM or Selling
   - Custom: checked
   - Is Single: unchecked
   - Is Child Table: unchecked
4. Open its Form builder or Fields tab.
5. Click **Add field**, then select the new field.
6. In the properties panel, enter **Label**, **Type**, and **Name**. In the form
   builder shown during setup, **Name is the fieldname**, such as `call_id`.
7. Add the fields listed below and click **Save**.

The record list's **Add Call Analysis Test** button creates a data record. To edit
the field definitions, open **DocType → Call Analysis Test - 2**.

| Label | Fieldname / Name | Type | Settings |
| --- | --- | --- | --- |
| Call ID | `call_id` | Data | Required, Unique, In List View |
| Recording ID | `recording_id` | Data | |
| Schema Version | `schema_version` | Data | |
| Call Date and Time | `call_datetime` | Datetime | In List View |
| Summary | `summary` | Long Text | |
| Transcript | `transcript` | Long Text | |
| Customer Interest | `customer_interest_level` | Select | In List View; options below |
| Agent Performance Score | `agent_performance_score` | Int | In List View |
| Duration in Seconds | `duration_seconds` | Float | |
| Source Updated At | `source_updated_at` | Data | Original ISO timestamp for this test |
| Last Received At | `last_received_at` | Datetime | |
| Received Payload | `payload_json` | Long Text | Complete received JSON |

For Customer Interest, enter one option per line in **Options**:

```text
High
Medium
Low
```

Check that generated fieldnames match the table exactly. Keep optional numeric
data unavailable when missing; do not deliberately replace it with zero. The raw
payload preserves nulls even if a numeric DocType field displays a default value.

If your DocType is named `Call Analysis Test` instead, change the `doctype` value
in the Server Script and select that same DocType in permissions and dashboard
settings. Do not mix the two names.

## 3. Configure role permissions

1. Search **Role → New**.
2. Create `Call Analytics Integration` and save.
3. Search **Role Permission Manager**.
4. Select DocType `Call Analysis Test - 2`.
5. Leave the existing System Manager rule in place.
6. Click **Add A New Rule**.
7. Select role `Call Analytics Integration` and permission level `0`.
8. In its new row, enable **Read**, **Create**, and **Write**.
9. Leave **Only If Creator** unchecked and the other permissions unchecked.
10. Ensure your dashboard operator's role also has Read access.

If the role is absent from the selector, create it first and reopen the permission
manager. Permissions apply to users through their assigned roles.

## 4. Create the integration user and API credentials

1. Search **User**, open the list, and click **New / Add User**.
2. Enter an email you control, for example `call-integration@yourcompany.com`.
3. First Name: `Call Analytics Integration`.
4. Enable the user and select **System User**, if shown.
5. Save.
6. Under **Roles / Roles & Permissions**, assign `Call Analytics Integration`.
7. Save again.
8. Find **API Access**, usually under **Settings**.
9. Click **Generate Keys**.
10. Save the API Key and API Secret privately. The secret is displayed when generated.

These are the integration user's ERPNext credentials. Do not put them in a
dashboard script, screenshot, chat message, or committed template.

ERPNext requests use:

```text
Authorization: token YOUR_API_KEY:YOUR_API_SECRET
```

Reference: [Frappe authentication](https://docs.frappe.io/framework-git/rest-api/authentication).

## 5. Prepare the local environment

Edit the existing repository-root **`.env`**. Preserve its PostgreSQL, Redis, Ollama,
and other existing settings. The root Docker Compose file loads `.env`.

`.env.example` is a shareable template. Keep its secret values empty; changing it
alone does not configure the running services. If you do not have `.env`, copy the
template once, then edit the private copy. Do not overwrite an existing `.env`.

Add these ERPNext settings to `.env`:

```dotenv
ERPNEXT_ENABLED=false
ERPNEXT_BASE_URL=https://YOUR-SITE.frappe.cloud
ERPNEXT_API_KEY=YOUR_API_KEY
ERPNEXT_API_SECRET=YOUR_API_SECRET
ERPNEXT_ANALYSIS_ENDPOINT=/api/method/receive_call_analysis_test
ERPNEXT_REQUEST_TIMEOUT=30
ERPNEXT_MAX_RETRIES=5
ERPNEXT_ALLOW_HTTP=false
ERPNEXT_ADMIN_TOKEN=YOUR_SEPARATE_RANDOM_ADMIN_TOKEN
```

Keep delivery disabled until the receiving API has passed the manual POST test.
Use only the origin in `ERPNEXT_BASE_URL`; the method path goes in the separate
endpoint setting.

Generate the admin token in PowerShell:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Paste the generated value into `ERPNEXT_ADMIN_TOKEN` in `.env`. It is a **separate
secret** for the local analytics status/retry API, not an ERPNext API credential.

| Destination | Authentication header |
| --- | --- |
| ERPNext API | `Authorization: token API_KEY:API_SECRET` |
| Local integration admin API | `Authorization: Bearer ERPNEXT_ADMIN_TOKEN` |

In `.env.example`, leave these empty:

```dotenv
ERPNEXT_API_KEY=
ERPNEXT_API_SECRET=
ERPNEXT_ADMIN_TOKEN=
```

If real credentials were committed, pushed, or shared, regenerate them and update
the private `.env`. Generate a replacement admin token if it was shared too.

## 6. Create the receiving Server Script

1. In ERPNext, search **Server Script → New**.
2. Set these values:

| Setting | Value |
| --- | --- |
| Name | `Receive Call Analysis Test` |
| Script Type | `API` |
| API Method | `receive_call_analysis_test` |
| Allow Guest | Unchecked |
| Disabled | Unchecked |
| Module (for export) | Can remain empty for this test |

3. Paste the script below into **Script**.
4. Replace `YOUR_INTEGRATION_USER_EMAIL` with the exact email of the user whose API
   keys you generated.
5. Confirm the DocType name matches your saved DocType.
6. Click **Save**.

Do not add imports; Server Scripts use Frappe's restricted execution environment.

```python
# Receiver for the initial integration test.
if frappe.session.user != "YOUR_INTEGRATION_USER_EMAIL":
    frappe.throw("Not permitted", frappe.PermissionError)

payload = dict(frappe.form_dict)
payload.pop("cmd", None)

if payload.get("schema_version") != "1.0":
    frappe.throw("Unsupported schema version")

if payload.get("analysis_status") != "Completed":
    frappe.throw("Only completed analyses are accepted")

call_id = payload.get("call_id")
if not isinstance(call_id, str) or not call_id or len(call_id) > 140:
    frappe.throw("Invalid call ID")

if len(json.dumps(payload).encode("utf-8")) > 2 * 1024 * 1024:
    frappe.throw("Payload too large")

if not payload.get("source_updated_at") or not payload.get("call_datetime"):
    frappe.throw("Required timestamps are missing")

incoming_time = frappe.utils.get_datetime(payload["source_updated_at"])
call_time = frappe.utils.get_datetime(payload["call_datetime"])

if not incoming_time or not incoming_time.tzinfo:
    frappe.throw("Source timestamp must include timezone")

if not call_time or not call_time.tzinfo:
    frappe.throw("Call timestamp must include timezone")

interest = payload.get("customer_interest_level")
if interest not in (None, "High", "Medium", "Low"):
    frappe.throw("Invalid interest level")

doctype = "Call Analysis Test - 2"
existing = frappe.db.exists(doctype, {"call_id": call_id})

if existing:
    doc = frappe.get_doc(doctype, existing)
else:
    doc = frappe.new_doc(doctype)
    doc.call_id = call_id

apply_update = True
if existing and doc.source_updated_at:
    previous_time = frappe.utils.get_datetime(doc.source_updated_at)
    if incoming_time < previous_time:
        apply_update = False

if apply_update:
    doc.recording_id = payload.get("recording_id")
    doc.schema_version = payload["schema_version"]
    doc.call_datetime = frappe.utils.convert_utc_to_system_timezone(
        call_time
    ).replace(tzinfo=None)
    doc.summary = payload.get("summary")
    doc.transcript = payload.get("transcript")
    doc.customer_interest_level = interest
    doc.agent_performance_score = payload.get("agent_performance_score")
    doc.duration_seconds = payload.get("duration_seconds")
    doc.source_updated_at = payload["source_updated_at"]
    doc.last_received_at = frappe.utils.now_datetime()
    doc.payload_json = json.dumps(payload, ensure_ascii=False)

    if existing:
        doc.save()
    else:
        doc.insert()

frappe.response["message"] = {
    "status": "accepted",
    "call_id": call_id
}
```

The endpoint becomes:

```text
https://YOUR-SITE.frappe.cloud/api/method/receive_call_analysis_test
```

Send **POST** requests. Frappe commits successful POST database writes at the end
of the request. The script does not bypass DocType permissions. Its email check
means the API keys must belong to that exact user.

References: [Server Scripts](https://docs.frappe.io/framework/user/en/desk/scripting/server-script),
[Script API](https://docs.frappe.io/framework/user/en/desk/scripting/script-api),
[database transactions](https://docs.frappe.io/framework/user/en/api/database).

## 7. Test authentication in Postman

Create a **GET** request:

```text
https://YOUR-SITE.frappe.cloud/api/method/frappe.auth.get_logged_user
```

Set Postman's Authorization tab to **No Auth** when entering the header manually,
so it does not add a second Authorization header. Under Headers, add:

| Key | Value |
| --- | --- |
| Authorization | `token YOUR_API_KEY:YOUR_API_SECRET` |
| Accept | `application/json` |

Click **Send**. Expected response:

```json
{"message":"your-integration-user-email"}
```

The returned email must match the user in your Server Script. Resolve authentication
errors before moving on. This checks credentials, not the receiving endpoint.

## 8. Send a sample analysis from Postman

Create a **POST** request:

```text
https://YOUR-SITE.frappe.cloud/api/method/receive_call_analysis_test
```

Use the ERPNext token Authorization header from the previous step and add:

```text
Content-Type: application/json
```

Choose **Body → raw → JSON**. Paste:

```json
{
  "schema_version": "1.0",
  "call_id": "test-001",
  "recording_id": "test-001",
  "customer_reference": null,
  "lead_reference": null,
  "contact_reference": null,
  "employee_reference": null,
  "call_datetime": "2026-10-13T06:00:00Z",
  "duration_seconds": 60,
  "direction": null,
  "analysis_status": "Completed",
  "transcript": "Customer requested pricing and a product demonstration.",
  "summary": "Customer requested a quotation.",
  "customer_interest_level": "High",
  "key_topics": ["Pricing", "Product demonstration"],
  "action_items": ["Send quotation"],
  "agent_performance_score": 8,
  "recording": {
    "storage_type": "local",
    "object_key": null
  },
  "source_updated_at": "2026-10-13T06:01:00Z"
}
```

Click **Send**. Expected successful response:

```json
{
  "message": {
    "status": "accepted",
    "call_id": "test-001"
  }
}
```

In ERPNext, search **Call Analysis Test - 2**, open its list, and inspect `test-001`.
Check the summary, transcript, interest, score and Received Payload.

Send the same POST again. There must still be **one record** with Call ID `test-001`.
For an update test, change the summary and advance `source_updated_at`, then send
again; the same record should update. Sending the older sample afterward should
not overwrite the newer analysis.

This is a sequential test. It does not establish production concurrency safety.

## 9. Create the dashboard test page

Use a **Workspace** as the first dashboard page.

1. Open an existing ERPNext workspace.
2. Select **New Workspace**, or **… → New**, depending on version.
3. Title: `Call Analytics Test`.
4. Choose an available module; select Workspace type if requested.
5. Keep access private for the first test, then create it.
6. Open **Edit** and add:
   - Heading: `Call Analytics Test`
   - Shortcut: `Call Analysis Test - 2`, List view
   - Quick List: `Call Analysis Test - 2`
7. Save and confirm that the received sample record is visible.

For a count card:

1. Search **Number Card → New**.
2. Label: `Received Calls`.
3. Type: `Document Type`.
4. Document Type: `Call Analysis Test - 2`.
5. Function: `Count`.
6. Save.
7. Add a Number Card block to your Workspace and select `Received Calls`.

With only the synthetic sample saved, the count should remain **1** after repeat
delivery. Other records increase that count normally. Add High-interest count,
average score, average duration and interest breakdown after this basic test.
Sharing workspaces can require the Workspace Manager role; viewers also need
permission to read the underlying DocType and cards.

Reference: [Workspaces](https://docs.frappe.io/framework/user/en/desk/navigation/workspace).

## 10. Enable delivery and start the local application

After the manual receiver test succeeds, change the private `.env`:

```dotenv
ERPNEXT_ENABLED=true
```

Confirm the other ERPNext values, especially the test method path. **Enabling
delivery also queues historical completed calls**, so use your test ERPNext site.

Start Docker Desktop and wait for its engine to be ready. In PowerShell, from the
repository root, start the full application:

```powershell
docker compose up --build -d
```

If the rest of the application is already running and you only need to recreate
the integration-related services after editing `.env`, use:

```powershell
docker compose up --build -d backend worker beat
```

Recreating services loads new environment values; a simple container restart does
not apply changes from an edited env file.

Check services:

```powershell
docker compose ps -a
```

Check recent startup errors:

```powershell
docker compose logs --tail=100 backend worker beat frontend
```

Open these default local URLs:

- Dashboard: <http://localhost:3000>
- Backend health: <http://localhost:8000/health>
- FastAPI documentation: <http://localhost:8000/docs>

The backend health endpoint should return `{"status":"ok"}`. Use the configured
ports instead if `BACKEND_PORT` or `FRONTEND_PORT` differ from their defaults.
Ollama/model startup can take time on the first run.

During the conversation, one check found only beat running and neither local
web port available. That was a point-in-time observation, not the current state.
Running beat alone does not serve the API, dashboard, or processing worker.

## 11. Verify connectivity from the application

In Postman, send:

```text
GET http://localhost:8000/api/v1/integrations/erpnext/status?check_connectivity=true
```

Header:

```text
Authorization: Bearer YOUR_ERPNEXT_ADMIN_TOKEN
```

Expected indicators:

```json
{
  "enabled": true,
  "connectivity": {
    "reachable": true,
    "authenticated": true,
    "analysis_endpoint_verified": false
  }
}
```

The response also includes backlog metrics. `analysis_endpoint_verified: false`
is expected: this check tests authentication, while actual delivery tests your
receiving method. The local health endpoint alone does not test ERPNext.

## 12. Verify a real analyzed call

1. Upload a recording through the existing local analytics dashboard.
2. Wait for its analysis status to become completed.
3. Note its original internal numeric call ID, for example `42`.
4. Check delivery in Postman with the same local Bearer admin header:

```text
GET http://localhost:8000/api/v1/integrations/erpnext/calls/42
```

Look for `"status":"synced"`. Then open the ERPNext test DocType list and find
the matching Call ID `42`. The existing analysis stays in the local application
even if ERPNext delivery fails.

The synthetic `test-001` record was posted directly to ERPNext. It is not an
internal local Call ID, so do not use it in the local integer-ID status routes.

To retry a failed completed call, send:

```text
POST http://localhost:8000/api/v1/integrations/erpnext/calls/42/retry
```

Use the same local Bearer header. Expected response is HTTP 202 with pending
status. Recheck status afterward. Repeating delivery should leave one ERPNext
record with that call ID.

## 13. API reference

| Location | Method and path | Authentication | Purpose |
| --- | --- | --- | --- |
| ERPNext | `GET /api/method/frappe.auth.get_logged_user` | ERPNext token | Check identity |
| ERPNext | `POST /api/method/receive_call_analysis_test` | ERPNext token | Receive test analysis |
| Local application | `GET /health` | None | Check API availability |
| Local application | `GET /api/v1/integrations/erpnext/status` | Admin Bearer | Settings flag and backlog counts |
| Local application | `GET /api/v1/integrations/erpnext/status?check_connectivity=true` | Admin Bearer | Also check ERPNext authentication |
| Local application | `GET /api/v1/integrations/erpnext/calls/{call_id}` | Admin Bearer | Inspect delivery state |
| Local application | `POST /api/v1/integrations/erpnext/calls/{call_id}/retry` | Admin Bearer | Requeue completed analysis |

Possible local sync states are pending, processing, synced and failed. A call with
no outbox row returns `not_queued`. The periodic beat recovery scan runs every
60 seconds, queues missing completed calls and dispatches due retries. Transient
network errors and eligible HTTP failures use bounded exponential backoff.

No incoming webhook from ERPNext to the local application is required. The local
worker initiates outbound requests to ERPNext, so a public URL for your local
FastAPI server is not needed for this test.

## 14. Troubleshooting

| Symptom | Check / action |
| --- | --- |
| Server Scripts disabled | Private bench and enabled execution; saving alone is insufficient |
| ERPNext authentication error | Enabled user, correct API key/secret and exact token header |
| `Not permitted` | Script email must match the user returned by get_logged_user |
| DocType permission error | Integration role assigned to user; Read/Create/Write at level 0 |
| DocType not found | Exact `Call Analysis Test - 2` spelling in script and saved DocType |
| Unknown field or missing values | Fieldnames must match the setup table, especially `payload_json` |
| Receiving method not found | Saved API Method, unchecked Disabled and matching endpoint setting |
| Record exists but dashboard is empty | Workspace filters, DocType read permission and refresh |
| Local port 8000/3000 unavailable | Docker engine, backend/frontend container state and startup logs |
| Only beat running | Start the full Compose stack, including backend, worker and frontend |
| Missing or invalid configuration | `.env`, enabled settings, HTTPS origin and service recreation |
| Local admin API returns 401 | Use the separate Bearer admin token, not ERPNext token credentials |
| Local admin API returns 503 | Configure a nonempty `ERPNEXT_ADMIN_TOKEN` and recreate backend |
| Retry returns 409 | Integration disabled, call incomplete, or delivery already has an active lease |
| Sync stays pending | Worker/beat running with matching settings; PostgreSQL/Redis available |
| Connectivity passes but delivery fails | Check actual receiving method, permissions and response shape |
| `invalid_acknowledgement` | Successful response must contain message.status=accepted and matching string call_id |
| `http_401`/`http_403` | Fix remote credentials or permissions, then manually requeue |
| `network_timeout`, `network_failure`, 429 or eligible 5xx | Check reachability, TLS and ERPNext availability; inspect retry state |

If sharing an error, provide the HTTP status and sanitized response message.
Remove credentials and customer transcript contents from shared output.

## 15. Fields for the later full ERPNext dashboard

The test stores the complete payload in `payload_json`. For a structured production
DocType, retain the core fields above and add:

| Fieldname | Type | Options / purpose |
| --- | --- | --- |
| `analysis_status` | Select | Completed |
| `direction` | Select | Blank, Inbound, Outbound |
| `customer_reference` | Link | Customer |
| `lead_reference` | Link | Lead |
| `contact_reference` | Link | Contact |
| `employee_reference` | Link | Employee, if installed |
| `key_topics` | Table | Child DocType `Call Analysis Topic` |
| `action_items` | Table | Child DocType `Call Analysis Action Item` |
| `recording_storage_type` | Select | local; reserve s3 for future support |
| `recording_object_key` | Data | Private uploaded object key, when supported |

Enable **Is Child Table** for the two child DocTypes:

- `Call Analysis Topic`: `topic` field, Data.
- `Call Analysis Action Item`: `action_item` field, Small Text.

Your receiver must map string arrays to child rows, for example
`["Pricing"]` becomes `[{"topic":"Pricing"}]`, and replace imported child rows
on updates rather than appending duplicate rows. Flatten `recording.storage_type`
and `recording.object_key` into their corresponding fields.

Suggested dashboard components:

| Component | Calculation |
| --- | --- |
| Total analyzed calls | Record count |
| Calls today | Count filtered by call_datetime |
| High-interest calls | Count where customer_interest_level is High |
| Average agent score | Average of available scores |
| Average duration | Average of available durations |
| Calls over time | Count grouped by date |
| Interest breakdown | Count grouped by interest level |
| Recent calls | Date, summary, interest, score and duration |

Current application limitations:

- CRM references and call direction are null because there is no persisted mapping.
- Agent/customer names are not included; an agent-wise dashboard requires a verified
  mapping or payload extension.
- call_datetime currently represents ingestion time, not a stored telephony start time.
- Recordings are local. No audio, local filesystem path or permanent public URL is
  exported; remote playback and private S3 uploads remain future work.
- Local sync failures/retry counts are not part of this analysis payload, so the
  receiver alone cannot show the local pending/failed backlog on ERPNext.

## 16. Production boundary and reusable checks

The Server Script above is intended for sequential initial tests. Before replacing
it with your production custom Frappe app, implement the full validation contract,
POST-only enforcement and atomic concurrent create-or-update with a unique call ID.
Use source_updated_at to prevent delayed older requests overwriting newer analysis,
and acknowledge only durable acceptance. A unique field prevents duplicate inserts
but does not by itself make concurrent updates safe.

The application defaults to the production method path:

```text
/api/method/call_analytics_integration.api.receive_call_analysis
```

When that app is ready and installed, set `ERPNEXT_ANALYSIS_ENDPOINT` to the new
method, verify it with Postman, and recreate backend/worker/beat. Keep the test
method until you deliberately retire the test setup.

To disable delivery, set `ERPNEXT_ENABLED=false` and recreate those services.
Durable sync rows remain and can resume when integration is enabled again.

Run the mocked application tests from `backend`:

```powershell
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
```

Normal tests do not need live ERPNext. PostgreSQL locking tests and live receiver
tests require explicit opt-in settings described in
[the integration documentation](docs/erpnext-integration.md#tests).

Initial end-to-end success checklist:

- [ ] Manual authentication returns the integration user's email.
- [ ] Sample POST returns accepted with the matching call ID.
- [ ] ERPNext contains the sample data.
- [ ] Repeated sample POST leaves one record for that call ID.
- [ ] Workspace shows the received record and correct count.
- [ ] Local API and dashboard are available.
- [ ] A real completed local call reaches synced status.
- [ ] ERPNext contains the matching internal call ID and analysis.

The user reported successful manual API execution during the conversation. This
guide does not claim independently verified live end-to-end synchronization; use
the checklist to record the outcome of each future setup.
