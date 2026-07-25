"""Offline tests for Telegram transport parsing and delivery limits."""

from __future__ import annotations

import unittest
from pathlib import Path

from clients.telegram.bot import TELEGRAM_MESSAGE_LIMIT, incoming_message, split_message


class TelegramBotTests(unittest.TestCase):
    def test_parses_private_text_messages(self) -> None:
        message = incoming_message(
            {"message": {"message_id": 99, "text": "hello", "chat": {"id": 11, "type": "private"}, "from": {"id": 22}}}
        )
        self.assertIsNotNone(message)
        self.assertEqual((message.chat_id, message.user_id, message.message_id, message.text), (11, 22, 99, "hello"))

    def test_ignores_non_private_non_text_and_unidentified_updates(self) -> None:
        self.assertIsNone(incoming_message({"message": {"message_id": 1, "text": "hello", "chat": {"id": 11, "type": "group"}, "from": {"id": 22}}}))
        self.assertIsNone(incoming_message({"message": {"chat": {"id": 11, "type": "private"}}}))
        self.assertIsNone(incoming_message({"message": {"text": "hello", "chat": {"id": 11, "type": "private"}, "from": {"id": 22}}}))

    def test_splits_telegram_messages_without_losing_content(self) -> None:
        text = "x" * (TELEGRAM_MESSAGE_LIMIT + 5)
        chunks = split_message(text)
        self.assertEqual("".join(chunks), text)
        self.assertTrue(all(len(chunk) <= TELEGRAM_MESSAGE_LIMIT for chunk in chunks))

    def test_debug_does_not_enable_botocore_request_logging(self) -> None:
        source = (Path(__file__).parents[1] / "clients" / "telegram" / "bot.py").read_text(encoding="utf-8")
        self.assertIn('logging.getLogger("botocore").setLevel(logging.WARNING)', source)


if __name__ == "__main__":
    unittest.main()
