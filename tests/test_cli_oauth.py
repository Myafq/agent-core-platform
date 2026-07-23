from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from clients.cli.chat import local_user_id, new_session_id, safe_invocation_failure, stream_response
from clients.oauth_events import OAuthPresentationState


class FakeHarnessClient:
    def __init__(self, events):
        self.events = events
        self.user_ids: list[str] = []

    def invoke_harness(self, **kwargs):
        self.user_ids.append(kwargs["runtimeUserId"])
        return {"stream": self.events}


class CliOAuthTests(unittest.TestCase):
    def test_cli_prints_a_synthetic_authorization_url_once(self):
        client = FakeHarnessClient([{"type": "authorization_required", "authorization_url": "https://example.invalid/authorize"}])
        state = OAuthPresentationState()
        output = io.StringIO()

        with redirect_stdout(output):
            stream_response(client, "arn", "session-a", "user-a", "hello", state)
            stream_response(client, "arn", "session-b", "user-a", "retry", state)

        self.assertEqual(output.getvalue().count("https://example.invalid/authorize"), 1)
        self.assertEqual(client.user_ids, ["user-a", "user-a"])

    def test_cli_does_not_render_raw_runtime_error_payloads(self):
        client = FakeHarnessClient([{"runtimeClientError": {"authorizationCode": "do-not-print"}}])

        with self.assertRaisesRegex(RuntimeError, "AgentCore returned runtimeClientError") as raised:
            stream_response(client, "arn", "session-a", "user-a", "hello", OAuthPresentationState())

        self.assertNotIn("do-not-print", str(raised.exception))

    def test_new_sessions_do_not_change_the_stable_user_id(self):
        self.assertNotEqual(new_session_id(), new_session_id())
        self.assertEqual(local_user_id(), local_user_id())

    def test_exception_details_never_reach_the_user(self):
        self.assertEqual(safe_invocation_failure(), "Invocation failed. Check AWS access and try again.")
        self.assertNotIn("authorization", safe_invocation_failure().lower())


if __name__ == "__main__":
    unittest.main()
