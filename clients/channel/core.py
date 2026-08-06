"""Trusted, transport-neutral channel-to-Harness application service."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from threading import Lock
from typing import Any, Callable
import uuid

from contracts.contract_validation import ContractError, runtime_user_id, session_id, validate_channel_message


LOGGER = logging.getLogger(__name__)
HELP_TEXT = "Send a message to chat. Use /new to start a fresh session."
NEW_SESSION_TEXT = "Started a fresh session."
EMPTY_RESPONSE_TEXT = "The Harness returned no text."
SAFE_FAILURE_TEXT = "The agent could not complete that request. Please try again."


@dataclass(frozen=True)
class ChannelMessage:
    channel: str
    tenant_id: str
    user_id: str
    conversation_id: str
    message_id: str
    text: str

    def as_dict(self) -> dict[str, str]:
        return {
            "channel": self.channel,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "text": self.text,
        }


class HarnessStreamError(RuntimeError):
    """A Harness stream ended with a safe-to-classify error."""


@dataclass
class ChannelService:
    invoke: Callable[[str, str, str], str]
    allowed_users: set[str] = field(default_factory=set)
    _sessions: dict[str, str] = field(default_factory=dict, init=False)
    _seen_messages: set[tuple[str, str, str]] = field(default_factory=set, init=False)
    _state_lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def handle(self, message: ChannelMessage) -> str | None:
        payload = message.as_dict()
        validate_channel_message(payload)
        with self._state_lock:
            if self.allowed_users and runtime_user_id(payload) not in self.allowed_users:
                LOGGER.info("Rejected channel message channel=%s tenant=%s", message.channel, message.tenant_id)
                return None

            dedupe_key = (message.channel, message.tenant_id, message.message_id)
            if dedupe_key in self._seen_messages:
                LOGGER.info("Ignored duplicate channel message channel=%s tenant=%s", message.channel, message.tenant_id)
                return None
            self._seen_messages.add(dedupe_key)

        command = _command_name(message.text)
        if command in {"/start", "/help"}:
            return HELP_TEXT
        key = session_id(payload)
        if command == "/new":
            with self._state_lock:
                self._sessions[key] = f"session-{uuid.uuid4().hex}"
            return NEW_SESSION_TEXT

        with self._state_lock:
            active_session = self._sessions.setdefault(key, key)
        try:
            response = self.invoke(active_session, runtime_user_id(payload), message.text)
        except (HarnessStreamError, RuntimeError, ContractError) as error:
            LOGGER.info("Harness invocation failed class=%s", type(error).__name__)
            return SAFE_FAILURE_TEXT
        return response or EMPTY_RESPONSE_TEXT


def _command_name(text: str) -> str | None:
    if not text.startswith("/"):
        return None
    return text.split(maxsplit=1)[0].split("@", maxsplit=1)[0]


def invoke_harness(client: Any, harness_arn: str, session_id: str, user_id: str, text: str) -> str:
    """Invoke an IAM-authorized Harness and return only text deltas."""
    response = client.invoke_harness(
        harnessArn=harness_arn,
        runtimeSessionId=session_id,
        actorId=user_id,
        messages=[{"role": "user", "content": [{"text": text}]}],
    )
    chunks: list[str] = []
    for event in response["stream"]:
        delta = event.get("contentBlockDelta", {}).get("delta", {})
        if isinstance(delta.get("text"), str):
            chunks.append(delta["text"])
        for error_name in ("runtimeClientError", "internalServerException", "validationException"):
            if error_name in event:
                raise HarnessStreamError(error_name)
    return "".join(chunks)
