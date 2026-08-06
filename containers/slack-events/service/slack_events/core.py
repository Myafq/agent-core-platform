"""Secret-safe Slack Events validation, dispatch, and worker behavior."""

from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import hmac
import json
import re
import time
from typing import Any, Mapping, Protocol

from clients.channel.core import (
    ChannelMessage,
    EMPTY_RESPONSE_TEXT,
    HELP_TEXT,
    NEW_SESSION_TEXT,
    SAFE_FAILURE_TEXT,
    HarnessStreamError,
    _command_name,
    runtime_user_id,
    session_id,
)


DEFAULT_PARAMETER_PREFIX = "/agent-core/slack/agents"
SIGNATURE_VERSION = "v0"
REPLAY_WINDOW_SECONDS = 300
_AGENT_NAME = re.compile(r"^[a-z][a-z0-9-]{0,38}[a-z0-9]$")
_APP_ID = re.compile(r"^A[A-Z0-9]+$")
_WORKSPACE_ID = re.compile(r"^T[A-Z0-9]+$")


class SlackEventsError(Exception):
    """A bounded failure class safe to log."""

    def __init__(self, log_class: str) -> None:
        super().__init__(log_class)
        self.log_class = log_class


class ParameterReader(Protocol):
    def get(self, name: str, *, decrypt: bool) -> str | None: ...


class EventDispatcher(Protocol):
    def dispatch(self, envelope: Mapping[str, Any]) -> None: ...


class SlackStateStore(Protocol):
    def claim_event(self, tenant_id: str, event_id: str) -> bool: ...

    def complete_event(self, tenant_id: str, event_id: str) -> None: ...

    def release_event(self, tenant_id: str, event_id: str) -> None: ...

    def has_thread(self, tenant_id: str, channel_id: str, thread_ts: str) -> bool: ...

    def register_thread(self, tenant_id: str, channel_id: str, thread_ts: str) -> None: ...

    def get_active_session(self, tenant_id: str, conversation_id: str) -> str | None: ...

    def set_active_session(self, tenant_id: str, conversation_id: str, active_session: str) -> None: ...


class HarnessInvoker(Protocol):
    def invoke(self, harness_arn: str, runtime_session_id: str, runtime_user_id: str, text: str) -> str: ...


class SlackPoster(Protocol):
    def post(self, bot_token: str, channel_id: str, thread_ts: str, text: str) -> None: ...


@dataclass(frozen=True)
class SlackBinding:
    agent_name: str
    workspace_id: str
    app_id: str
    installation_state: str
    bot_user_id: str | None


@dataclass(frozen=True)
class SlackCredentials:
    signing_secret: str
    bot_token: str | None


@dataclass(frozen=True)
class SlackAgent:
    binding: SlackBinding
    credentials: SlackCredentials


