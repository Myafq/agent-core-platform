"""Public Slack OAuth installation callback.

This is the *only* public entrypoint in the Slack slice: Socket Mode owns
runtime events, and this Lambda exists solely to complete `GET
/slack/oauth/callback` after a human approves installation. It reads and
writes the exact same per-agent SSM hierarchy that
`clients.slack.reconciliation` and `clients.slack.launcher` already own
(`/agent-core/slack/agents/<name>/{binding,credentials}`) -- this module adds
no new credential model, only a narrowly scoped public path to that existing
schema. It is intentionally self-contained (stdlib plus the AWS-provided
boto3 runtime, no `clients` import) so its Lambda package stays small and its
IAM role stays easy to reason about.

Never log or return the authorization code, client secret, signing secret,
state signing key, bot token, or raw query string / state token.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol

from contracts.slack_oauth_state import StateError, unverified_agent_name, verify_state

LOG = logging.getLogger(__name__)
DEFAULT_BINDING_PREFIX = "/agent-core/slack/agents"
SSM_KEY_ID = "alias/aws/ssm"
_CREDENTIAL_KEYS = frozenset({"client_id", "client_secret", "signing_secret", "state_signing_key", "bot_token", "app_token"})
_REQUIRED_BINDING_FIELDS = (
    "agent_name",
    "workspace_id",
    "app_id",
    "manifest_digest",
    "installation_state",
    "last_successful_reconcile_at",
)
_APP_ID = re.compile(r"^A[A-Z0-9]+$")
_WORKSPACE_ID = re.compile(r"^T[A-Z0-9]+$")
# Slack's documented, non-sensitive `error` values for the OAuth callback.
# Anything else is logged as a generic "provider_error" rather than echoing
# an attacker-controlled string into logs.
_KNOWN_SLACK_ERRORS = frozenset({"access_denied"})


class CallbackError(Exception):
    """A safe, user-facing installation failure.

    `safe_message` is plain text intended for direct HTML rendering (the
    caller still escapes it). `log_class` is a fixed, bounded label safe to
    write to CloudWatch; it never contains request-supplied text.
    """

    def __init__(self, safe_message: str, *, log_class: str) -> None:
        super().__init__(log_class)
        self.safe_message = safe_message
        self.log_class = log_class


class ParameterStore(Protocol):
    def get(self, name: str, *, decrypt: bool) -> str | None: ...

    def put_secure_json(self, name: str, value: Mapping[str, str]) -> None: ...

    def put_binding(self, name: str, value: Mapping[str, str]) -> None: ...


class SlackOAuthClient(Protocol):
    def exchange(self, client_id: str, client_secret: str, code: str, redirect_uri: str) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class CallbackConfig:
    workspace_id: str
    redirect_uri: str
    binding_prefix: str = DEFAULT_BINDING_PREFIX

    @classmethod
    def from_environment(cls) -> "CallbackConfig":
        try:
            workspace_id = os.environ["SLACK_WORKSPACE_ID"]
            redirect_uri = os.environ["SLACK_OAUTH_REDIRECT_URI"]
        except KeyError as error:
            raise CallbackError("Installation could not be completed.", log_class="config_missing") from error
        prefix = os.environ.get("SLACK_AGENT_PARAMETER_PREFIX", DEFAULT_BINDING_PREFIX)
        if not _WORKSPACE_ID.fullmatch(workspace_id):
            raise CallbackError("Installation could not be completed.", log_class="config_invalid")
        if not redirect_uri.startswith("https://"):
            raise CallbackError("Installation could not be completed.", log_class="config_invalid")
        return cls(workspace_id=workspace_id, redirect_uri=redirect_uri, binding_prefix=prefix.rstrip("/"))


@dataclass(frozen=True)
class InstallationResult:
    """Nonsecret fields kept for audit; never includes a token or secret."""

    agent_name: str
    workspace_id: str
    app_id: str
    bot_user_id: str | None
    granted_scopes: tuple[str, ...]
    installed_at: str


class UrllibSlackOAuthClient:
    """Fixed-host Slack OAuth client; callers cannot supply a URL or header."""

    endpoint = "https://slack.com/api/oauth.v2.access"

    def exchange(self, client_id: str, client_secret: str, code: str, redirect_uri: str) -> Mapping[str, Any]:
        body = urllib.parse.urlencode(
            {"client_id": client_id, "client_secret": client_secret, "code": code, "redirect_uri": redirect_uri}
        ).encode("ascii")
        request = urllib.request.Request(
            self.endpoint, data=body, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise CallbackError("Slack could not be reached. Try again shortly.", log_class="slack_unavailable") from error
        if not isinstance(payload, dict):
            raise CallbackError("Slack could not be reached. Try again shortly.", log_class="slack_unavailable")
        return payload


class SsmParameterStore:
    """Thin boto3 adapter matching `clients.slack.reconciliation`'s SSM shape."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def get(self, name: str, *, decrypt: bool) -> str | None:
        try:
            response = self.client.get_parameter(Name=name, WithDecryption=decrypt)
        except self.client.exceptions.ParameterNotFound:
            return None
        value = response.get("Parameter", {}).get("Value")
        return value if isinstance(value, str) else None

    def put_secure_json(self, name: str, value: Mapping[str, str]) -> None:
        self.client.put_parameter(
            Name=name,
            Value=json.dumps(dict(value), separators=(",", ":"), sort_keys=True),
            Type="SecureString",
            KeyId=SSM_KEY_ID,
            Tier="Standard",
            Overwrite=True,
        )

    def put_binding(self, name: str, value: Mapping[str, str]) -> None:
        self.client.put_parameter(
            Name=name,
            Value=json.dumps(dict(value), separators=(",", ":"), sort_keys=True),
            Type="String",
            Tier="Standard",
            Overwrite=True,
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_binding(raw: str) -> dict[str, str]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise CallbackError("This installation link is invalid.", log_class="binding_corrupt") from error
    if not isinstance(value, dict) or not all(isinstance(key, str) and isinstance(item, str) for key, item in value.items()):
        raise CallbackError("This installation link is invalid.", log_class="binding_corrupt")
    if any(not value.get(field) for field in _REQUIRED_BINDING_FIELDS):
        raise CallbackError("This installation link is invalid.", log_class="binding_corrupt")
    if not _APP_ID.fullmatch(value["app_id"]):
        raise CallbackError("This installation link is invalid.", log_class="binding_corrupt")
    return value


def _parse_credentials(raw: str) -> dict[str, str]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise CallbackError("This installation link is invalid.", log_class="credentials_corrupt") from error
    if not isinstance(value, dict) or not all(isinstance(key, str) and isinstance(item, str) and item for key, item in value.items()):
        raise CallbackError("This installation link is invalid.", log_class="credentials_corrupt")
    if set(value) - _CREDENTIAL_KEYS:
        raise CallbackError("This installation link is invalid.", log_class="credentials_corrupt")
    return value


def complete_installation(
    query: Mapping[str, str],
    parameters: ParameterStore,
    oauth: SlackOAuthClient,
    config: CallbackConfig,
    *,
    now: Callable[[], str] = _utc_now,
) -> InstallationResult:
    """Verify, exchange, and persist one Slack installation.

    Raises `CallbackError` with a safe, user-facing message on every failure
    path. No SSM write happens until state verification, the Slack exchange,
    and the returned identity have all passed -- a duplicate or replayed
    callback either fails those checks (a consumed authorization code is
    rejected by Slack) or, for an exact repeat, simply re-persists the same
    already-correct values.
    """
    error = query.get("error")
    if error:
        log_class = "user_denied" if error in _KNOWN_SLACK_ERRORS else "provider_error"
        raise CallbackError("Slack installation was not approved.", log_class=log_class)

    state_token = query.get("state")
    code = query.get("code")
    if not state_token or not code:
        raise CallbackError("This installation link is invalid or incomplete.", log_class="request_invalid")

    try:
        claimed_agent_name = unverified_agent_name(state_token)
    except StateError:
        raise CallbackError("This installation link is invalid.", log_class="state_malformed") from None

    binding_path = f"{config.binding_prefix}/{claimed_agent_name}/binding"
    credentials_path = f"{config.binding_prefix}/{claimed_agent_name}/credentials"

    binding_raw = parameters.get(binding_path, decrypt=False)
    if binding_raw is None:
        raise CallbackError("This installation link is invalid.", log_class="binding_missing")
    binding = _parse_binding(binding_raw)

    credentials_raw = parameters.get(credentials_path, decrypt=True)
    if credentials_raw is None:
        raise CallbackError("This installation link is invalid.", log_class="credentials_missing")
    credentials = _parse_credentials(credentials_raw)

    signing_key = credentials.get("state_signing_key")
    if not signing_key:
        raise CallbackError("This installation link is invalid.", log_class="signing_key_missing")

    try:
        state = verify_state(
            state_token,
            signing_key=signing_key,
            workspace_id=config.workspace_id,
            app_id=binding["app_id"],
            redirect_uri=config.redirect_uri,
        )
    except StateError:
        raise CallbackError(
            "This installation link has expired or is no longer valid. Request a new one.", log_class="state_invalid"
        ) from None

    if state.agent_name != binding["agent_name"] or state.agent_name != claimed_agent_name:
        raise CallbackError("This installation link is invalid.", log_class="identity_mismatch")

    client_id = credentials.get("client_id")
    client_secret = credentials.get("client_secret")
    if not client_id or not client_secret:
        raise CallbackError("This installation link is invalid.", log_class="credentials_incomplete")

    response = oauth.exchange(client_id, client_secret, code, config.redirect_uri)
    if response.get("ok") is not True:
        raise CallbackError(
            "Slack could not complete the installation. The link may already have been used.",
            log_class="exchange_failed",
        )

    response_app_id = response.get("app_id")
    if isinstance(response_app_id, str) and response_app_id and response_app_id != binding["app_id"]:
        raise CallbackError("Installation could not be verified.", log_class="app_mismatch")

    team = response.get("team")
    team_id = team.get("id") if isinstance(team, Mapping) else None
    if team_id != config.workspace_id:
        raise CallbackError("Installation could not be verified.", log_class="workspace_mismatch")

    bot_token = response.get("access_token")
    if not isinstance(bot_token, str) or not bot_token:
        raise CallbackError("Installation could not be verified.", log_class="bot_token_missing")

    bot_user_id = response.get("bot_user_id")
    bot_user_id = bot_user_id if isinstance(bot_user_id, str) and bot_user_id else None
    scope = response.get("scope")
    granted_scopes = tuple(scope.split(",")) if isinstance(scope, str) and scope else ()

    updated_credentials = dict(credentials)
    updated_credentials["bot_token"] = bot_token

    installed_at = now()
    updated_binding = dict(binding)
    updated_binding["installation_state"] = "installed"
    updated_binding["last_successful_reconcile_at"] = installed_at
    if bot_user_id:
        updated_binding["bot_user_id"] = bot_user_id
    if granted_scopes:
        updated_binding["granted_scopes"] = ",".join(granted_scopes)

    try:
        parameters.put_secure_json(credentials_path, updated_credentials)
    except Exception as write_error:
        raise CallbackError(
            "Installation credentials were not saved. Try installing again.", log_class="credentials_write_failed"
        ) from write_error
    try:
        parameters.put_binding(binding_path, updated_binding)
    except Exception as write_error:
        raise CallbackError(
            "Installation credentials were saved but installation state was not recorded. "
            "Contact the operator before retrying.",
            log_class="binding_write_failed",
        ) from write_error

    return InstallationResult(
        agent_name=claimed_agent_name,
        workspace_id=config.workspace_id,
        app_id=binding["app_id"],
        bot_user_id=bot_user_id,
        granted_scopes=granted_scopes,
        installed_at=installed_at,
    )
