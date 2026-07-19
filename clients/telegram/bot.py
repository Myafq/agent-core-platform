#!/usr/bin/env python3
"""Long-polling Telegram adapter for a deployed AgentCore Harness."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import uuid


TELEGRAM_API_URL = "https://api.telegram.org"
TELEGRAM_MESSAGE_LIMIT = 4096


@dataclass(frozen=True)
class IncomingMessage:
    chat_id: int
    user_id: int
    text: str


class TelegramApiError(RuntimeError):
    """A Telegram Bot API request failed."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--harness-arn", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--profile", default="default")
    parser.add_argument("--token-env", default="TELEGRAM_BOT_TOKEN")
    parser.add_argument("--poll-timeout", type=int, default=30)
    parser.add_argument("--offset-file", type=Path, default=Path(".telegram-offset"))
    return parser.parse_args()


def telegram_identity(chat_id: int, user_id: int) -> str:
    digest = hashlib.sha256(f"{chat_id}:{user_id}".encode("utf-8")).hexdigest()[:20]
    return f"telegram-{digest}"


def initial_session_id(chat_id: int) -> str:
    digest = hashlib.sha256(str(chat_id).encode("utf-8")).hexdigest()[:24]
    return f"telegram-{digest}"


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
    if chat.get("type") != "private" or not isinstance(chat.get("id"), int) or not isinstance(sender.get("id"), int):
        return None
    return IncomingMessage(chat_id=chat["id"], user_id=sender["id"], text=message["text"].strip())


def command_name(text: str) -> str | None:
    if not text.startswith("/"):
        return None
    return text.split(maxsplit=1)[0].split("@", maxsplit=1)[0]


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
            self.call("sendMessage", {"chat_id": chat_id, "text": chunk})


def invoke_harness(client: Any, harness_arn: str, session_id: str, user_id: str, text: str) -> str:
    response = client.invoke_harness(
        harnessArn=harness_arn,
        qualifier="DEFAULT",
        runtimeSessionId=session_id,
        runtimeUserId=user_id,
        messages=[{"role": "user", "content": [{"text": text}]}],
    )
    chunks: list[str] = []
    for event in response["stream"]:
        delta = event.get("contentBlockDelta", {}).get("delta", {})
        if "text" in delta:
            chunks.append(delta["text"])
        for error_name in ("runtimeClientError", "internalServerException", "validationException"):
            if error_name in event:
                raise RuntimeError(f"{error_name}: {event[error_name]}")
    return "".join(chunks)


def main() -> int:
    args = parse_args()
    token = os.environ.get(args.token_env)
    if not token:
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
        webhook = telegram.call("getWebhookInfo")
    except TelegramApiError as error:
        print(error, file=sys.stderr)
        return 1
    if webhook.get("url"):
        print("Telegram webhook is configured; remove it before using long polling.", file=sys.stderr)
        return 1

    harness = boto3.Session(profile_name=args.profile, region_name=args.region).client("bedrock-agentcore")
    offset = load_offset(args.offset_file)
    sessions: dict[int, str] = {}
    print("Telegram long polling started. Press Ctrl-C to stop.")

    while True:
        try:
            updates = telegram.call(
                "getUpdates",
                {"offset": offset, "timeout": args.poll_timeout, "allowed_updates": ["message"]},
                timeout=args.poll_timeout + 10,
            )
            for update in updates:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    offset = update_id + 1
                    save_offset(args.offset_file, offset)
                message = incoming_message(update)
                if message is None or not message.text:
                    continue
                command = command_name(message.text)
                if command in {"/start", "/help"}:
                    telegram.send_text(message.chat_id, "Send a message to chat with the agent. Use /new for a fresh session.")
                    continue
                if command == "/new":
                    sessions[message.chat_id] = f"telegram-{uuid.uuid4().hex}"
                    telegram.send_text(message.chat_id, "Started a fresh session.")
                    continue
                session_id = sessions.setdefault(message.chat_id, initial_session_id(message.chat_id))
                try:
                    response = invoke_harness(
                        harness,
                        args.harness_arn,
                        session_id,
                        telegram_identity(message.chat_id, message.user_id),
                        message.text,
                    )
                    telegram.send_text(message.chat_id, response)
                except (BotoCoreError, ClientError, RuntimeError, TelegramApiError) as error:
                    print(f"Message handling failed: {error}", file=sys.stderr)
                    telegram.send_text(message.chat_id, "The agent could not complete that request. Please try again.")
        except KeyboardInterrupt:
            print("\nTelegram long polling stopped.")
            return 0
        except TelegramApiError as error:
            print(error, file=sys.stderr)
            time.sleep(2)


if __name__ == "__main__":
    raise SystemExit(main())
