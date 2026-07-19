"""Offline tests for Telegram long-polling adapter behavior."""

from __future__ import annotations

import unittest

from clients.telegram.bot import (
    TELEGRAM_MESSAGE_LIMIT,
    command_name,
    incoming_message,
    initial_session_id,
    split_message,
    telegram_identity,
)


class TelegramBotTests(unittest.TestCase):
    def test_parses_private_text_messages(self) -> None:
        message = incoming_message(
            {"message": {"text": "hello", "chat": {"id": 11, "type": "private"}, "from": {"id": 22}}}
        )

        self.assertIsNotNone(message)
        self.assertEqual(message.chat_id, 11)
        self.assertEqual(message.user_id, 22)
        self.assertEqual(message.text, "hello")

    def test_ignores_non_private_and_non_text_updates(self) -> None:
        group = {"message": {"text": "hello", "chat": {"id": 11, "type": "group"}, "from": {"id": 22}}}

        self.assertIsNone(incoming_message(group))
        self.assertIsNone(incoming_message({"message": {"chat": {"id": 11, "type": "private"}}}))

    def test_identity_and_initial_session_are_stable(self) -> None:
        self.assertEqual(telegram_identity(11, 22), telegram_identity(11, 22))
        self.assertNotEqual(telegram_identity(11, 22), telegram_identity(11, 23))
        self.assertEqual(initial_session_id(11), initial_session_id(11))

    def test_handles_commands_addressed_to_the_bot(self) -> None:
        self.assertEqual(command_name("/new@githubassistant_bot"), "/new")
        self.assertEqual(command_name("/start hello"), "/start")
        self.assertIsNone(command_name("hello"))

    def test_splits_telegram_messages_without_losing_content(self) -> None:
        text = "x" * (TELEGRAM_MESSAGE_LIMIT + 5)

        chunks = split_message(text)

        self.assertEqual("".join(chunks), text)
        self.assertTrue(all(len(chunk) <= TELEGRAM_MESSAGE_LIMIT for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
