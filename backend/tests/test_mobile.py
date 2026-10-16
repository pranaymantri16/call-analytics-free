import asyncio
import hashlib
import json
import tempfile
import types
import unittest
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
import httpx
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import func, select, update, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.database import Base, get_db
from app.models import Call, MobileRecording, RecordingAudit
from app.api.mobile import router, settings
from app.services.mobile_dispatch import dispatch_recording, recover_mobile

AUDIO = b"RIFF" + (48).to_bytes(4, "little") + b"WAVEfmt " + b"\0" * 40


def metadata(audio=AUDIO):
    return dict(device_id="device-test", recording_id="recording-test", phone_number="+919876543210", contact_name="Test Contact", direction="incoming", call_start_timestamp="2026-10-14T06:35:30Z", call_duration_seconds=245, recording_duration_seconds=245, recording_creation_timestamp=None, recording_modification_timestamp="2026-10-14T06:39:35Z", original_filename="original.wav", proposed_filename="proposed.wav", match_status="matched", match_confidence=.95, timezone="UTC", upload_status="pending", sha256=hashlib.sha256(audio).hexdigest())


class MobileTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.pg_url = os.getenv("TEST_POSTGRES_URL")
        self.schema = "mobile_test_" + uuid.uuid4().hex
        self.engine = create_async_engine(self.pg_url or f"sqlite+aiosqlite:///{Path(self.temp.name) / 'test.db'}", connect_args={"server_settings": {"search_path": self.schema}} if self.pg_url else {})
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as connection:
            if self.pg_url:
                await connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
            await connection.run_sync(Base.metadata.create_all)
        self.app = FastAPI(); self.app.include_router(router)
        from app.api.recording_audit import router as audit_router
        self.app.include_router(audit_router)
        async def database():
            async with self.sessions() as db:
                yield db
        self.app.dependency_overrides[get_db] = database
        self.patches = [patch.object(settings, "mobile_enabled", True), patch.object(settings, "mobile_devices", {"device-test": SecretStr("test-only-token")}), patch.object(settings, "audio_dir", self.temp.name), patch("app.api.mobile.dispatch_recording", AsyncMock(return_value=True))]
        for item in self.patches:
            item.start()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        for item in reversed(self.patches):
            item.stop()
        if self.pg_url:
            async with self.engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        await self.engine.dispose()
        self.temp.cleanup()

    async def upload(self, data=None, audio=AUDIO, token="test-only-token"):
        return await self.client.post("/api/mobile/recordings", headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "device-test:recording-test"}, data={"metadata": json.dumps(data or metadata(audio))}, files={"audio": ("test.wav", audio, "audio/wav")})

    async def test_upload_creates_existing_call_and_retains_phone_metadata(self):
        response = await self.upload()
        self.assertEqual(response.status_code, 201, response.text)
        async with self.sessions() as db:
            receipt = (await db.execute(select(MobileRecording))).scalar_one()
            call = await db.get(Call, receipt.call_id)
            self.assertEqual(response.json()["server_recording_id"], str(call.id))
            self.assertEqual(receipt.metadata_json["phone_number"], metadata()["phone_number"])
            self.assertEqual(call.status, "queued")
            self.assertEqual(Path(call.audio_path).read_bytes(), AUDIO)

    async def test_response_loss_and_concurrent_retries_create_one_call(self):
        responses = await asyncio.gather(*[self.upload() for _ in range(4)])
        self.assertTrue(all(r.status_code == 201 for r in responses), [r.text for r in responses])
        self.assertEqual(len({r.json()["server_recording_id"] for r in responses}), 1)
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.count()).select_from(Call)), 1)
            self.assertEqual(await db.scalar(select(func.count()).select_from(MobileRecording)), 1)

    async def test_auth_scope_conflicts_and_checksum(self):
        self.assertEqual((await self.upload(token="wrong")).status_code, 401)
        wrong = metadata(); wrong["device_id"] = "wrong-device"
        self.assertEqual((await self.upload(data=wrong)).status_code, 403)
        wrong = metadata(); wrong["sha256"] = "0"*64
        self.assertEqual((await self.upload(data=wrong)).status_code, 422)
        self.assertEqual((await self.upload(audio=b"invalid")).status_code, 415)
        await self.upload()
        wrong = metadata(); wrong["phone_number"] = "+123"
        self.assertEqual((await self.upload(data=wrong)).status_code, 409)

    async def test_status_tracks_existing_analysis_call(self):
        response = await self.upload()
        async with self.sessions.begin() as db:
            await db.execute(update(Call).where(Call.id == int(response.json()["server_recording_id"])).values(status="completed"))
        response = await self.client.get("/api/mobile/recordings/recording-test/status?device_id=device-test", headers={"Authorization": "Bearer test-only-token"})
        self.assertEqual(response.json()["status"], "completed")
        response = await self.client.get("/api/mobile/recordings/recording-test/status?device_id=other", headers={"Authorization": "Bearer test-only-token"})
        self.assertEqual(response.status_code, 403)

    async def test_broker_outage_retains_durable_intent_and_recovery(self):
        await self.upload()
        async with self.sessions() as db:
            receipt = (await db.execute(select(MobileRecording))).scalar_one()
        def fail(cid, key):
            raise ConnectionError("Redis unavailable")
        self.assertFalse(await dispatch_recording(receipt.id, self.sessions, fail))
        async with self.sessions.begin() as db:
            await db.execute(update(MobileRecording).values(next_dispatch_at=datetime.now(timezone.utc)-timedelta(seconds=1)))
        events = []
        await recover_mobile(self.sessions, lambda cid, key: events.append((cid, key)))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0], receipt.call_id)
        self.assertFalse(await dispatch_recording(receipt.id, self.sessions, lambda cid, key: events.append((cid, key))))

    async def test_completed_task_redelivery_does_not_transcribe_or_send_crm(self):
        response = await self.upload()
        call_id = int(response.json()["server_recording_id"])
        async with self.sessions.begin() as db:
            await db.execute(update(Call).values(status="completed"))
        from app.tasks import celery_tasks
        stt = types.ModuleType("app.services.stt_service")
        stt.transcribe_and_diarize = lambda path: self.fail("Duplicate transcription")
        llm = types.ModuleType("app.services.llm_service")
        llm.summarize_call = AsyncMock(side_effect=AssertionError("Duplicate LLM"))
        with patch.dict("sys.modules", {stt.__name__: stt, llm.__name__: llm}), patch.object(celery_tasks, "AsyncSessionLocal", self.sessions), patch.object(celery_tasks, "enqueue") as enqueue:
            await celery_tasks._process_call_once(call_id)
            enqueue.assert_not_called()

    async def test_mobile_call_runs_existing_processing_and_crm_enqueue(self):
        response = await self.upload()
        call_id = int(response.json()["server_recording_id"])
        from app.tasks import celery_tasks
        stt = types.ModuleType("app.services.stt_service")
        stt.transcribe_and_diarize = lambda path: {"transcript": "Synthetic test transcript", "segments": [], "duration_seconds": 245}
        llm = types.ModuleType("app.services.llm_service")
        llm.summarize_call = AsyncMock(return_value={"call_summary": "Test summary", "customer_interest_level": "High", "key_topics": [], "action_items": [], "agent_performance_score": 8})
        with patch.dict("sys.modules", {stt.__name__: stt, llm.__name__: llm}), patch.object(celery_tasks, "AsyncSessionLocal", self.sessions), patch.object(celery_tasks, "enqueue") as enqueue:
            await celery_tasks._process_call_once(call_id)
            enqueue.assert_called_once_with(call_id)
        async with self.sessions() as db:
            call = await db.get(Call, call_id)
            self.assertEqual(call.status, "completed")
            self.assertEqual(call.call_summary, "Test summary")

    async def test_audit_preserves_metadata_ack_storage_and_rejected_upload(self):
        result = await self.upload()
        call_id = int(result.json()["server_recording_id"])
        async with self.sessions() as db:
            rows = (await db.execute(select(RecordingAudit).order_by(RecordingAudit.id))).scalars().all()
        self.assertEqual([row.event for row in rows], ["mobile_upload_received", "mobile_upload_stored", "mobile_acknowledgement"])
        self.assertTrue(all(row.call_id == call_id for row in rows))
        self.assertEqual(len({row.correlation_id for row in rows}), 1)
        self.assertEqual(rows[0].details["metadata"], metadata())
        self.assertEqual(rows[1].details["size_bytes"], len(AUDIO))
        self.assertTrue(rows[1].details["storage"]["relative_path"].startswith("mobile/"))
        self.assertEqual(rows[2].details["response"], result.json())
        bad = metadata(); bad["sha256"] = "0" * 64
        self.assertEqual((await self.upload(data=bad)).status_code, 422)
        async with self.sessions() as db:
            rejected = (await db.execute(select(RecordingAudit).where(RecordingAudit.event == "mobile_upload_rejected"))).scalar_one()
        self.assertEqual(rejected.details["reason"], "Checksum mismatch")
        self.assertEqual(rejected.details["validation"]["actual_sha256"], hashlib.sha256(AUDIO).hexdigest())
        self.assertEqual(rejected.details["validation"]["size_bytes"], len(AUDIO))
        self.assertIsNone(rejected.call_id)

    async def test_audit_records_auth_failure_without_credentials(self):
        await self.upload(token="wrong-super-secret")
        async with self.sessions() as db:
            rows = (await db.execute(select(RecordingAudit))).scalars().all()
        self.assertEqual([row.event for row in rows], ["mobile_auth_rejected"])
        self.assertNotIn("wrong-super-secret", json.dumps(rows[0].details))

    async def test_audit_duplicates_keep_distinct_upload_attempts(self):
        await self.upload()
        await self.upload()
        async with self.sessions() as db:
            rows = (await db.execute(select(RecordingAudit))).scalars().all()
        self.assertEqual(sum(row.event == "mobile_upload_received" for row in rows), 2)
        self.assertEqual(sum(row.event == "mobile_duplicate" for row in rows), 1)
        self.assertEqual(len({row.correlation_id for row in rows}), 2)

    async def test_audit_api_is_protected_paginated_and_has_current_snapshot(self):
        result = await self.upload()
        call_id = int(result.json()["server_recording_id"])
        root = "/api/v1/recording-audit"
        with patch.object(settings, "erpnext_admin_token", SecretStr("")):
            self.assertEqual((await self.client.get(root)).status_code, 503)
        with patch.object(settings, "erpnext_admin_token", SecretStr("admin-test")):
            for path in (root, root + "/events/1", root + f"/calls/{call_id}"):
                self.assertEqual((await self.client.get(path)).status_code, 401)
            headers = {"Authorization": "Bearer admin-test"}
            first = await self.client.get(root + "?limit=2", headers=headers)
            self.assertEqual(first.headers["cache-control"], "no-store")
            data = first.json()
            self.assertEqual(len(data["items"]), 2)
            self.assertNotIn("details", data["items"][0])
            second = (await self.client.get(root + f'?limit=2&before_id={data["next_before_id"]}', headers=headers)).json()
            self.assertFalse({row["id"] for row in data["items"]} & {row["id"] for row in second["items"]})
            event_id = data["items"][0]["id"]
            detail = (await self.client.get(root + f"/events/{event_id}", headers=headers)).json()
            self.assertEqual(detail["details"]["response"], result.json())
            snapshot = (await self.client.get(root + f"/calls/{call_id}", headers=headers)).json()
            self.assertEqual(snapshot["mobile_metadata"], metadata())
            self.assertIsNone(snapshot["crm_sync"])
            self.assertEqual((await self.client.get(root + "/events/99999", headers=headers)).status_code, 404)
            self.assertEqual((await self.client.get(root + "?limit=1000", headers=headers)).status_code, 422)

    async def test_audit_device_filter_includes_crm_and_analysis_events(self):
        result = await self.upload()
        call_id = int(result.json()["server_recording_id"])
        from app.services.recording_audit import record
        async with self.sessions() as db:
            await record(db, stage="crm", event="crm_result", outcome="success", call_id=call_id)
            await db.commit()
        with patch.object(settings, "erpnext_admin_token", SecretStr("admin-test")):
            headers = {"Authorization": "Bearer admin-test"}
            result = await self.client.get("/api/v1/recording-audit?device_id=device-test&recording_id=recording-test&stage=crm", headers=headers)
            self.assertEqual([row["event"] for row in result.json()["items"]], ["crm_result"])

    async def test_audit_invalid_metadata_redacts_nested_credentials(self):
        data = metadata(); data["api_secret"] = "do-not-store"
        self.assertEqual((await self.upload(data=data)).status_code, 422)
        async with self.sessions() as db:
            row = (await db.execute(select(RecordingAudit).where(RecordingAudit.event == "mobile_upload_received"))).scalar_one()
        self.assertEqual(row.details["metadata"]["api_secret"], "[REDACTED]")
        self.assertNotIn("do-not-store", json.dumps(row.details))

    async def test_upload_survives_audit_table_failure(self):
        async with self.engine.begin() as connection:
            await connection.run_sync(RecordingAudit.__table__.drop)
        with self.assertLogs("app.services.recording_audit", "WARNING"):
            result = await self.upload()
        self.assertEqual(result.status_code, 201, result.text)
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.count()).select_from(Call)), 1)

    async def test_audit_groups_one_row_per_call_and_keeps_unassigned_uploads(self):
        result = await self.upload()
        call_id = int(result.json()["server_recording_id"])
        await self.upload()
        bad = metadata(); bad["sha256"] = "0" * 64
        await self.upload(data=bad)
        root = "/api/v1/recording-audit"
        with patch.object(settings, "erpnext_admin_token", SecretStr("admin-test")):
            self.assertEqual((await self.client.get(root + "/groups")).status_code, 401)
            headers = {"Authorization": "Bearer admin-test"}
            response = await self.client.get(root + "/groups", headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.assertEqual(len(data["items"]), 1)
            self.assertEqual(data["items"][0]["call_id"], call_id)
            self.assertEqual(data["items"][0]["event_count"], 6)
            self.assertEqual(data["items"][0]["device_id"], "device-test")
            self.assertEqual(data["unassigned_count"], 2)
            self.assertNotIn("details", data["items"][0])
            failed = (await self.client.get(root + "/groups?outcome=failed", headers=headers)).json()
            self.assertEqual(failed["items"], [])
            self.assertEqual(failed["unassigned_count"], 1)
            orphaned = (await self.client.get(root + "?unassigned=true", headers=headers)).json()
            self.assertEqual(len(orphaned["items"]), 2)
            self.assertTrue(all(item["call_id"] is None for item in orphaned["items"]))
            before = (await self.client.get(root + f"/groups?before_call_id={call_id}", headers=headers)).json()
            self.assertEqual(before["items"], [])


@unittest.skipUnless(os.getenv("TEST_POSTGRES_URL"), "Real PostgreSQL required for advisory lock validation")
class ProcessingGuardPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_claim_is_rejected_and_lock_released(self):
        from app.services.processing_guard import processing_guard
        engine = create_async_engine(os.environ["TEST_POSTGRES_URL"])
        call_id = -int(uuid.uuid4().hex[:7], 16)
        try:
            async with processing_guard(engine, call_id) as first:
                self.assertTrue(first)
                async with processing_guard(engine, call_id) as second:
                    self.assertFalse(second)
            async with processing_guard(engine, call_id) as next_claim:
                self.assertTrue(next_claim)
        finally:
            await engine.dispose()
