"""Safe parsing and presentation of project-owned synthetic OAuth stream events.

The live AgentCore OAuth envelope is intentionally unknown until GH-010 records
a redacted event shape. Unknown stream events are ignored by this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Mapping
from urllib.parse import urlsplit


SENSITIVE_KEY_PARTS = ("token", "code", "secret", "password", "credential", "key")


@dataclass(frozen=True)
class OAuthEvent:
    status: str
    authorization_url: str | None = None


@dataclass
class OAuthPresentationState:
    shown_url_digests: set[str] = field(default_factory=set)

    def show_once(self, url: str) -> bool:
        digest = sha256(url.encode("utf-8")).hexdigest()
        if digest in self.shown_url_digests:
            return False
        self.shown_url_digests.add(digest)
        return True


def _authorization_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    return value


def parse_oauth_event(event: object) -> OAuthEvent | None:
    """Parse only the project-owned synthetic OAuth envelopes.

    Supported provisional app-defined envelopes are ``{"type":
    "authorization_required", "authorization_url": "https://..."}``,
    ``{"type": "authorization_pending"}``, and ``{"type":
    "authorization_failed"}``. They are not a claimed AgentCore Harness schema.
    Do not infer OAuth state from arbitrary nested events or URLs before GH-010
    supplies a redacted live fixture.
    """

    if not isinstance(event, Mapping):
        return None
    event_type = event.get("type")
    if event_type == "authorization_required":
        url = _authorization_url(event.get("authorization_url"))
        return OAuthEvent("authorization_required", url) if url else None
    if event_type == "authorization_pending":
        return OAuthEvent("pending")
    if event_type == "authorization_failed":
        return OAuthEvent("failed")
    return None


def sanitize_for_diagnostics(value: object) -> object:
    """Recursively remove credential-like values and all URL query/fragment data."""

    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, child in value.items():
            key_text = str(key)
            if any(part in key_text.lower() for part in SENSITIVE_KEY_PARTS):
                result[key_text] = "<redacted>"
            else:
                result[key_text] = sanitize_for_diagnostics(child)
        return result
    if isinstance(value, list):
        return [sanitize_for_diagnostics(child) for child in value]
    if isinstance(value, str):
        parsed = urlsplit(value)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            try:
                port = f":{parsed.port}" if parsed.port else ""
            except ValueError:
                port = ""
            return f"{parsed.scheme}://{parsed.hostname or '<invalid-host>'}{port}<redacted-url-data>"
    return value


def oauth_user_message(event: OAuthEvent, state: OAuthPresentationState) -> list[str]:
    """Return normal UX; URLs are never returned by diagnostic helpers."""

    if event.status == "authorization_required":
        messages = ["GitHub authorization is required. Authorize, return here, then retry the same request."]
        if event.authorization_url and state.show_once(event.authorization_url):
            messages.append(event.authorization_url)
        return messages
    if event.status == "pending":
        return ["GitHub authorization is pending. Complete authorization, return here, then retry the same request."]
    return ["GitHub authorization failed. Start authorization again, then retry the same request."]


def safe_runtime_error_summary(error_name: str) -> str:
    return f"AgentCore returned {error_name}."
