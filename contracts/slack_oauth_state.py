"""Signed, expiring Slack OAuth installation state.

The public callback (`services/slack_oauth_callback`) must bind an inbound
`code` to the exact agent, workspace, Slack App, and redirect URI that started
the installation, without a server-side session store. `sign_state` and
`verify_state` are the single source of truth for that binding; both the
install-URL generator (`clients.slack.reconciliation`) and the callback Lambda
import this module so the format never drifts between the two sides.

Verification looks up the per-agent signing key using the *unverified* agent
name carried in the token (`unverified_agent_name`), then checks the HMAC
under that key -- the same "unverified key-id selects key material, then
verify" pattern used by multi-tenant JWT `kid` lookups. A forged token for
agent A can only be produced by someone who already holds agent A's
`state_signing_key`; a token that names the wrong agent fails signature
verification once checked against that agent's real key.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

DEFAULT_TTL_SECONDS = 600
_VERSION = 1
_AGENT_NAME = re.compile(r"^[a-z][a-z0-9-]{0,38}[a-z0-9]$")
_WORKSPACE_ID = re.compile(r"^T[A-Z0-9]+$")
_APP_ID = re.compile(r"^A[A-Z0-9]+$")


class StateError(ValueError):
    """State is missing, malformed, expired, tampered, or bound elsewhere.

    The message is safe to log or return to a caller: it never includes the
    raw token, signing key, or decoded payload.
    """


@dataclass(frozen=True)
class OAuthState:
    agent_name: str
    workspace_id: str
    app_id: str
    redirect_uri: str
    issued_at: int
    expires_at: int


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    if not isinstance(data, str) or not data or not re.fullmatch(r"[A-Za-z0-9_-]+", data):
        raise StateError("state is malformed")
    padding = "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(data + padding)
    except (binascii.Error, ValueError) as error:
        raise StateError("state is malformed") from error


def _signature(payload_b64: str, signing_key: str) -> bytes:
    return hmac.new(signing_key.encode("utf-8"), payload_b64.encode("ascii"), sha256).digest()


def sign_state(
    *,
    agent_name: str,
    workspace_id: str,
    app_id: str,
    redirect_uri: str,
    signing_key: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: int | None = None,
) -> str:
    if not _AGENT_NAME.fullmatch(agent_name):
        raise StateError("agent name is invalid")
    if not _WORKSPACE_ID.fullmatch(workspace_id):
        raise StateError("workspace id is invalid")
    if not _APP_ID.fullmatch(app_id):
        raise StateError("app id is invalid")
    if not isinstance(redirect_uri, str) or not redirect_uri.startswith("https://"):
        raise StateError("redirect uri is invalid")
    if not isinstance(signing_key, str) or len(signing_key) < 32:
        raise StateError("signing key is invalid")
    if ttl_seconds <= 0:
        raise StateError("ttl_seconds must be positive")
    issued_at = int(now if now is not None else time.time())
    payload: dict[str, Any] = {
        "v": _VERSION,
        "agent": agent_name,
        "workspace_id": workspace_id,
        "app_id": app_id,
        "redirect_uri": redirect_uri,
        "iat": issued_at,
        "exp": issued_at + ttl_seconds,
        "nonce": secrets.token_hex(8),
    }
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    return f"{payload_b64}.{_b64url_encode(_signature(payload_b64, signing_key))}"


def unverified_agent_name(token: str) -> str:
    """Return the claimed agent name without checking the signature.

    Callers must use this only as an SSM-path lookup key to find the
    candidate signing key, then call `verify_state` before trusting anything
    else about the token. The regex rejects any value unsafe to interpolate
    into an SSM parameter path.
    """
    payload = _decode_payload(token)
    agent_name = payload.get("agent")
    if not isinstance(agent_name, str) or not _AGENT_NAME.fullmatch(agent_name):
        raise StateError("state is malformed")
    return agent_name


def _decode_payload(token: str) -> dict[str, Any]:
    if not isinstance(token, str) or token.count(".") != 1:
        raise StateError("state is malformed")
    payload_b64, _ = token.split(".", 1)
    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except json.JSONDecodeError as error:
        raise StateError("state is malformed") from error
    if not isinstance(payload, dict):
        raise StateError("state is malformed")
    return payload


def verify_state(
    token: str,
    *,
    signing_key: str,
    workspace_id: str | None = None,
    app_id: str | None = None,
    redirect_uri: str | None = None,
    now: int | None = None,
) -> OAuthState:
    """Verify signature, shape, and expiry; optionally pin expected fields.

    Raises `StateError` on any failure. Never include the raw token or
    signing key in the exception message.
    """
    if not isinstance(token, str) or token.count(".") != 1:
        raise StateError("state is malformed")
    payload_b64, signature_b64 = token.split(".", 1)
    expected = _signature(payload_b64, signing_key)
    provided = _b64url_decode(signature_b64)
    if not hmac.compare_digest(expected, provided):
        raise StateError("state signature is invalid")

    payload = json.loads(_b64url_decode(payload_b64))
    if not isinstance(payload, dict):
        raise StateError("state is malformed")
    if payload.get("v") != _VERSION:
        raise StateError("state version is unsupported")

    agent_name = payload.get("agent")
    state_workspace_id = payload.get("workspace_id")
    state_app_id = payload.get("app_id")
    state_redirect_uri = payload.get("redirect_uri")
    issued_at = payload.get("iat")
    expires_at = payload.get("exp")
    if not isinstance(agent_name, str) or not _AGENT_NAME.fullmatch(agent_name):
        raise StateError("state is malformed")
    if not isinstance(state_workspace_id, str) or not _WORKSPACE_ID.fullmatch(state_workspace_id):
        raise StateError("state is malformed")
    if not isinstance(state_app_id, str) or not _APP_ID.fullmatch(state_app_id):
        raise StateError("state is malformed")
    if not isinstance(state_redirect_uri, str) or not state_redirect_uri.startswith("https://"):
        raise StateError("state is malformed")
    if not isinstance(issued_at, int) or not isinstance(expires_at, int) or expires_at <= issued_at:
        raise StateError("state is malformed")

    current = int(now if now is not None else time.time())
    if current >= expires_at:
        raise StateError("state has expired")
    if current < issued_at:
        raise StateError("state is malformed")

    if workspace_id is not None and state_workspace_id != workspace_id:
        raise StateError("state does not match the expected workspace")
    if app_id is not None and state_app_id != app_id:
        raise StateError("state does not match the expected app")
    if redirect_uri is not None and state_redirect_uri != redirect_uri:
        raise StateError("state does not match the expected redirect uri")

    return OAuthState(
        agent_name=agent_name,
        workspace_id=state_workspace_id,
        app_id=state_app_id,
        redirect_uri=state_redirect_uri,
        issued_at=issued_at,
        expires_at=expires_at,
    )
