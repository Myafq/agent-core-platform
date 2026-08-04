"""Offline tests for the Slack Socket Mode transport."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile
import unittest

from clients.channel.core import ChannelService, NEW_SESSION_TEXT
from clients.slack.bot import SLACK_MESSAGE_LIMIT, SlackSocketHandler, SlackThreadRegistry, incoming_message, split_message


def payload(*, event_id: str = "Ev1", text: str = "hello", **event_fields: object) -> dict[str, object]:
    event = {
        "type": "message",
        "channel_type": "im",
        "user": "U1",
        "channel": "D1",
        "ts": "100.1",
        "text": text,
    }
    event.update(event_fields)
    return {
        "type": "event_callback",
        "team_id": "T1",
        "api_app_id": "A1",
        "event_id": event_id,
        "authorizations": [{"team_id": "T1", "user_id": "UBOT", "is_bot": True}],
        "event": event,
    }


@dataclass
class FakeRequest:
    payload: dict[str, object]
    envelope_id: str = "env-1"
    type: str = "events_api"
    retry_attempt: int | None = None


class FakeWebClient:
    def __init__(self, calls: list[object]) -> None:
        self.calls = calls

    def chat_postMessage(self, **kwargs: object) -> None:
        self.calls.append(("post", kwargs))


class FakeSocketClient:
    def __init__(self, calls: list[object]) -> None:
        self.calls = calls
        self.web_client = FakeWebClient(calls)

    def send_socket_mode_response(self, response: object) -> None:
        self.calls.append(("ack", response))


class SlackBotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.registry_path = Path(self.temporary_directory.name) / "threads"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def handler(self, service: ChannelService, response_factory=lambda envelope_id: envelope_id) -> SlackSocketHandler:
        return SlackSocketHandler(service, "T1", "A1", "UBOT", SlackThreadRegistry(self.registry_path, "T1:A1"), response_factory)

    def test_accepts_only_direct_human_text_from_the_configured_workspace(self) -> None:
        message = incoming_message(payload(text="hello &amp; goodbye"), "T1", "A1", "UBOT")
        self.assertIsNotNone(message)
        self.assertEqual(message.text, "hello & goodbye")
        self.assertEqual(message.conversation_id, "D1:100.1")
        self.assertEqual(message.thread_ts, "100.1")
        self.assertIsNone(incoming_message(payload(subtype="bot_message", bot_id="B1"), "T1", "A1", "UBOT"))
        self.assertIsNone(incoming_message(payload(channel_type="channel", thread_ts=None), "T1", "A1", "UBOT"))
        self.assertIsNone(incoming_message(payload(), "T2", "A1", "UBOT"))
        self.assertIsNone(incoming_message(payload(), "T1", "ADIFFERENT", "UBOT"))

    def test_accepts_channel_mentions_and_removes_the_bot_mention(self) -> None:
        message = incoming_message(
            payload(text="<@UBOT> investigate this", type="app_mention", channel="C1", channel_type="channel"),
            "T1",
            "A1",
            "UBOT",
        )
        self.assertIsNotNone(message)
        self.assertEqual(message.text, "investigate this")
        self.assertEqual(message.conversation_id, "C1:100.1")
        self.assertTrue(message.starts_thread)

    def test_acknowledges_before_invocation_and_sends_plain_bounded_output(self) -> None:
        calls: list[object] = []
        service = ChannelService(lambda *_: calls.append("invoke") or ("x" * (SLACK_MESSAGE_LIMIT + 1)))
        handler = self.handler(service, lambda envelope_id: {"envelope_id": envelope_id})
        handler.process(FakeSocketClient(calls), FakeRequest(payload()))

        self.assertEqual(calls[0], ("ack", {"envelope_id": "env-1"}))
        self.assertEqual(calls[1], "invoke")
        posts = [call[1] for call in calls if isinstance(call, tuple) and call[0] == "post"]
        self.assertEqual(len(posts), 2)
        self.assertEqual("".join(post["text"] for post in posts), "x" * (SLACK_MESSAGE_LIMIT + 1))
        self.assertTrue(all(post["mrkdwn"] is False for post in posts))
        self.assertTrue(all(post["unfurl_links"] is False and post["unfurl_media"] is False for post in posts))
        self.assertTrue(all(post["thread_ts"] == "100.1" for post in posts))

    def test_retry_is_acknowledged_but_duplicate_event_is_not_reinvoked(self) -> None:
        calls: list[object] = []
        service = ChannelService(lambda *_: calls.append("invoke") or "reply")
        handler = self.handler(service)
        client = FakeSocketClient(calls)
        handler.process(client, FakeRequest(payload()))
        handler.process(client, FakeRequest(payload(), envelope_id="env-2", retry_attempt=1))

        self.assertEqual(calls.count("invoke"), 1)
        self.assertIn(("ack", "env-2"), calls)

    def test_channel_thread_followups_share_the_registered_mention_session(self) -> None:
        calls: list[object] = []
        observed: list[str] = []
        service = ChannelService(lambda session_id, *_: observed.append(session_id) or "reply")
        handler = self.handler(service)
        client = FakeSocketClient(calls)
        handler.process(
            client,
            FakeRequest(payload(event_id="Ev1", text="<@UBOT> start", type="app_mention", channel="C1", channel_type="channel", ts="90.0")),
        )
        handler.process(
            client,
            FakeRequest(payload(event_id="Ev2", text="continue", user="U2", channel="C1", channel_type="channel", thread_ts="90.0")),
        )

        posts = [call[1] for call in calls if isinstance(call, tuple) and call[0] == "post"]
        self.assertEqual([post["thread_ts"] for post in posts], ["90.0", "90.0"])
        self.assertEqual(len(observed), 2)
        self.assertEqual(observed[0], observed[1])

    def test_ignores_channel_messages_outside_registered_bot_threads(self) -> None:
        calls: list[object] = []
        handler = self.handler(ChannelService(lambda *_: calls.append("invoke") or "reply"))
        handler.process(
            FakeSocketClient(calls),
            FakeRequest(payload(channel="C1", channel_type="channel", thread_ts="90.0")),
        )
        self.assertNotIn("invoke", calls)

    def test_thread_registry_persists_only_pseudonymous_roots(self) -> None:
        registry = SlackThreadRegistry(self.registry_path, "T1:A1")
        registry.add("C1", "90.0")
        self.assertTrue(SlackThreadRegistry(self.registry_path, "T1:A1").contains("C1", "90.0"))
        self.assertFalse(SlackThreadRegistry(self.registry_path, "T1:A2").contains("C1", "90.0"))
        state = self.registry_path.read_text(encoding="utf-8")
        self.assertNotIn("C1", state)
        self.assertNotIn("90.0", state)

    def test_new_command_uses_shared_channel_behavior(self) -> None:
        calls: list[object] = []
        handler = self.handler(ChannelService(lambda *_: "unused"))
        handler.process(FakeSocketClient(calls), FakeRequest(payload(text="/new")))
        post = next(call[1] for call in calls if isinstance(call, tuple) and call[0] == "post")
        self.assertEqual(post["text"], NEW_SESSION_TEXT)

    def test_split_preserves_content_and_safe_logs_exclude_payloads(self) -> None:
        text = "x" * (SLACK_MESSAGE_LIMIT + 5)
        self.assertEqual("".join(split_message(text)), text)
        source = (Path(__file__).parents[1] / "clients" / "slack" / "bot.py").read_text(encoding="utf-8")
        self.assertIn('logging.getLogger("slack_sdk").setLevel(logging.CRITICAL)', source)
        self.assertNotIn('"--allowed-user-id"', source)
        self.assertNotIn("LOGGER.debug(request.payload", source)
        self.assertNotIn("LOGGER.info(error", source)


if __name__ == "__main__":
    unittest.main()
