import asyncio
import json
import os
import tempfile
import types
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import httpx
from pydantic import SecretStr
from sqlalchemy import DateTime, text
from sqlalchemy.types import TypeDecorator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.config import Settings
from app.database import Base
from app.models import Call, Caller, Customer, ERPNextSync
from app.services.erpnext import ERPNextClient, IntegrationError, build_payload, validate_configuration
from app.services.erpnext_sync import add_pending, sync_call, recover, sync_metrics


def config(**changes):
    values = dict(_env_file=None, erpnext_enabled=True, erpnext_base_url="https://erp.example.test",
                  erpnext_api_key=SecretStr("test-key"), erpnext_api_secret=SecretStr("test-secret"),
                  erpnext_max_retries=2, erpnext_request_timeout=1)
    values.update(changes)
    return Settings(**values)


def sample(**changes):
    data = dict(id=42, status="completed", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                processed_at=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
                external_call_id="provider-99", duration_seconds=42.5,
                transcript="Customer: please send a quote.", call_summary="Customer requested a quote.",
                key_topics=["Pricing"], action_items=["Send quote"], customer_interest_level="High",
                agent_performance_score=8, audio_path="C:/private/customer.wav")
    data.update(changes)
    return SimpleNamespace(**data)


class PayloadTests(unittest.TestCase):
    def test_mapping_and_local_storage_privacy(self):
        payload = build_payload(sample())
        self.assertEqual(payload["call_id"], "42")
        self.assertEqual(payload["recording_id"], "42")
        self.assertEqual(payload["summary"], "Customer requested a quote.")
        self.assertEqual(payload["action_items"], ["Send quote"])
        self.assertEqual(payload["transcript"], sample().transcript)
        self.assertEqual(payload["recording"], {"storage_type": "local", "object_key": None})
        self.assertEqual(payload["source_updated_at"], "2026-01-01T01:00:00Z")
        for key in ("customer_reference", "lead_reference", "contact_reference", "employee_reference", "direction"):
            self.assertIsNone(payload[key])
        self.assertNotIn("private", json.dumps(payload))
        self.assertNotIn("provider-99", json.dumps(payload))

    def test_missing_optionals(self):
        payload = build_payload(sample(transcript=None, call_summary=None, duration_seconds=None,
                                       key_topics=None, action_items=None, customer_interest_level=None,
                                       agent_performance_score=None))
        self.assertEqual(payload["key_topics"], [])
        self.assertEqual(payload["action_items"], [])
        self.assertIsNone(payload["duration_seconds"])

    def test_invalid_data_and_sanitization(self):
        for changes in ({"duration_seconds": -1}, {"duration_seconds": float("nan")},
                        {"duration_seconds": float("inf")}, {"agent_performance_score": 11},
                        {"agent_performance_score": True}, {"customer_interest_level": "SECRET"},
                        {"created_at": datetime(2026, 1, 1)}, {"key_topics": [7]},
                        {"action_items": [{"task": "SECRET"}]}):
            with self.subTest(changes=changes), self.assertRaises(IntegrationError) as error:
                build_payload(sample(**changes))
            self.assertEqual(str(error.exception), "invalid_payload")

    def test_size_and_completion(self):
        with self.assertRaisesRegex(IntegrationError, "payload_too_large"):
            build_payload(sample(transcript="x" * (2 * 1024 * 1024)))
        with self.assertRaisesRegex(IntegrationError, "analysis_not_completed"):
            build_payload(sample(status="processing"))

    def test_disabled_requires_no_credentials(self):
        validate_configuration(config(erpnext_enabled=False, erpnext_base_url="", erpnext_api_key=SecretStr("")))

    def test_configuration_validation(self):
        cases = [{"erpnext_api_key": SecretStr("")}, {"erpnext_api_secret": SecretStr("")},
                 {"erpnext_base_url": "http://erp.example.test"},
                 {"erpnext_base_url": "https://key:secret@example.test"},
                 {"erpnext_base_url": "https://example.test?secret=x"},
                 {"erpnext_base_url": "https://[broken"},
                 {"erpnext_analysis_endpoint": "https://evil.test"},
                 {"erpnext_analysis_endpoint": "/api/method/../other"},
                 {"erpnext_request_timeout": 0}, {"erpnext_max_retries": -1}]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaisesRegex(IntegrationError, "invalid_configuration"):
                validate_configuration(config(**changes))
        validate_configuration(config(erpnext_base_url="http://localhost:8000", erpnext_allow_http=True))


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_and_repeated_stable_identity(self):
        remote_records = {}
        def receive(request):
            self.assertEqual(request.headers["Authorization"], "token test-key:test-secret")
            self.assertTrue(str(request.url).endswith(config().erpnext_analysis_endpoint))
            payload = json.loads(request.content)
            remote_records[payload["call_id"]] = payload
            return httpx.Response(200, json={"message": {"status": "accepted", "call_id": payload["call_id"]}})
        client = ERPNextClient(config(), httpx.MockTransport(receive))
        await client.send(build_payload(sample()))
        await client.send(build_payload(sample()))
        self.assertEqual(len(remote_records), 1)  # Receiver contract simulation, not a live-server claim.

    async def test_http_errors_and_retry_categories(self):
        for code in (401, 403, 400, 422, 429, 500, 502, 503, 504, 501, 302):
            with self.subTest(code=code):
                client = ERPNextClient(config(), httpx.MockTransport(
                    lambda request: httpx.Response(code, text="test-secret private.wav remote traceback")))
                with self.assertRaises(IntegrationError) as error:
                    await client.send(build_payload(sample()))
                self.assertEqual(str(error.exception), f"http_{code}")
                self.assertEqual(error.exception.retryable, code in (429, 500, 502, 503, 504))

    async def test_timeout_and_network_failure(self):
        for exception, expected in ((httpx.ReadTimeout("secret"), "network_timeout"),
                                    (httpx.ConnectError("secret"), "network_failure")):
            def fail(request):
                raise exception
            with self.assertRaisesRegex(IntegrationError, expected):
                await ERPNextClient(config(), httpx.MockTransport(fail)).send(build_payload(sample()))

    async def test_total_request_deadline(self):
        async def slow(request):
            await asyncio.sleep(1)
            return httpx.Response(200, json={})
        with self.assertRaisesRegex(IntegrationError, "network_timeout"):
            await ERPNextClient(config(erpnext_request_timeout=.01), httpx.MockTransport(slow)).send(build_payload(sample()))

    async def test_invalid_acknowledgements(self):
        for data in ({}, {"message": "ok"}, {"message": {"status": "accepted", "call_id": "wrong"}},
                     {"message": {"status": "error", "call_id": "42"}}):
            with self.subTest(data=data), self.assertRaises(IntegrationError):
                await ERPNextClient(config(), httpx.MockTransport(lambda request: httpx.Response(200, json=data))).send(build_payload(sample()))
        with self.assertRaisesRegex(IntegrationError, "invalid_response"):
            await ERPNextClient(config(), httpx.MockTransport(lambda request: httpx.Response(200, text="not JSON"))).send(build_payload(sample()))

    async def test_health_does_not_claim_receiving_endpoint_verified(self):
        client = ERPNextClient(config(), httpx.MockTransport(lambda request: httpx.Response(200, json={"message": "integration@example.test"})))
        result = await client.health()
        self.assertFalse(result["analysis_endpoint_verified"])
        self.assertNotIn("integration@example.test", json.dumps(result))

    async def test_disabled_no_http(self):
        def forbidden(request):
            self.fail("Disabled integration sent HTTP")
        with self.assertRaisesRegex(IntegrationError, "integration_disabled"):
            await ERPNextClient(config(erpnext_enabled=False), httpx.MockTransport(forbidden)).send(build_payload(sample()))


