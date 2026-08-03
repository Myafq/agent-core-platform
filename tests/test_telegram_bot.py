"""Offline tests for Telegram transport parsing and delivery limits."""

from __future__ import annotations

import unittest
from pathlib import Path

from clients.telegram.bot import TELEGRAM_MESSAGE_LIMIT, TelegramApiError, TelegramClient, TypingIndicator, incoming_message, split_message


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

    def test_debug_logging_does_not_include_payload_or_transport_error_details(self) -> None:
        source = (Path(__file__).parents[1] / "clients" / "telegram" / "bot.py").read_text(encoding="utf-8")
        self.assertIn('LOGGER.debug("Telegram poll updates=%s", len(updates))', source)
        self.assertIn('LOGGER.debug("Telegram private text accepted")', source)
        self.assertNotIn('failed: {error}', source)
        self.assertNotIn('result.get(\'description\'', source)

    def test_typing_indicator_starts_and_stops_without_exposing_chat_state(self) -> None:
        class FakeTelegram:
            def __init__(self) -> None:
                self.actions: list[int] = []

            def send_typing(self, chat_id: int) -> None:
                self.actions.append(chat_id)

        telegram = FakeTelegram()
        with TypingIndicator(telegram, 11, interval_seconds=60):  # type: ignore[arg-type]
            pass
        self.assertEqual(telegram.actions, [11])

    def test_typing_failure_does_not_interrupt_the_harness_response(self) -> None:
        class FailingTelegram:
            def send_typing(self, chat_id: int) -> None:
                raise TelegramApiError("safe")

        with TypingIndicator(FailingTelegram(), 11, interval_seconds=60):  # type: ignore[arg-type]
            pass

    def test_typing_uses_the_standard_telegram_action(self) -> None:
        source = (Path(__file__).parents[1] / "clients" / "telegram" / "bot.py").read_text(encoding="utf-8")
        self.assertIn('self.call("sendChatAction", {"chat_id": chat_id, "action": "typing"})', source)


if __name__ == "__main__":
    unittest.main()
