"""Persist debugging snapshots, without credentials, binary audio or raw exceptions."""
import hashlib
import json
import logging
import re
import uuid
from datetime import datetime
from pydantic import SecretStr
from sqlalchemy import update
from app.config import settings
from app.models.recording_audit import RecordingAudit

logger = logging.getLogger(__name__)
MAX_DETAILS_BYTES = 4 * 1024 * 1024
SENSITIVE_KEYS = {"authorization", "cookie", "setcookie", "apikey", "apisecret",
                  "token", "admintoken", "password", "secret", "accesstoken",
                  "refreshtoken", "webhooksecret", "databaseurl", "redisurl"}
SENSITIVE_KEYS.update({"exc", "traceback", "stacktrace", "stack", "exception"})


def redact(value, config=settings):
    """Preserve customer metadata/transcripts for admins, redact system credentials."""
    credentials = []
    for name, item in vars(config).items():
        if isinstance(item, SecretStr):
            credentials.append(item.get_secret_value())
        elif name in ("hf_token", "webhook_secret", "database_url", "redis_url") and item:
            credentials.append(str(item))
        elif name == "mobile_devices":
            credentials.extend(token.get_secret_value() for token in item.values())
    credentials = sorted({secret for secret in credentials if secret}, key=len, reverse=True)

    def clean(item, depth=0):
        if depth > 40:
            return "[MAX_DEPTH]"
        if isinstance(item, SecretStr):
            return "[REDACTED]"
        if isinstance(item, dict):
            result = {}
            for key, child in item.items():
                normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
                hidden = normalized in SENSITIVE_KEYS or normalized.endswith(("apikey", "apisecret", "password", "token", "secret"))
                result[clean(str(key), depth + 1)] = "[REDACTED]" if hidden else clean(child, depth + 1)
            return result
        if isinstance(item, (list, tuple)):
            return [clean(child, depth + 1) for child in item]
        if isinstance(item, datetime):
            return item.isoformat()
        if isinstance(item, bytes):
            return "[BINARY OMITTED]"
        if isinstance(item, str):
            for secret in credentials:
                item = item.replace(secret, "[REDACTED]")
            item = re.sub(r"(?i)\b(Bearer|token)\s+[A-Za-z0-9_:.+/=-]+", r"\1 [REDACTED]", item)
            item = re.sub(r'''(?i)(["']?(?:api[_-]?key|api[_-]?secret|password|access[_-]?token)["']?\s*[:=]\s*["']?)[^\s,"'}]+''',
                          r"\1[REDACTED]", item)
            # Strip URL credentials/query/fragment, including signed recording URLs.
            item = re.sub(r"https?://[^\s\"<>]+", lambda match: re.sub(
                r"(https?://)[^/@]+@", r"\1[REDACTED]@",
                match.group(0).split("?", 1)[0].split("#", 1)[0],
            ), item)
            return item
        if item is None or isinstance(item, (bool, int, float)):
            return item
        return "[UNSUPPORTED VALUE]"

    return clean(value)


def safe_details(details, config=settings):
    cleaned = redact(details, config)
    encoded = json.dumps(cleaned, ensure_ascii=False, allow_nan=False).encode("utf8")
    if len(encoded) <= MAX_DETAILS_BYTES:
        return cleaned
    return {"truncated": True, "original_bytes": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "preview": encoded[:128 * 1024].decode("utf8", errors="replace")}


async def record(db, *, stage, event, outcome, call_id=None, device_id=None,
                 recording_id=None, correlation_id=None, attempt=None, details=None, config=settings):
    """Join the caller's transaction; a logging failure must not break processing.

    Savepoint preserves already-pending domain writes. Caller commits the event
    with the domain state. Server logs receive IDs only, never the full snapshot.
    """
    try:
        row = RecordingAudit(
            call_id=call_id, device_id=device_id, recording_id=recording_id,
            correlation_id=correlation_id or str(uuid.uuid4()), stage=stage,
            event=event, outcome=outcome, attempt=attempt, details=safe_details(details or {}, config),
        )
        async with db.begin_nested():
            db.add(row)
            await db.flush()
        logger.info("recording_audit event=%s call_id=%s audit_id=%s", event, call_id, row.id)
        return row.id
    except Exception:
        logger.warning("recording_audit_write_failed event=%s call_id=%s", event, call_id)
        return None


def analysis_snapshot(call):
    return {"status": call.status, "transcript": call.transcript, "segments": call.segments,
            "summary": call.call_summary, "duration_seconds": call.duration_seconds,
            "customer_interest_level": call.customer_interest_level, "key_topics": call.key_topics,
            "action_items": call.action_items, "agent_performance_score": call.agent_performance_score,
            "processed_at": call.processed_at}


async def link_call(db, correlation_id, call_id):
    try:
        async with db.begin_nested():
            await db.execute(update(RecordingAudit).where(
                RecordingAudit.correlation_id == correlation_id, RecordingAudit.call_id.is_(None),
            ).values(call_id=call_id))
    except Exception:
        logger.warning("recording_audit_link_failed call_id=%s", call_id)
