"""Optional UI smoke test: pip install playwright; requires installed Edge and running frontend.

All audit HTTP responses are mocked. No real credentials/customer data are used.
Run: python frontend/tests/audit_browser_smoke.py
"""
import json
import os
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect

BASE = os.getenv("AUDIT_UI_URL", "http://localhost:3000")
TOKEN = "browser-test-only-token"
KEY = "call-analytics.audit-token:http://localhost:8000"


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context()
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def respond(route):
            request = route.request
            headers = {"Access-Control-Allow-Origin": BASE, "Access-Control-Allow-Headers": "authorization,content-type",
                       "Access-Control-Allow-Methods": "GET,OPTIONS"}
            if request.method == "OPTIONS":
                route.fulfill(status=204, headers=headers)
                return
            if request.headers.get("authorization") != "Bearer " + TOKEN:
                route.fulfill(status=401, json={"detail": "Invalid token"}, headers=headers)
                return
            path = urlsplit(request.url).path
            if path.endswith("/groups"):
                body = {"items": [{"call_id": 777, "status": "completed", "summary": "Synthetic summary",
                                  "crm_status": "synced", "device_id": "test-device", "recording_id": "test-recording",
                                  "event_count": 6, "failure_count": 0, "last_event_at": "2026-10-16T07:00:00Z",
                                  "last_event": "crm_result", "last_outcome": "success"}],
                        "next_before_call_id": None, "unassigned_count": 0}
            elif "/events/" in path:
                body = {"id": 501, "call_id": 777, "event": "crm_result", "correlation_id": "test-correlation",
                        "details": {"http_status": 200, "response": "accepted"}}
            elif "/calls/" in path:
                body = {"call_id": 777, "analysis": {"summary": "Synthetic summary"}}
            else:
                body = {"items": [{"id": 501, "call_id": 777, "device_id": "test-device", "recording_id": "test-recording",
                                  "correlation_id": "test-correlation", "stage": "crm", "event": "crm_result",
                                  "outcome": "success", "attempt": 1, "created_at": "2026-10-16T07:00:00Z"}],
                        "next_before_id": None}
            route.fulfill(status=200, json=body, headers=headers)

        page.route("**/api/v1/recording-audit**", respond)
        page.goto(BASE + "/audit")
        page.get_by_placeholder("ERPNEXT_ADMIN_TOKEN").fill(TOKEN)
        page.get_by_role("button", name="Save connection", exact=True).click()
        expect(page.get_by_text("Saved audit connection", exact=False)).to_be_visible()
        expect(page.get_by_role("heading", name="Call #777", exact=True)).to_have_count(1)
        page.reload()
        expect(page.get_by_text("Saved audit connection", exact=False)).to_be_visible()
        expect(page.get_by_placeholder("ERPNEXT_ADMIN_TOKEN")).to_have_count(0)
        page.get_by_role("link", name="Call #777", exact=False).click()
        expect(page.get_by_role("heading", name="Call #777 audit trail")).to_be_visible()
        expect(page.get_by_text("Saved audit connection", exact=False)).to_be_visible()
        page.get_by_role("button", name="Inspect", exact=True).click()
        expect(page.get_by_text('"response": "accepted"', exact=False)).to_be_visible()
        page.reload()
        expect(page.get_by_text("Saved audit connection", exact=False)).to_be_visible()
        page.get_by_role("button", name="Change token", exact=True).click()
        page.get_by_placeholder("ERPNEXT_ADMIN_TOKEN").fill("wrong-test-token")
        page.get_by_role("button", name="Save connection", exact=True).click()
        expect(page.get_by_text("Invalid admin token. The saved connection has not changed.", exact=True)).to_be_visible()
        assert page.evaluate("key => localStorage.getItem(key)", KEY) == TOKEN
        page.get_by_role("button", name="Cancel", exact=True).click()
        page.get_by_role("button", name="Forget saved token", exact=True).click()
        expect(page.get_by_placeholder("ERPNEXT_ADMIN_TOKEN")).to_be_visible()
        assert page.evaluate("key => localStorage.getItem(key)", KEY) is None
        page.reload()
        expect(page.get_by_placeholder("ERPNEXT_ADMIN_TOKEN")).to_be_visible()
        assert not errors, json.dumps(errors)
        context.close()
        browser.close()
    print("PASS: grouped calls, drill-down, refresh/navigation persistence, invalid replacement and explicit forget")


if __name__ == "__main__":
    main()
