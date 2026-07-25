#!/usr/bin/env python3
"""Long-polling Telegram transport for the shared channel service."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from clients.channel.core import ChannelMessage, ChannelService, invoke_harness
from contracts.contract_validation import runtime_user_id


TELEGRAM_API_URL = "https://api.telegram.org"
TELEGRAM_MESSAGE_LIMIT = 4096
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class IncomingMessage:
    chat_id: int
    user_id: int
    message_id: int
    text: str


class TelegramApiError(RuntimeError):
    """A Telegram Bot API request failed."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--harness-arn", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--profile", default="default")
    parser.add_argument("--token-env", default="TELEGRAM_BOT_TOKEN")
    parser.add_argument("--allowed-user-id", action="append", default=[])
    parser.add_argument("--poll-timeout", type=int, default=30)
    parser.add_argument("--offset-file", type=Path, default=Path(".telegram-offset"))
    parser.add_argument("--debug", action="store_true", help="Log safe adapter diagnostics to stderr.")
    return parser.parse_args()


def split_message(text: str) -> list[str]:
    if not text:
        return ["The Harness returned no text."]
    return [text[index : index + TELEGRAM_MESSAGE_LIMIT] for index in range(0, len(text), TELEGRAM_MESSAGE_LIMIT)]


def incoming_message(update: dict[str, Any]) -> IncomingMessage | None:
    message = update.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("text"), str):
        return None
    chat = message.get("chat")
    sender = message.get("from")
    if not isinstance(chat, dict) or not isinstance(sender, dict):
        return None
    if (
        chat.get("type") != "private"
        or not isinstance(chat.get("id"), int)
        or not isinstance(sender.get("id"), int)
        or not isinstance(message.get("message_id"), int)
    ):
        return None
    return IncomingMessage(chat["id"], sender["id"], message["message_id"], message["text"].strip())


def load_offset(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except FileNotFoundError:
        return None
    except ValueError:
        raise TelegramApiError(f"Offset file contains an invalid update ID: {path}") from None


def save_offset(path: Path, offset: int) -> None:
    path.write_text(f"{offset}\n", encoding="utf-8")


class TelegramClient:
    def __init__(self, token: str) -> None:
        self.token = token

    def call(self, method: str, payload: dict[str, Any] | None = None, timeout: int = 40) -> Any:
        request = Request(
            f"{TELEGRAM_API_URL}/bot{self.token}/{method}",
            data=json.dumps(payload or {}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                result = json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            raise TelegramApiError(f"Telegram {method} failed: {error}") from error
        if not result.get("ok"):
            raise TelegramApiError(f"Telegram {method} failed: {result.get('description', 'unknown error')}")
        return result["result"]

    def send_text(self, chat_id: int, text: str) -> None:
        for chunk in split_message(text):
            self.call("sendMessage", {"chat_id": chat_id, "text": chunk, "link_preview_options": {"is_disabled": True}})


def main() -> int:
    args = parse_args()
    if args.debug:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        LOGGER.setLevel(logging.DEBUG)
        logging.getLogger("botocore").setLevel(logging.WARNING)
    if not (token := os.environ.get(args.token_env)):
        print(f"Set {args.token_env} to the bot token before starting the adapter.", file=sys.stderr)
        return 2
    if not 1 <= args.poll_timeout <= 50:
        print("--poll-timeout must be between 1 and 50 seconds.", file=sys.stderr)
        return 2
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ModuleNotFoundError as error:
        print(f"Missing CLI dependency {error.name!r}. Install clients/cli/requirements.txt.", file=sys.stderr)
        return 2

    telegram = TelegramClient(token)
    try:
        if telegram.call("getWebhookInfo").get("url"):
            print("Telegram webhook is configured; remove it before using long polling.", file=sys.stderr)
            return 1
        bot = telegram.call("getMe")
        if not isinstance(bot, dict) or not isinstance(bot.get("id"), int):
            raise TelegramApiError("Telegram getMe returned an invalid bot ID.")
    except TelegramApiError as error:
        print(error, file=sys.stderr)
        return 1
    harness = boto3.Session(profile_name=args.profile, region_name=args.region).client("bedrock-agentcore")
    tenant_id = str(bot["id"])
    allowed_users = {
        runtime_user_id(ChannelMessage("telegram", tenant_id, str(user_id), "configuration", "configuration", "allow-list").as_dict())
        for user_id in args.allowed_user_id
    }
    service = ChannelService(
        invoke=lambda session_id, user_id, text: invoke_harness(harness, args.harness_arn, session_id, user_id, text),
        allowed_users=allowed_users,
    )
    offset = load_offset(args.offset_file)
    print("Telegram long polling started. Press Ctrl-C to stop.")
    while True:
        try:
            updates = telegram.call("getUpdates", {"offset": offset, "timeout": args.poll_timeout, "allowed_updates": ["message"]}, timeout=args.poll_timeout + 10)
            for update in updates:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    offset = update_id + 1
                    save_offset(args.offset_file, offset)
                message = incoming_message(update)
                if message is None or not message.text:
                    continue
                reply = service.handle(ChannelMessage("telegram", tenant_id, str(message.user_id), str(message.chat_id), str(message.message_id), message.text))
                if reply is not None:
                    telegram.send_text(message.chat_id, reply)
        except KeyboardInterrupt:
            print("\nTelegram long polling stopped.")
            return 0
        except (BotoCoreError, ClientError, TelegramApiError, RuntimeError) as error:
            LOGGER.info("Telegram polling failure class=%s", type(error).__name__)
            print("Telegram adapter encountered a temporary failure.", file=sys.stderr)
            time.sleep(2)


if __name__ == "__main__":
    raise SystemExit(main())
