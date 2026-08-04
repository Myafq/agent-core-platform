#!/usr/bin/env python3
"""Slack Socket Mode transport for the shared channel service."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import html
import logging
import os
from pathlib import Path
import re
import sys
from threading import Event, Lock
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from clients.channel.core import ChannelMessage, ChannelService, invoke_harness


SLACK_MESSAGE_LIMIT = 4000
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class IncomingMessage:
    team_id: str
    user_id: str
    channel_id: str
    message_id: str
    text: str
    thread_ts: str
    starts_thread: bool
    is_direct: bool

    @property
    def conversation_id(self) -> str:
        return f"{self.channel_id}:{self.thread_ts}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--harness-arn", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--profile", default="default")
    parser.add_argument("--bot-token-env", default="SLACK_BOT_TOKEN")
    parser.add_argument("--app-token-env", default="SLACK_APP_TOKEN")
    parser.add_argument("--app-id", required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--thread-state-file", type=Path, default=Path(".slack-threads"))
    parser.add_argument("--debug", action="store_true", help="Log safe adapter diagnostics to stderr.")
    return parser.parse_args()


def split_message(text: str) -> list[str]:
    if not text:
        return ["The Harness returned no text."]
    return [text[index : index + SLACK_MESSAGE_LIMIT] for index in range(0, len(text), SLACK_MESSAGE_LIMIT)]


def incoming_message(
    payload: dict[str, Any],
    expected_team_id: str,
    expected_app_id: str,
    expected_bot_user_id: str,
) -> IncomingMessage | None:
    if (
        payload.get("type") != "event_callback"
        or payload.get("team_id") != expected_team_id
        or payload.get("api_app_id") != expected_app_id
    ):
        return None
    event = payload.get("event")
    if not isinstance(event, dict):
        return None
    event_type = event.get("type")
    channel_type = event.get("channel_type")
    is_direct = event_type == "message" and channel_type == "im"
    is_mention = event_type == "app_mention"
    is_channel_followup = event_type == "message" and channel_type in {"channel", "group"} and isinstance(event.get("thread_ts"), str)
    if not (is_direct or is_mention or is_channel_followup) or event.get("subtype") is not None or "bot_id" in event:
        return None
    event_id = payload.get("event_id")
    user_id = event.get("user")
    channel_id = event.get("channel")
    message_ts = event.get("ts")
    text = event.get("text")
    thread_ts = event.get("thread_ts") or message_ts
    if not all(isinstance(value, str) and value for value in (event_id, user_id, channel_id, message_ts, text)):
        return None
    if not isinstance(thread_ts, str) or not thread_ts:
        return None
    normalized_text = html.unescape(text).strip()
    if is_mention:
        normalized_text = re.sub(rf"<@{re.escape(expected_bot_user_id)}(?:\|[^>]+)?>", "", normalized_text, count=1).strip()
    return IncomingMessage(
        team_id=expected_team_id,
        user_id=user_id,
        channel_id=channel_id,
        message_id=event_id,
        text=normalized_text,
        thread_ts=thread_ts,
        starts_thread=is_direct or is_mention,
        is_direct=is_direct,
    )


class SlackThreadRegistry:
    """Persist pseudonymous roots for channel threads started through a mention."""

    def __init__(self, path: Path, namespace: str) -> None:
        self.path = path
        self.namespace = namespace
        self._lock = Lock()
        try:
            self._threads = {line for line in path.read_text(encoding="utf-8").splitlines() if line}
        except FileNotFoundError:
            self._threads = set()

    def _key(self, channel_id: str, thread_ts: str) -> str:
        return hashlib.sha256(f"{self.namespace}:{channel_id}:{thread_ts}".encode("utf-8")).hexdigest()

    def contains(self, channel_id: str, thread_ts: str) -> bool:
        with self._lock:
            return self._key(channel_id, thread_ts) in self._threads

    def add(self, channel_id: str, thread_ts: str) -> None:
        key = self._key(channel_id, thread_ts)
        with self._lock:
            if key in self._threads:
                return
            with self.path.open("a", encoding="utf-8") as state_file:
                state_file.write(f"{key}\n")
            self._threads.add(key)


class SlackSocketHandler:
    def __init__(
        self,
        service: ChannelService,
        workspace_id: str,
        app_id: str,
        bot_user_id: str,
        thread_registry: SlackThreadRegistry,
        response_factory: Callable[[str], Any],
    ) -> None:
        self.service = service
        self.workspace_id = workspace_id
        self.app_id = app_id
        self.bot_user_id = bot_user_id
        self.thread_registry = thread_registry
        self.response_factory = response_factory

    def process(self, client: Any, request: Any) -> None:
        client.send_socket_mode_response(self.response_factory(request.envelope_id))
        if request.type != "events_api":
            return
        message = incoming_message(request.payload, self.workspace_id, self.app_id, self.bot_user_id)
        if message is None or not message.text:
            LOGGER.debug("Slack event ignored reason=unsupported_or_empty")
            return
        if message.starts_thread and not message.is_direct:
            self.thread_registry.add(message.channel_id, message.thread_ts)
        elif not message.is_direct and not self.thread_registry.contains(message.channel_id, message.thread_ts):
            LOGGER.debug("Slack event ignored reason=unregistered_thread")
            return
        LOGGER.debug("Slack user text accepted retry=%s", request.retry_attempt is not None)
        try:
            reply = self.service.handle(
                ChannelMessage(
                    "slack",
                    f"{message.team_id}:{self.app_id}",
                    message.user_id,
                    message.conversation_id,
                    message.message_id,
                    message.text,
                )
            )
            if reply is None:
                LOGGER.debug("Slack message produced no reply")
                return
            for chunk in split_message(reply):
                arguments: dict[str, Any] = {
                    "channel": message.channel_id,
                    "text": chunk,
                    "mrkdwn": False,
                    "unfurl_links": False,
                    "unfurl_media": False,
                }
                arguments["thread_ts"] = message.thread_ts
                client.web_client.chat_postMessage(**arguments)
        except Exception as error:
            LOGGER.info("Slack event handling failed class=%s", type(error).__name__)


def main() -> int:
    args = parse_args()
    if args.debug:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        LOGGER.setLevel(logging.DEBUG)
    logging.getLogger("slack_sdk").setLevel(logging.CRITICAL)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    bot_token = os.environ.get(args.bot_token_env)
    app_token = os.environ.get(args.app_token_env)
    if not bot_token or not app_token:
        print(f"Set {args.bot_token_env} and {args.app_token_env} before starting the adapter.", file=sys.stderr)
        return 2
    try:
        import boto3
        from slack_sdk.socket_mode import SocketModeClient
        from slack_sdk.socket_mode.response import SocketModeResponse
        from slack_sdk.web import WebClient
    except ModuleNotFoundError as error:
        print(f"Missing client dependency {error.name!r}. Install clients/cli/requirements.txt.", file=sys.stderr)
        return 2

    web_client = WebClient(token=bot_token)
    try:
        identity = web_client.auth_test()
    except Exception as error:
        LOGGER.info("Slack authentication failed class=%s", type(error).__name__)
        print("Slack authentication failed.", file=sys.stderr)
        return 1
    if identity.get("team_id") != args.workspace_id:
        print("Slack bot token does not belong to the configured workspace.", file=sys.stderr)
        return 1
    bot_user_id = identity.get("user_id")
    if not isinstance(bot_user_id, str) or not bot_user_id:
        print("Slack authentication did not return a bot user ID.", file=sys.stderr)
        return 1

    harness = boto3.Session(profile_name=args.profile, region_name=args.region).client("bedrock-agentcore")
    service = ChannelService(
        invoke=lambda session_id, user_id, text: invoke_harness(harness, args.harness_arn, session_id, user_id, text),
    )
    socket_client = SocketModeClient(app_token=app_token, web_client=web_client, trace_enabled=False)
    handler = SlackSocketHandler(
        service,
        args.workspace_id,
        args.app_id,
        bot_user_id,
        SlackThreadRegistry(args.thread_state_file, f"{args.workspace_id}:{args.app_id}"),
        lambda envelope_id: SocketModeResponse(envelope_id=envelope_id),
    )
    socket_client.socket_mode_request_listeners.append(handler.process)
    LOGGER.debug("Slack adapter configured workspace_bound=true")
    socket_client.connect()
    print("Slack Socket Mode started. Press Ctrl-C to stop.")
    try:
        Event().wait()
    except KeyboardInterrupt:
        socket_client.disconnect()
        print("\nSlack Socket Mode stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
