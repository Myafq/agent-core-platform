"""Offline tests for the trusted channel application service."""

from __future__ import annotations

import unittest

from clients.channel.core import (
    EMPTY_RESPONSE_TEXT,
    HELP_TEXT,
    NEW_SESSION_TEXT,
    SAFE_FAILURE_TEXT,
    ChannelMessage,
    ChannelService,
    HarnessStreamError,
    invoke_harness,
)
from contracts.contract_validation import runtime_user_id


def message(*, message_id: str = "99", user_id: str = "42", text: str = "hello") -> ChannelMessage:
    return ChannelMessage("telegram", "bot-123", user_id, user_id, message_id, text)


class ChannelCoreTests(unittest.TestCase):
    def test_identity_is_stable_and_channel_partitioned(self) -> None:
        first = message().as_dict()
        second = message().as_dict()
        slack = ChannelMessage("slack", "bot-123", "42", "42", "99", "hello").as_dict()
        self.assertEqual(runtime_user_id(first), runtime_user_id(second))
        self.assertNotEqual(runtime_user_id(first), runtime_user_id(slack))

    def test_new_session_replaces_the_conversation_session(self) -> None:
        calls: list[tuple[str, str, str]] = []
        service = ChannelService(lambda *args: calls.append(args) or "reply")
        self.assertEqual(service.handle(message(message_id="1")), "reply")
        first_session = calls[-1][0]
        self.assertEqual(service.handle(message(message_id="2", text="/new")), NEW_SESSION_TEXT)
        self.assertEqual(service.handle(message(message_id="3")), "reply")
        self.assertNotEqual(first_session, calls[-1][0])

    def test_duplicate_message_is_not_invoked_twice(self) -> None:
        calls: list[tuple[str, str, str]] = []
        service = ChannelService(lambda *args: calls.append(args) or "reply")
        self.assertEqual(service.handle(message()), "reply")
        self.assertIsNone(service.handle(message()))
        self.assertEqual(len(calls), 1)

    def test_help_allow_list_empty_response_and_safe_stream_error(self) -> None:
        allowed = runtime_user_id(message().as_dict())
        service = ChannelService(lambda *_: "", allowed_users={allowed})
        self.assertEqual(service.handle(message(text="/help")), HELP_TEXT)
        self.assertEqual(service.handle(message(message_id="100")), EMPTY_RESPONSE_TEXT)
        rejected = ChannelService(lambda *_: "reply", allowed_users={allowed})
        self.assertIsNone(rejected.handle(message(user_id="other")))
        failed = ChannelService(lambda *_: (_ for _ in ()).throw(HarnessStreamError("runtimeClientError")))
        self.assertEqual(failed.handle(message(message_id="101")), SAFE_FAILURE_TEXT)

    def test_harness_stream_collects_text_and_hides_error_details(self) -> None:
        class Client:
            def invoke_harness(self, **kwargs):
                self.kwargs = kwargs
                return {"stream": [{"contentBlockDelta": {"delta": {"text": "hello"}}}, {"contentBlockDelta": {"delta": {"text": " world"}}}]}

        client = Client()
        self.assertEqual(invoke_harness(client, "arn", "session", "user", "prompt"), "hello world")
        self.assertEqual(client.kwargs["runtimeUserId"], "user")

        class FailedClient:
            def invoke_harness(self, **_kwargs):
                return {"stream": [{"runtimeClientError": {"secret": "do-not-print"}}]}

        with self.assertRaisesRegex(HarnessStreamError, "runtimeClientError") as error:
            invoke_harness(FailedClient(), "arn", "session", "user", "prompt")
        self.assertNotIn("do-not-print", str(error.exception))


if __name__ == "__main__":
    unittest.main()
