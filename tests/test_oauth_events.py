from __future__ import annotations

import json
import unittest
from pathlib import Path

from clients.oauth_events import OAuthPresentationState, oauth_user_message, parse_oauth_event, safe_runtime_error_summary, sanitize_for_diagnostics


FIXTURES = Path(__file__).parent / "fixtures" / "oauth_events"


class OAuthEventTests(unittest.TestCase):
    def load_fixture(self, name: str):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def test_parses_provisional_synthetic_authorization_states(self):
        required = parse_oauth_event(self.load_fixture("synthetic_authorization_required.json"))
        pending = parse_oauth_event(self.load_fixture("synthetic_pending.json"))
        failed = parse_oauth_event(self.load_fixture("synthetic_failed.json"))

        self.assertEqual((required.status, required.authorization_url), ("authorization_required", "https://example.invalid/authorize"))
        self.assertEqual(pending.status, "pending")
        self.assertEqual(failed.status, "failed")

    def test_unknown_or_malformed_events_are_ignored(self):
        self.assertIsNone(parse_oauth_event({"runtimeClientError": {"authorization_url": "https://example.invalid"}}))
        self.assertIsNone(parse_oauth_event({"type": "authorization_required", "authorization_url": "http://example.invalid"}))
        self.assertIsNone(parse_oauth_event({"type": "authorization_required", "authorization_url": "https://user@example.invalid"}))

    def test_authorization_url_is_presented_once_with_retry_instructions(self):
        event = parse_oauth_event(self.load_fixture("synthetic_authorization_required.json"))
        state = OAuthPresentationState()
        first = oauth_user_message(event, state)
        second = oauth_user_message(event, state)

        self.assertEqual(first.count("https://example.invalid/authorize"), 1)
        self.assertNotIn("https://example.invalid/authorize", second)
        self.assertIn("retry", first[0].lower())

    def test_recursively_sanitizes_credentials_and_url_data(self):
        sanitized = sanitize_for_diagnostics({"authorizationCode": "do-not-print", "nested": {"accessToken": "do-not-print", "items": [{"API-Key": "do-not-print"}]}, "url": "https://user:pass@example.invalid/path/secret-value?code=do-not-print#token=do-not-print"})
        rendered = json.dumps(sanitized, sort_keys=True)
        self.assertNotIn("do-not-print", rendered)
        self.assertNotIn("?code=", rendered)
        self.assertNotIn("#token=", rendered)
        self.assertNotIn("user:pass", rendered)
        self.assertNotIn("secret-value", rendered)
        self.assertIn("https://example.invalid<redacted-url-data>", rendered)
        self.assertIn("<redacted>", rendered)

    def test_runtime_errors_are_allow_listed(self):
        self.assertEqual(safe_runtime_error_summary("runtimeClientError"), "AgentCore returned runtimeClientError.")


if __name__ == "__main__":
    unittest.main()
