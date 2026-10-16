import json
import unittest
from pydantic import SecretStr
from app.config import Settings
from app.services.recording_audit import redact, safe_details, MAX_DETAILS_BYTES


class RedactionTests(unittest.TestCase):
    def test_secret_fields_credentials_urls_and_binary_are_removed(self):
        config = Settings(_env_file=None, erpnext_api_secret=SecretStr("private-crm-secret"),
                          erpnext_admin_token=SecretStr("private-admin-secret"),
                          mobile_devices={"test": SecretStr("private-device-secret")})
        original = {"metadata": {"phone_number": "+919876543210", "api_secret": "unknown-secret"},
                    "nested": [{"Authorization": "token anything:anything", "password": "hidden"}],
                    "body": "private-crm-secret private-admin-secret private-device-secret Bearer unknown-token",
                    "invalid_json": 'api_key="unknown-key"', "exc": "Traceback: internal server path",
                    "url": "https://user:password@example.test/recording?signature=hidden#secret",
                    "audio": b"audio-binary"}
        result = redact(original, config)
        encoded = json.dumps(result)
        for secret in ("private-crm-secret", "private-admin-secret", "private-device-secret", "unknown-secret",
                       "anything:anything", "unknown-token", "unknown-key", "signature=hidden", "user:password", "Traceback:"):
            self.assertNotIn(secret, encoded)
        self.assertEqual(result["metadata"]["phone_number"], original["metadata"]["phone_number"])
        self.assertEqual(result["audio"], "[BINARY OMITTED]")
        self.assertEqual(original["metadata"]["api_secret"], "unknown-secret")

    def test_large_snapshot_is_explicitly_marked_and_bounded(self):
        result = safe_details({"transcript": "x" * (MAX_DETAILS_BYTES + 1)})
        self.assertTrue(result["truncated"])
        self.assertGreater(result["original_bytes"], MAX_DETAILS_BYTES)
        self.assertEqual(len(result["sha256"]), 64)
        self.assertLess(len(json.dumps(result)), 140000)

    def test_supported_full_crm_payload_is_preserved(self):
        payload = {"call_id": "42", "transcript": "Normal customer conversation.",
                   "action_items": ["Send quotation"], "recording": {"storage_type": "local", "object_key": None}}
        self.assertEqual(safe_details(payload), payload)