def _json_object(raw: str, error_class: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as error:
        raise SlackEventsError(error_class) from error
    if not isinstance(value, dict):
        raise SlackEventsError(error_class)
    return value


def _required(value: Mapping[str, Any], field: str, error_class: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item:
        raise SlackEventsError(error_class)
    return item


def agent_parameter_paths(agent_name: str, prefix: str = DEFAULT_PARAMETER_PREFIX) -> tuple[str, str]:
    if not _AGENT_NAME.fullmatch(agent_name):
        raise SlackEventsError("agent_invalid")
    base = f"{prefix.rstrip('/')}/{agent_name}"
    return f"{base}/binding", f"{base}/credentials"


def load_agent(reader: ParameterReader, agent_name: str, prefix: str = DEFAULT_PARAMETER_PREFIX) -> SlackAgent:
    binding_path, credentials_path = agent_parameter_paths(agent_name, prefix)
    binding_raw = reader.get(binding_path, decrypt=False)
    credentials_raw = reader.get(credentials_path, decrypt=True)
    if binding_raw is None or credentials_raw is None:
        raise SlackEventsError("agent_unavailable")
    binding_value = _json_object(binding_raw, "binding_invalid")
    credentials_value = _json_object(credentials_raw, "credentials_invalid")
    binding = SlackBinding(
        agent_name=_required(binding_value, "agent_name", "binding_invalid"),
        workspace_id=_required(binding_value, "workspace_id", "binding_invalid"),
        app_id=_required(binding_value, "app_id", "binding_invalid"),
        installation_state=_required(binding_value, "installation_state", "binding_invalid"),
        bot_user_id=binding_value.get("bot_user_id") if isinstance(binding_value.get("bot_user_id"), str) else None,
    )
    if (
        binding.agent_name != agent_name
        or not _WORKSPACE_ID.fullmatch(binding.workspace_id)
        or not _APP_ID.fullmatch(binding.app_id)
        or binding.installation_state not in {"installed", "socket_mode_ready"}
    ):
        raise SlackEventsError("binding_invalid")
    return SlackAgent(
        binding=binding,
        credentials=SlackCredentials(
            signing_secret=_required(credentials_value, "signing_secret", "credentials_invalid"),
            bot_token=credentials_value.get("bot_token") if isinstance(credentials_value.get("bot_token"), str) else None,
        ),
    )


def raw_http_body(event: Mapping[str, Any]) -> bytes:
    body = event.get("body")
    if not isinstance(body, str):
        raise SlackEventsError("body_invalid")
    try:
        return base64.b64decode(body, validate=True) if event.get("isBase64Encoded") else body.encode("utf-8")
    except (UnicodeEncodeError, ValueError) as error:
        raise SlackEventsError("body_invalid") from error


def request_headers(event: Mapping[str, Any]) -> dict[str, str]:
    raw = event.get("headers")
    if not isinstance(raw, Mapping):
        raise SlackEventsError("headers_invalid")
    return {key.lower(): value for key, value in raw.items() if isinstance(key, str) and isinstance(value, str)}


def verify_slack_signature(headers: Mapping[str, str], raw_body: bytes, signing_secret: str, *, now: int | None = None) -> None:
    timestamp = headers.get("x-slack-request-timestamp")
    received = headers.get("x-slack-signature")
    if not timestamp or not received:
        raise SlackEventsError("signature_missing")
    try:
        request_time = int(timestamp)
    except ValueError as error:
        raise SlackEventsError("timestamp_invalid") from error
    current_time = int(time.time()) if now is None else now
    if abs(current_time - request_time) > REPLAY_WINDOW_SECONDS:
        raise SlackEventsError("timestamp_stale")
    signed = f"{SIGNATURE_VERSION}:{timestamp}:".encode("ascii") + raw_body
    expected = SIGNATURE_VERSION + "=" + hmac.new(signing_secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise SlackEventsError("signature_invalid")


def _payload(raw_body: bytes) -> dict[str, Any]:
    try:
        decoded = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SlackEventsError("payload_invalid") from error
    if not isinstance(decoded, dict):
        raise SlackEventsError("payload_invalid")
    return decoded


def _string(value: Mapping[str, Any], key: str) -> str | None:
    item = value.get(key)
    return item if isinstance(item, str) and item else None


def normalized_event(payload: Mapping[str, Any], agent: SlackAgent) -> dict[str, Any] | None:
    if payload.get("type") == "url_verification":
        return None
    if payload.get("type") != "event_callback":
        raise SlackEventsError("payload_type_invalid")
    # `socket_mode_ready` is accepted by load_agent only so a currently live
    # Socket Mode binding can complete signed URL verification during cutover.
    # Runtime Events delivery requires the reconciler-owned `installed` state.
    if agent.binding.installation_state != "installed":
        raise SlackEventsError("events_not_ready")
    if payload.get("team_id") != agent.binding.workspace_id or payload.get("api_app_id") != agent.binding.app_id:
        raise SlackEventsError("routing_invalid")
    event = payload.get("event")
    event_id = _string(payload, "event_id")
    if not isinstance(event, Mapping) or not event_id:
        raise SlackEventsError("event_invalid")
    event_type = _string(event, "type")
    channel_type = _string(event, "channel_type")
    if event_type not in {"app_mention", "message"}:
        return None
    if not all(_string(event, key) for key in ("user", "channel", "ts", "text")):
        return None
    return {
        "version": 1,
        "agent": agent.binding.agent_name,
        "workspace_id": agent.binding.workspace_id,
        "app_id": agent.binding.app_id,
        "bot_user_id": agent.binding.bot_user_id,
        "event_id": event_id,
        "event": {
            "type": event_type,
            "channel_type": channel_type,
            "user": _string(event, "user"),
            "channel": _string(event, "channel"),
            "ts": _string(event, "ts"),
            "thread_ts": _string(event, "thread_ts"),
            "text": _string(event, "text"),
            "subtype": _string(event, "subtype"),
            "bot_id": _string(event, "bot_id"),
        },
    }


def ingress_response(event: Mapping[str, Any], reader: ParameterReader, dispatcher: EventDispatcher, *, prefix: str, now: int) -> dict[str, Any]:
    parameters = event.get("pathParameters")
    agent_name = parameters.get("agent") if isinstance(parameters, Mapping) else None
    if not isinstance(agent_name, str):
        raw_path = event.get("rawPath")
        path_prefix = "/slack/events/"
        if isinstance(raw_path, str) and raw_path.startswith(path_prefix):
            candidate = raw_path[len(path_prefix) :]
            if candidate and "/" not in candidate:
                agent_name = candidate
    if not isinstance(agent_name, str):
        raise SlackEventsError("agent_invalid")
    agent = load_agent(reader, agent_name, prefix)
    raw_body = raw_http_body(event)
    verify_slack_signature(request_headers(event), raw_body, agent.credentials.signing_secret, now=now)
    payload = _payload(raw_body)
    if payload.get("type") == "url_verification":
        if (
            payload.get("api_app_id") not in {None, agent.binding.app_id}
            or not isinstance(payload.get("challenge"), str)
        ):
            raise SlackEventsError("routing_invalid")
        return {"statusCode": 200, "headers": {"Content-Type": "text/plain"}, "body": payload["challenge"]}
    envelope = normalized_event(payload, agent)
    if envelope is not None:
        dispatcher.dispatch(envelope)
    return {"statusCode": 200, "headers": {"Content-Type": "application/json"}, "body": "{\"ok\":true}"}


def state_hash(*values: str) -> str:
    return hashlib.sha256("\x1f".join(values).encode("utf-8")).hexdigest()


class InMemorySlackState:
    """Test implementation; production state must use hashed durable records."""

    def __init__(self) -> None:
        self.claimed: set[str] = set()
        self.completed: set[str] = set()
        self.threads: set[str] = set()
        self.sessions: dict[str, str] = {}

    def claim_event(self, tenant_id: str, event_id: str) -> bool:
        key = state_hash(tenant_id, event_id)
        if key in self.claimed or key in self.completed:
            return False
        self.claimed.add(key)
        return True

    def complete_event(self, tenant_id: str, event_id: str) -> None:
        key = state_hash(tenant_id, event_id)
        self.claimed.discard(key)
        self.completed.add(key)

    def release_event(self, tenant_id: str, event_id: str) -> None:
        self.claimed.discard(state_hash(tenant_id, event_id))

    def has_thread(self, tenant_id: str, channel_id: str, thread_ts: str) -> bool:
        return state_hash(tenant_id, channel_id, thread_ts) in self.threads

    def register_thread(self, tenant_id: str, channel_id: str, thread_ts: str) -> None:
        self.threads.add(state_hash(tenant_id, channel_id, thread_ts))

    def get_active_session(self, tenant_id: str, conversation_id: str) -> str | None:
        return self.sessions.get(state_hash(tenant_id, conversation_id))

    def set_active_session(self, tenant_id: str, conversation_id: str, active_session: str) -> None:
        self.sessions[state_hash(tenant_id, conversation_id)] = active_session


class SlackWorker:
    def __init__(self, state: SlackStateStore, harness: HarnessInvoker, poster: SlackPoster) -> None:
        self.state = state
        self.harness = harness
        self.poster = poster

    def process(self, envelope: Mapping[str, Any], *, harness_arn: str, bot_token: str) -> None:
        agent = _required(envelope, "agent", "queue_invalid")
        workspace_id = _required(envelope, "workspace_id", "queue_invalid")
        app_id = _required(envelope, "app_id", "queue_invalid")
        event_id = _required(envelope, "event_id", "queue_invalid")
        event = envelope.get("event")
        if envelope.get("version") != 1 or not isinstance(event, Mapping):
            raise SlackEventsError("queue_invalid")
        tenant_id = f"{workspace_id}:{app_id}"
        if not self.state.claim_event(tenant_id, event_id):
            return
        try:
            bot_user_id = envelope.get("bot_user_id")
            message = self._message(event, workspace_id, app_id, bot_user_id if isinstance(bot_user_id, str) else None)
            if message is not None:
                reply = self._reply(message, tenant_id, harness_arn)
                if reply is not None:
                    self.poster.post(bot_token, message.channel_id, message.thread_ts, reply)
            self.state.complete_event(tenant_id, event_id)
        except Exception:
            self.state.release_event(tenant_id, event_id)
            raise

    def _message(
        self, event: Mapping[str, Any], workspace_id: str, app_id: str, bot_user_id: str | None
    ) -> "WorkerMessage | None":
        event_type = _string(event, "type")
        channel_type = _string(event, "channel_type")
        if event_type not in {"app_mention", "message"} or _string(event, "subtype") or _string(event, "bot_id"):
            return None
        is_direct = event_type == "message" and channel_type == "im"
        is_mention = event_type == "app_mention"
        is_followup = event_type == "message" and channel_type in {"channel", "group"} and _string(event, "thread_ts")
        user_id, channel_id, message_ts, text = (_string(event, key) for key in ("user", "channel", "ts", "text"))
        thread_ts = _string(event, "thread_ts") or message_ts
        if not (is_direct or is_mention or is_followup) or not all((user_id, channel_id, message_ts, text, thread_ts)):
            return None
        normalized_text = text.strip()
        if is_mention:
            if not bot_user_id:
                return None
            normalized_text = re.sub(
                rf"<@{re.escape(bot_user_id)}(?:\|[^>]+)?>", "", normalized_text, count=1
            ).strip()
        if not normalized_text:
            return None
        tenant_id = f"{workspace_id}:{app_id}"
        if is_mention:
            self.state.register_thread(tenant_id, channel_id, thread_ts)
        elif not is_direct and not self.state.has_thread(tenant_id, channel_id, thread_ts):
            return None
        return WorkerMessage(workspace_id, app_id, user_id, channel_id, message_ts, thread_ts, normalized_text)

    def _reply(self, message: "WorkerMessage", tenant_id: str, harness_arn: str) -> str | None:
        channel_message = ChannelMessage(
            "slack", tenant_id, message.user_id, f"{message.channel_id}:{message.thread_ts}", message.message_id, message.text
        )
        command = _command_name(message.text)
        if command in {"/start", "/help"}:
            return HELP_TEXT
        if command == "/new":
            self.state.set_active_session(tenant_id, channel_message.conversation_id, f"session-{state_hash(message.message_id)}")
            return NEW_SESSION_TEXT
        active_session = self.state.get_active_session(tenant_id, channel_message.conversation_id) or session_id(channel_message.as_dict())
        try:
            reply = self.harness.invoke(
                harness_arn, active_session, runtime_user_id(channel_message.as_dict()), channel_message.text
            )
        except (HarnessStreamError, RuntimeError, ValueError):
            return SAFE_FAILURE_TEXT
        return reply or EMPTY_RESPONSE_TEXT


@dataclass(frozen=True)
class WorkerMessage:
    workspace_id: str
    app_id: str
    user_id: str
    channel_id: str
    message_id: str
    thread_ts: str
    text: str
