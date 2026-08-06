"""Offline tests for Slack Events ingress and durable worker behavior."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "containers" / "slack-events" / "service"))

from slack_events.core import (
    InMemorySlackState,
    REPLAY_WINDOW_SECONDS,
    SlackEventsError,
    SlackWorker,
    ingress_response,
    verify_slack_signature,
)
from slack_events.ingress import SqsFifoDispatcher
from slack_events.worker import DynamoSlackState, UrllibSlackPoster


NOW = 1_700_000_000
AGENT = "github-assistant"
PREFIX = "/agent-core/slack/agents"


class FakeParameters:
    def __init__(self, *, state: str = "installed") -> None:
        self.values = {
            f"{PREFIX}/{AGENT}/binding": json.dumps(
                {
                    "agent_name": AGENT,
                    "workspace_id": "T1",
                    "app_id": "A1",
                    "installation_state": state,
                    "bot_user_id": "U1",
                }
            ),
            f"{PREFIX}/{AGENT}/credentials": json.dumps(
                {"signing_secret": "signing-secret", "bot_token": "xoxb-secret"}
            ),
        }
        self.calls: list[tuple[str, bool]] = []

    def get(self, name: str, *, decrypt: bool) -> str | None:
        self.calls.append((name, decrypt))
        return self.values.get(name)


class FakeDispatcher:
    def __init__(self) -> None:
        self.envelopes: list[dict[str, object]] = []

    def dispatch(self, envelope) -> None:
        self.envelopes.append(dict(envelope))


class FakeHarness:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []
        self.reply = "Harness reply"

    def invoke(self, harness_arn: str, runtime_session_id: str, runtime_user_id: str, text: str) -> str:
        self.calls.append((harness_arn, runtime_session_id, runtime_user_id, text))
        return self.reply


class FakePoster:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []
        self.status_calls: list[tuple[str, str, str, str]] = []
        self.reject_status = False

    def set_status(self, bot_token: str, channel_id: str, thread_ts: str, status: str) -> None:
        self.status_calls.append((bot_token, channel_id, thread_ts, status))
        if self.reject_status:
            raise RuntimeError("slack_rejected")

    def post(self, bot_token: str, channel_id: str, thread_ts: str, text: str) -> None:
        self.calls.append((bot_token, channel_id, thread_ts, text))


def signed_request(payload: dict[str, object], *, timestamp: int = NOW) -> dict[str, object]:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = "v0=" + hmac.new(
        b"signing-secret", f"v0:{timestamp}:".encode("ascii") + raw, hashlib.sha256
    ).hexdigest()
    return {
        "pathParameters": {"agent": AGENT},
        "headers": {"X-Slack-Request-Timestamp": str(timestamp), "X-Slack-Signature": signature},
        "body": raw.decode("utf-8"),
        "isBase64Encoded": False,
    }


def event_payload(*, event_type: str = "app_mention", event_id: str = "Ev1", **overrides: object) -> dict[str, object]:
    event: dict[str, object] = {
        "type": event_type,
        "channel_type": "channel",
        "user": "U-user",
        "channel": "C1",
        "ts": "100.1",
        "text": "<@U1> hello",
    }
    event.update(overrides.pop("event", {}))
    return {"type": "event_callback", "team_id": "T1", "api_app_id": "A1", "event_id": event_id, "event": event, **overrides}


class SlackEventsIngressTests(unittest.TestCase):
    def test_literal_api_gateway_route_reads_agent_from_raw_path(self) -> None:
        request = signed_request(event_payload())
        request.pop("pathParameters")
        request["rawPath"] = f"/slack/events/{AGENT}"
        dispatcher = FakeDispatcher()

        response = ingress_response(request, FakeParameters(), dispatcher, prefix=PREFIX, now=NOW)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(len(dispatcher.envelopes), 1)

    def test_signature_uses_raw_body_and_replay_window(self) -> None:
        raw = b'{"not":"reformatted"}'
        signature = "v0=" + hmac.new(b"signing-secret", f"v0:{NOW}:".encode("ascii") + raw, hashlib.sha256).hexdigest()
        verify_slack_signature(
            {"x-slack-request-timestamp": str(NOW), "x-slack-signature": signature}, raw, "signing-secret", now=NOW
        )
        with self.assertRaisesRegex(SlackEventsError, "timestamp_stale"):
            verify_slack_signature(
                {"x-slack-request-timestamp": str(NOW - REPLAY_WINDOW_SECONDS - 1), "x-slack-signature": signature},
                raw,
                "signing-secret",
                now=NOW,
            )

    def test_url_verification_accepts_official_payload_without_app_id(self) -> None:
        parameters = FakeParameters(state="socket_mode_ready")
        dispatcher = FakeDispatcher()
        response = ingress_response(
            signed_request({"type": "url_verification", "challenge": "challenge-value"}),
            parameters,
            dispatcher,
            prefix=PREFIX,
            now=NOW,
        )
        self.assertEqual(response["body"], "challenge-value")
        self.assertEqual(dispatcher.envelopes, [])

    def test_event_requires_exact_bound_workspace_and_app_before_dispatch(self) -> None:
        payload = event_payload(team_id="T-other")
        with self.assertRaisesRegex(SlackEventsError, "routing_invalid"):
            ingress_response(signed_request(payload), FakeParameters(), FakeDispatcher(), prefix=PREFIX, now=NOW)

    def test_dispatch_is_narrowed_and_does_not_include_signing_material(self) -> None:
        dispatcher = FakeDispatcher()
        ingress_response(signed_request(event_payload()), FakeParameters(), dispatcher, prefix=PREFIX, now=NOW)
        self.assertEqual(len(dispatcher.envelopes), 1)
        envelope = dispatcher.envelopes[0]
        self.assertEqual(set(envelope), {"version", "agent", "workspace_id", "app_id", "bot_user_id", "event_id", "event"})
        self.assertNotIn("signing_secret", json.dumps(envelope))
        self.assertEqual(envelope["event"]["text"], "<@U1> hello")


class SlackEventsWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = InMemorySlackState()
        self.harness = FakeHarness()
        self.poster = FakePoster()
        self.worker = SlackWorker(self.state, self.harness, self.poster)

    def envelope(self, **event: object) -> dict[str, object]:
        payload = event_payload(**event)
        return {
            "version": 1,
            "agent": AGENT,
            "workspace_id": "T1",
            "app_id": "A1",
            "bot_user_id": "U1",
            "event_id": payload["event_id"],
            "event": payload["event"],
        }

    def process(self, envelope: dict[str, object]) -> None:
        self.worker.process(envelope, harness_arn="arn:harness", bot_token="xoxb-secret")

    def test_mention_root_then_channel_followup_share_the_thread_and_dedupe(self) -> None:
        root = self.envelope()
        self.process(root)
        self.process(root)
        followup = self.envelope(
            event_type="message",
            event_id="Ev2",
            event={"thread_ts": "100.1", "text": "follow up"},
        )
        self.process(followup)
        self.assertEqual([call[-1] for call in self.poster.calls], ["Harness reply", "Harness reply"])
        self.assertEqual([call[-1] for call in self.harness.calls], ["hello", "follow up"])

    def test_unregistered_channel_thread_and_bot_event_are_ignored(self) -> None:
        self.process(
            self.envelope(event_type="message", event_id="Ev2", event={"thread_ts": "100.1", "text": "follow up"})
        )
        self.process(self.envelope(event_id="Ev3", event={"bot_id": "B1"}))
        self.assertEqual(self.harness.calls, [])
        self.assertEqual(self.poster.calls, [])

    def test_new_session_is_durable_for_the_next_message(self) -> None:
        self.process(self.envelope(event={"text": "<@U1> /new"}))
        self.process(self.envelope(event_id="Ev2", event={"text": "<@U1> next"}))
        self.assertEqual(self.poster.calls[0][-1], "Started a fresh session.")
        self.assertTrue(self.harness.calls[0][1].startswith("session-"))

    def test_sets_native_thread_status_while_harness_runs(self) -> None:
        self.process(self.envelope())
        self.assertEqual(
            self.poster.status_calls,
            [("xoxb-secret", "C1", "100.1", "is working on your request...")],
        )

    def test_status_failure_does_not_interrupt_the_harness_response(self) -> None:
        self.poster.reject_status = True
        self.process(self.envelope())
        self.assertEqual(self.harness.calls[0][-1], "hello")
        self.assertEqual(self.poster.calls[0][-1], "Harness reply")

    def test_commands_do_not_set_a_working_status(self) -> None:
        self.process(self.envelope(event={"text": "<@U1> /new"}))
        self.assertEqual(self.poster.status_calls, [])


class SlackWebApiTests(unittest.TestCase):
    def test_native_status_uses_the_thread_status_endpoint(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def read(self) -> bytes:
                return b'{"ok":true}'

        with patch("slack_events.worker.urllib.request.urlopen", return_value=Response()) as urlopen:
            UrllibSlackPoster().set_status("xoxb-secret", "C1", "100.1", "is working on your request...")

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://slack.com/api/assistant.threads.setStatus")
        self.assertEqual(
            json.loads(request.data),
            {"channel_id": "C1", "thread_ts": "100.1", "status": "is working on your request..."},
        )


class FifoDispatchTests(unittest.TestCase):
    def test_groups_thread_and_hashes_event_deduplication(self) -> None:
        class Client:
            def __init__(self) -> None:
                self.kwargs = None

            def send_message(self, **kwargs) -> None:
                self.kwargs = kwargs

        client = Client()
        SqsFifoDispatcher(client, "queue-url").dispatch(
            {"agent": AGENT, "app_id": "A1", "event_id": "Ev1", "event": {"channel": "C1", "ts": "100.1"}}
        )
        self.assertEqual(client.kwargs["MessageDeduplicationId"], hashlib.sha256(b"Ev1").hexdigest())
        self.assertEqual(len(client.kwargs["MessageGroupId"]), 64)


class DynamoLeaseTests(unittest.TestCase):
    class ConditionalCheckFailedException(Exception):
        pass

    class Client:
        def __init__(self) -> None:
            self.exceptions = type("Exceptions", (), {"ConditionalCheckFailedException": DynamoLeaseTests.ConditionalCheckFailedException})
            self.items: dict[tuple[str, str], dict[str, dict[str, str]]] = {}

        @staticmethod
        def key(item: dict[str, dict[str, str]]) -> tuple[str, str]:
            return item["pk"]["S"], item["sk"]["S"]

        def put_item(self, *, Item, **kwargs) -> None:
            key = self.key(Item)
            if key in self.items:
                raise self.exceptions.ConditionalCheckFailedException()
            self.items[key] = dict(Item)

        def update_item(self, *, Key, UpdateExpression, ConditionExpression, ExpressionAttributeValues, **kwargs) -> None:
            item = self.items[self.key(Key)]
            if "lease_until <" in ConditionExpression:
                if item["status"]["S"] != "inflight" or int(item["lease_until"]["N"]) >= int(ExpressionAttributeValues[":now"]["N"]):
                    raise self.exceptions.ConditionalCheckFailedException()
                item.update(
                    {
                        "status": ExpressionAttributeValues[":inflight"],
                        "lease_until": ExpressionAttributeValues[":lease_until"],
                        "lease_token": ExpressionAttributeValues[":lease_token"],
                        "expires_at": ExpressionAttributeValues[":expires_at"],
                    }
                )
                return
            if item["status"]["S"] != "inflight" or item["lease_token"] != ExpressionAttributeValues[":lease_token"]:
                raise self.exceptions.ConditionalCheckFailedException()
            item["status"] = ExpressionAttributeValues[":completed"]
            item.pop("lease_until", None)
            item.pop("lease_token", None)

    def test_event_claim_lease_can_reclaim_after_expiry_but_not_after_completion(self) -> None:
        client = self.Client()
        state = DynamoSlackState(client, "state-table")
        with patch("slack_events.worker.time.time", side_effect=[1000, 1100, 1241, 1242]):
            self.assertTrue(state.claim_event("T1:A1", "Ev1"))
            self.assertFalse(state.claim_event("T1:A1", "Ev1"))
            self.assertTrue(state.claim_event("T1:A1", "Ev1"))
            state.complete_event("T1:A1", "Ev1")
            self.assertFalse(state.claim_event("T1:A1", "Ev1"))


if __name__ == "__main__":
    unittest.main()
