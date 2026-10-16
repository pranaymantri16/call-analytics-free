"""Versioned contract and bounded ERPNext HTTP client. Remote errors are untrusted."""
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.services.recording_storage import RecordingReference, recording_reference

MAX_PAYLOAD_BYTES = 2 * 1024 * 1024


class IntegrationError(Exception):
    def __init__(self, code: str, retryable: bool = False, category: str = "local"):
        super().__init__(code)
        self.code, self.retryable, self.category = code, retryable, category


def validate_configuration(config):
    if not config.erpnext_enabled:
        return
    try:
        url = urlsplit(config.erpnext_base_url)
        url.port  # Validate malformed port/IPv6 syntax without echoing the URL.
    except ValueError:
        raise IntegrationError("invalid_configuration") from None
    endpoint = config.erpnext_analysis_endpoint
    key = config.erpnext_api_key.get_secret_value()
    secret = config.erpnext_api_secret.get_secret_value()
    invalid = (
        not url.hostname or url.username is not None or url.password is not None
        or url.query or url.fragment or url.path not in ("", "/")
        or any(ord(c) < 33 for c in config.erpnext_base_url)
        or url.scheme not in ("https", "http")
        or (url.scheme != "https" and not config.erpnext_allow_http)
        or not endpoint.startswith("/api/method/")
        or any(c in endpoint for c in ("?", "#", "\\", "%"))
        or any(ord(c) < 33 for c in endpoint)
        or ".." in endpoint or not key or not secret
        or any(c in key + secret for c in ("\r", "\n", ":"))
        or not 0 < config.erpnext_request_timeout <= 300
        or not 0 <= config.erpnext_max_retries <= 20
    )
    if invalid:
        raise IntegrationError("invalid_configuration")


class AnalysisPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    schema_version: Literal["1.0"] = "1.0"
    call_id: str
    recording_id: str
    customer_reference: None = None
    lead_reference: None = None
    contact_reference: None = None
    employee_reference: None = None
    call_datetime: datetime
    duration_seconds: float | None = Field(default=None, ge=0)
    direction: Literal["Inbound", "Outbound"] | None = None
    analysis_status: Literal["Completed"] = "Completed"
    transcript: str | None = None
    summary: str | None = None
    customer_interest_level: Literal["High", "Medium", "Low"] | None = None
    key_topics: list[str] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)
    agent_performance_score: int | None = Field(default=None, ge=1, le=10)
    recording: RecordingReference
    source_updated_at: datetime

    @field_validator("call_datetime", "source_updated_at")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timestamp must include timezone")
        return value.astimezone(timezone.utc)

    def wire(self):
        result = self.model_dump(mode="json")
        if len(json.dumps(result, ensure_ascii=False).encode("utf8")) > MAX_PAYLOAD_BYTES:
            raise IntegrationError("payload_too_large")
        return result


def build_payload(call):
    if call is None or call.status != "completed" or call.processed_at is None:
        raise IntegrationError("analysis_not_completed")
    try:
        payload = AnalysisPayload(
            call_id=str(call.id), recording_id=str(call.id),
            call_datetime=call.created_at, source_updated_at=call.processed_at,
            duration_seconds=call.duration_seconds, transcript=call.transcript,
            summary=call.call_summary, customer_interest_level=call.customer_interest_level,
            key_topics=call.key_topics if call.key_topics is not None else [],
            action_items=call.action_items if call.action_items is not None else [],
            agent_performance_score=call.agent_performance_score,
            recording=recording_reference(call),
        )
        return payload.wire()
    except IntegrationError:
        raise
    except Exception:
        # Pydantic errors may include transcript contents. Never retain them.
        raise IntegrationError("invalid_payload") from None


class ERPNextClient:
    def __init__(self, config, transport=None):
        validate_configuration(config)
        self.config, self.transport = config, transport
        self.last_response = None

    async def _request(self, method, endpoint, payload=None):
        self.last_response = None
        if not self.config.erpnext_enabled:
            raise IntegrationError("integration_disabled")
        headers = {"Authorization": "token " + self.config.erpnext_api_key.get_secret_value()
                   + ":" + self.config.erpnext_api_secret.get_secret_value()}
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.erpnext_request_timeout, connect=min(10, self.config.erpnext_request_timeout)),
                follow_redirects=False, transport=self.transport, trust_env=False,
            ) as client:
                response = await asyncio.wait_for(client.request(
                    method, self.config.erpnext_base_url.rstrip("/") + endpoint,
                    headers=headers, json=payload,
                ), timeout=self.config.erpnext_request_timeout)
        except (httpx.TimeoutException, TimeoutError):
            raise IntegrationError("network_timeout", True, "network") from None
        except httpx.RequestError:
            raise IntegrationError("network_failure", True, "network") from None
        # Capture the actual reply for the protected audit trail. Never retain headers.
        response_bytes = response.content
        if len(response_bytes) <= 128 * 1024:
            try:
                response_body = response.json()
            except ValueError:
                response_body = {"format": "non_json", "size_bytes": len(response_bytes),
                                 "sha256": hashlib.sha256(response_bytes).hexdigest()}
        else:
            response_body = {"omitted": "response_exceeds_128_KiB", "size_bytes": len(response_bytes),
                             "sha256": hashlib.sha256(response_bytes).hexdigest()}
        self.last_response = {"http_status": response.status_code, "body": response_body}
        category = f"{response.status_code // 100}xx"
        if not 200 <= response.status_code < 300:
            raise IntegrationError(f"http_{response.status_code}",
                                   response.status_code in (408, 429, 500, 502, 503, 504), category)
        try:
            if len(response.content) > MAX_PAYLOAD_BYTES:
                raise ValueError()
            data = response.json()
            if not isinstance(data, dict) or "message" not in data:
                raise ValueError()
            return data["message"]
        except (ValueError, TypeError):
            raise IntegrationError("invalid_response", False, category) from None

    async def send(self, payload):
        message = await self._request("POST", self.config.erpnext_analysis_endpoint, payload)
        if (not isinstance(message, dict) or message.get("status") != "accepted"
                or message.get("call_id") != payload["call_id"]):
            raise IntegrationError("invalid_acknowledgement", False, "2xx")

    async def health(self):
        message = await self._request("GET", "/api/method/frappe.auth.get_logged_user")
        if not isinstance(message, str) or not message or message == "Guest":
            raise IntegrationError("invalid_health_response", False, "2xx")
        return {"reachable": True, "authenticated": True,
                "analysis_endpoint_verified": False}