# SQLite loses timezone metadata; adapt only the test harness, including aggregates.
class TestUTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def process_result_value(self, value, dialect):
        if dialect.name == "sqlite" and value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


for table in Base.metadata.tables.values():
    for column in table.columns:
        if isinstance(column.type, DateTime):
            column.type = TestUTCDateTime(timezone=True)


class DurableSyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.pg_url = os.getenv("TEST_POSTGRES_URL")
        self.schema = "erpnext_test_" + uuid.uuid4().hex
        self.url = self.pg_url or "sqlite+aiosqlite:///" + Path(self.temp.name, "outbox.db").as_posix()
        self.connect_args = {"server_settings": {"search_path": self.schema}} if self.pg_url else {}
        self.engine = create_async_engine(self.url, connect_args=self.connect_args)
        async with self.engine.begin() as connection:
            if self.pg_url:
                await connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.sessions() as db:
            db.add_all([Caller(id=1, name="Agent"), Customer(id=1, name="Customer")])
            await db.flush()
            values = vars(sample()) | {"caller_id": 1, "customer_id": 1}
            db.add(Call(**values))
            await add_pending(db, 42)
            await db.commit()

    async def asyncTearDown(self):
        if self.pg_url:
            async with self.engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        await self.engine.dispose()
        self.temp.cleanup()

    async def row(self):
        async with self.sessions() as db:
            return await db.get(ERPNextSync, 42)

    def client(self, code=200):
        def respond(request):
            return httpx.Response(code, json={"message": {"status": "accepted", "call_id": "42"}})
        return ERPNextClient(config(), httpx.MockTransport(respond))

    async def test_success_skips_duplicate_queued_jobs(self):
        client = SimpleNamespace(send=AsyncMock())
        await sync_call(42, self.sessions, config(), client)
        await sync_call(42, self.sessions, config(), client)
        self.assertEqual(client.send.await_count, 1)
        row = await self.row()
        self.assertEqual(row.status, "synced")
        self.assertEqual(row.attempt_count, 1)
        self.assertIsNotNone(row.last_success_at)

    async def test_auth_failure_is_permanent(self):
        await sync_call(42, self.sessions, config(), self.client(401))
        row = await self.row()
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.last_error, "http_401")
        self.assertIsNone(row.next_retry_at)

    async def test_transient_failure_persists_due_time_and_backoff_limit(self):
        for attempt in range(1, 4):
            await sync_call(42, self.sessions, config(), self.client(429))
            row = await self.row()
            self.assertEqual(row.attempt_count, attempt)
            self.assertEqual(row.status, "pending" if attempt < 3 else "failed")
            if attempt < 3:
                self.assertAlmostEqual((row.next_retry_at - row.last_attempt_at).total_seconds(), 30 * 2 ** (attempt - 1), delta=2)
                async with self.sessions() as db:
                    row = await db.get(ERPNextSync, 42)
                    row.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                    await db.commit()

    async def test_timeout_and_5xx_preserve_completed_analysis(self):
        for failure in (IntegrationError("network_timeout", True, "network"), IntegrationError("http_503", True, "5xx")):
            async with self.sessions() as db:
                row = await db.get(ERPNextSync, 42)
                row.status, row.next_retry_at = "pending", datetime.now(timezone.utc)
                await db.commit()
            client = SimpleNamespace(send=AsyncMock(side_effect=failure))
            await sync_call(42, self.sessions, config(), client)
            self.assertEqual((await self.row()).status, "pending")
            async with self.sessions() as db:
                call = await db.get(Call, 42)
                self.assertEqual(call.status, "completed")
                self.assertEqual(call.transcript, sample().transcript)

    async def test_restart_recovery_and_due_time(self):
        await sync_call(42, self.sessions, config(), self.client(503))
        await self.engine.dispose()
        self.engine = create_async_engine(self.url, connect_args=self.connect_args)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        jobs = []
        await recover(self.sessions, jobs.append, config())
        self.assertEqual(jobs, [])  # Not due yet after restart.
        async with self.sessions() as db:
            row = await db.get(ERPNextSync, 42)
            row.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await db.commit()
        await recover(self.sessions, jobs.append, config())
        self.assertEqual(jobs, [42])
        await sync_call(42, self.sessions, config(), self.client())
        self.assertEqual((await self.row()).status, "synced")

    async def test_expired_processing_lease_is_recovered(self):
        async with self.sessions() as db:
            row = await db.get(ERPNextSync, 42)
            row.status, row.attempt_count = "processing", 1
            row.lease_token = "crashed-worker"
            row.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
            await db.commit()
        await sync_call(42, self.sessions, config(), self.client())
        self.assertEqual((await self.row()).status, "synced")
        self.assertEqual((await self.row()).attempt_count, 2)

    async def test_unexpired_lease_and_exhausted_crashes(self):
        async with self.sessions() as db:
            row = await db.get(ERPNextSync, 42)
            row.status, row.attempt_count = "processing", 3
            row.lease_until = datetime.now(timezone.utc) + timedelta(seconds=60)
            await db.commit()
        client = SimpleNamespace(send=AsyncMock())
        await sync_call(42, self.sessions, config(), client)
        client.send.assert_not_awaited()
        async with self.sessions() as db:
            row = await db.get(ERPNextSync, 42)
            row.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
            await db.commit()
        await sync_call(42, self.sessions, config(), client)
        self.assertEqual((await self.row()).status, "failed")

    async def test_reconciliation_missing_outbox_and_disabled(self):
        async with self.sessions() as db:
            row = await db.get(ERPNextSync, 42)
            await db.delete(row)
            await db.commit()
        jobs = []
        await recover(self.sessions, jobs.append, config(erpnext_enabled=False))
        self.assertIsNone(await self.row())
        await recover(self.sessions, jobs.append, config())
        self.assertEqual(jobs, [42])
        self.assertEqual((await self.row()).status, "pending")

    async def test_disabled_sync_no_attempt(self):
        await sync_call(42, self.sessions, config(erpnext_enabled=False), self.client())
        self.assertEqual((await self.row()).attempt_count, 0)

    async def test_invalid_persisted_data_does_not_send(self):
        async with self.sessions() as db:
            call = await db.get(Call, 42)
            call.duration_seconds = -1
            await db.commit()
        client = SimpleNamespace(send=AsyncMock())
        await sync_call(42, self.sessions, config(), client)
        client.send.assert_not_awaited()
        self.assertEqual((await self.row()).last_error, "invalid_payload")

    async def test_stale_worker_cannot_overwrite_new_delivery(self):
        started, finish = asyncio.Event(), asyncio.Event()
        async def old_send(payload):
            started.set()
            await finish.wait()
            raise IntegrationError("http_503", True, "5xx")
        old = asyncio.create_task(sync_call(42, self.sessions, config(), SimpleNamespace(send=AsyncMock(side_effect=old_send))))
        await started.wait()
        async with self.sessions() as db:
            row = await db.get(ERPNextSync, 42)
            row.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
            await db.commit()
        await sync_call(42, self.sessions, config(), self.client())
        finish.set()
        await old
        self.assertEqual((await self.row()).status, "synced")
        self.assertIsNone((await self.row()).last_error)

    async def test_protected_admin_routes_and_manual_requeue(self):
        from fastapi import FastAPI
        from app.api import erpnext as api
        from app.database import get_db
        app = FastAPI()
        app.include_router(api.router)
        async def database():
            async with self.sessions() as db:
                yield db
        app.dependency_overrides[get_db] = database
        root = "/api/v1/integrations/erpnext"
        admin_config = config(erpnext_admin_token=SecretStr("admin-test"))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            with patch.object(api, "settings", config(erpnext_admin_token=SecretStr(""))):
                self.assertEqual((await client.get(root + "/status")).status_code, 503)
            with patch.object(api, "settings", admin_config), patch.object(api, "enqueue") as dispatch:
                self.assertEqual((await client.get(root + "/status")).status_code, 401)
                self.assertEqual((await client.get(root + "/status", headers={"Authorization": "Bearer wrong"})).status_code, 401)
                client.headers["Authorization"] = "Bearer admin-test"
                response = await client.get(root + "/status")
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("test-secret", response.text)
                self.assertEqual((await client.get(root + "/calls/42")).json()["status"], "pending")
                self.assertEqual((await client.get(root + "/calls/999")).status_code, 404)
                await sync_call(42, self.sessions, config(), self.client(401))
                response = await client.post(root + "/calls/42/retry")
                self.assertEqual(response.status_code, 202)
                self.assertEqual((await self.row()).attempt_count, 0)
                dispatch.assert_called_once_with(42)
                async with self.sessions() as db:
                    row = await db.get(ERPNextSync, 42)
                    row.status, row.lease_until = "processing", datetime.now(timezone.utc) + timedelta(seconds=60)
                    await db.commit()
                self.assertEqual((await client.post(root + "/calls/42/retry")).status_code, 409)
            with patch.object(api, "settings", config(erpnext_enabled=False, erpnext_admin_token=SecretStr("admin-test"))):
                self.assertEqual((await client.post(root + "/calls/42/retry")).status_code, 409)

    async def test_sanitized_error_logs_and_metrics(self):
        with self.assertLogs("app.services.erpnext_sync", "INFO") as logs:
            await sync_call(42, self.sessions, config(), SimpleNamespace(send=AsyncMock(side_effect=RuntimeError("test-secret private.wav"))))
        self.assertNotIn("test-secret", str(logs.output))
        self.assertNotIn("private.wav", str([record.__dict__ for record in logs.records]))
        self.assertEqual((await self.row()).last_error, "internal_sync_failure")
        async with self.sessions() as db:
            self.assertEqual((await sync_metrics(db))["failed"], 1)

    async def test_analysis_commit_survives_outbox_and_broker_failure(self):
        from app.tasks import celery_tasks as tasks
        stt = types.ModuleType("app.services.stt_service")
        stt.transcribe_and_diarize = lambda path: {"transcript": "fresh transcript", "segments": [], "duration_seconds": 10.0}
        llm = types.ModuleType("app.services.llm_service")
        llm.summarize_call = AsyncMock(return_value={"call_summary": "fresh summary", "key_topics": [],
            "action_items": [], "customer_interest_level": "Medium", "agent_performance_score": 7})
        async with self.sessions() as db:
            row = await db.get(ERPNextSync, 42)
            await db.delete(row)
            await db.commit()
        with patch.dict("sys.modules", {stt.__name__: stt, llm.__name__: llm}), \
             patch.object(tasks, "settings", config()), patch.object(tasks, "AsyncSessionLocal", self.sessions), \
             patch.object(tasks, "engine", self.engine), patch.object(tasks, "add_pending", AsyncMock(side_effect=RuntimeError("secret"))):
            await tasks._process_call_async(42)
        async with self.sessions() as db:
            call = await db.get(Call, 42)
            self.assertEqual(call.status, "completed")
            self.assertEqual(call.call_summary, "fresh summary")
        jobs = []
        await recover(self.sessions, jobs.append, config())
        self.assertEqual(jobs, [42])
        from app.services import erpnext_sync
        with patch.object(erpnext_sync, "settings", config()), patch.object(tasks.sync_erpnext, "delay", side_effect=RuntimeError("secret")):
            erpnext_sync.enqueue(42)
        self.assertEqual((await self.row()).status, "pending")

    async def test_processing_commits_analysis_and_outbox_before_dispatch(self):
        from app.tasks import celery_tasks as tasks
        stt = types.ModuleType("app.services.stt_service")
        stt.transcribe_and_diarize = lambda path: {"transcript": "new transcript", "segments": [], "duration_seconds": 10.0}
        llm = types.ModuleType("app.services.llm_service")
        llm.summarize_call = AsyncMock(return_value={"call_summary": "new summary", "key_topics": [],
            "action_items": [], "customer_interest_level": "Medium", "agent_performance_score": 7})
        # Hold dispatch until the function returns, then inspect the durable commit.
        with patch.dict("sys.modules", {stt.__name__: stt, llm.__name__: llm}), \
             patch.object(tasks, "settings", config()), patch.object(tasks, "AsyncSessionLocal", self.sessions), \
             patch.object(tasks, "engine", self.engine), patch.object(tasks, "enqueue") as dispatch:
            await tasks._process_call_async(42)
            dispatch.assert_called_once_with(42)
        async with self.sessions() as db:
            call = await db.get(Call, 42)
            self.assertEqual(call.status, "completed")
            self.assertEqual(call.call_summary, "new summary")
            self.assertEqual((await db.get(ERPNextSync, 42)).status, "pending")

    async def test_database_row_lock_skips_an_in_progress_claim(self):
        if not self.pg_url:
            self.skipTest("Real PostgreSQL required for SKIP LOCKED")
        from sqlalchemy import select
        async with self.sessions() as first:
            await first.execute(select(ERPNextSync).where(ERPNextSync.call_id == 42).with_for_update())
            client = SimpleNamespace(send=AsyncMock())
            await sync_call(42, self.sessions, config(), client)
            client.send.assert_not_awaited()

    @unittest.skipUnless(os.getenv("TEST_POSTGRES_URL"), "Real PostgreSQL required for row-lock concurrency")
    async def test_concurrent_workers_claim_once(self):
        started, finish = asyncio.Event(), asyncio.Event()
        async def send(payload):
            started.set()
            await finish.wait()
        client = SimpleNamespace(send=AsyncMock(side_effect=send))
        first = asyncio.create_task(sync_call(42, self.sessions, config(), client))
        await started.wait()
        await sync_call(42, self.sessions, config(), client)
        finish.set()
        await first
        self.assertEqual(client.send.await_count, 1)


class OptionalLiveTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(os.getenv("ERPNEXT_RUN_LIVE_TEST") == "1", "Live ERPNext test explicitly opt-in")
    async def test_live_connectivity_and_idempotent_receiving_endpoint(self):
        live = Settings()
        self.assertTrue(live.erpnext_enabled)
        client = ERPNextClient(live)
        await client.health()
        # Requires explicit synthetic ID to avoid overwriting a real call.
        synthetic_id = os.getenv("ERPNEXT_LIVE_TEST_CALL_ID")
        self.assertTrue(synthetic_id and synthetic_id.startswith("test-"))
        payload = build_payload(sample())
        payload["call_id"] = payload["recording_id"] = synthetic_id
        await client.send(payload)
        await client.send(payload)


if __name__ == "__main__":
    unittest.main()
