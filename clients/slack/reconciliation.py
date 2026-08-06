"""Secret-safe Slack App manifest reconciliation primitives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
import secrets
import urllib.parse
from typing import Any, Callable, Mapping, Protocol, Sequence

from contracts.slack_oauth_state import DEFAULT_TTL_SECONDS, StateError, sign_state
from scripts.render_slack_manifest import slack_manifest


SSM_KEY_ID = "alias/aws/ssm"
SSM_STANDARD_VALUE_BYTES = 4096
STATE_SIGNING_KEY_BYTES = 32
_APP_ID = re.compile(r"A[A-Z0-9]+$")
_CREDENTIAL_KEYS = frozenset({"client_id", "client_secret", "signing_secret", "state_signing_key", "bot_token"})
_LEGACY_CREDENTIAL_KEYS = frozenset({"app_token"})


class ReconciliationError(RuntimeError):
    """A safe error suitable for command-line output."""


class AdoptionRequired(ReconciliationError):
    """An existing Slack App must be named explicitly before it can be used."""


class ParameterStore(Protocol):
    def get(self, name: str, *, decrypt: bool) -> str | None: ...

    def put_secure_json(self, name: str, value: Mapping[str, str]) -> None: ...

    def put_binding(self, name: str, value: Mapping[str, str]) -> None: ...


class SlackProvisionerApi(Protocol):
    def rotate_configuration_token(self, refresh_token: str) -> Mapping[str, Any]: ...

    def create_manifest(self, configuration_token: str, manifest: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def update_manifest(self, configuration_token: str, app_id: str, manifest: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def exchange_oauth_code(self, client_id: str, client_secret: str, code: str, redirect_uri: str) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class ParameterPaths:
    provisioner: str
    binding: str
    credentials: str


@dataclass(frozen=True)
class Binding:
    agent_name: str
    workspace_id: str
    app_id: str
    manifest_digest: str
    installation_state: str
    last_successful_reconcile_at: str
    bot_user_id: str | None = None
    granted_scopes: str | None = None

    @classmethod
    def from_json(cls, raw: str) -> "Binding":
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as error:
            raise AdoptionRequired("Slack binding is corrupt; provide --adopt-app-id with the exact App ID.") from error
        if not isinstance(value, dict):
            raise AdoptionRequired("Slack binding is corrupt; provide --adopt-app-id with the exact App ID.")
        fields = ("agent_name", "workspace_id", "app_id", "manifest_digest", "installation_state", "last_successful_reconcile_at")
        if any(not isinstance(value.get(field), str) or not value[field] for field in fields):
            raise AdoptionRequired("Slack binding is corrupt; provide --adopt-app-id with the exact App ID.")
        if not _APP_ID.fullmatch(value["app_id"]):
            raise AdoptionRequired("Slack binding is corrupt; provide --adopt-app-id with the exact App ID.")
        optional = {}
        for field in ("bot_user_id", "granted_scopes"):
            if field in value:
                if not isinstance(value[field], str) or not value[field]:
                    raise AdoptionRequired("Slack binding is corrupt; provide --adopt-app-id with the exact App ID.")
                optional[field] = value[field]
        return cls(**{field: value[field] for field in fields}, **optional)

    def as_json(self) -> dict[str, str]:
        value = {
            "agent_name": self.agent_name,
            "workspace_id": self.workspace_id,
            "app_id": self.app_id,
            "manifest_digest": self.manifest_digest,
            "installation_state": self.installation_state,
            "last_successful_reconcile_at": self.last_successful_reconcile_at,
        }
        if self.bot_user_id:
            value["bot_user_id"] = self.bot_user_id
        if self.granted_scopes:
            value["granted_scopes"] = self.granted_scopes
        return value


@dataclass(frozen=True)
class ReconcilePlan:
    action: str
    agent_name: str
    workspace_id: str
    app_id: str | None
    manifest_digest: str
    installation_state: str

    def safe_output(self) -> dict[str, str | None]:
        return {
            "action": self.action,
            "agent_name": self.agent_name,
            "workspace_id": self.workspace_id,
            "app_id": self.app_id,
            "manifest_digest": self.manifest_digest,
            "installation_state": self.installation_state,
        }


@dataclass(frozen=True)
class ReconcileResult:
    plan: ReconcilePlan
    install_url: str | None = None

    def safe_output(self) -> dict[str, str | None]:
        output = self.plan.safe_output()
        output["install_url"] = self.install_url
        return output


def manifest_digest(manifest: Mapping[str, Any]) -> str:
    canonical = json.dumps(manifest, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _install_url(client_id: str, bot_scopes: Sequence[str], redirect_uri: str, state: str) -> str:
    """Build Slack's OAuth v2 authorize URL directly.

    The URL returned by ``apps.manifest.create`` is a bare app-review link and
    cannot carry a caller-chosen ``state``; only the documented
    ``https://slack.com/oauth/v2/authorize`` endpoint accepts ``redirect_uri``
    and ``state`` as query parameters, so this is built explicitly rather than
    passed through from Slack's response.
    """
    query = urllib.parse.urlencode(
        {"client_id": client_id, "scope": ",".join(bot_scopes), "redirect_uri": redirect_uri, "state": state}
    )
    return f"https://slack.com/oauth/v2/authorize?{query}"


def _agent_name(spec: Mapping[str, Any]) -> str:
    name = spec.get("metadata", {}).get("name") if isinstance(spec.get("metadata"), Mapping) else None
    if not isinstance(name, str) or not name:
        raise ReconciliationError("Agent metadata.name is required.")
    return name


def _json_object(raw: str | None, parameter_kind: str) -> dict[str, str]:
    if raw is None:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ReconciliationError(f"Slack {parameter_kind} parameter is corrupt.") from error
    if not isinstance(value, dict) or any(not isinstance(key, str) or not isinstance(item, str) or not item for key, item in value.items()):
        raise ReconciliationError(f"Slack {parameter_kind} parameter is corrupt.")
    return value


def _required(value: Mapping[str, Any], field: str, source: str) -> str:
    result = value.get(field)
    if not isinstance(result, str) or not result:
        raise ReconciliationError(f"Slack {source} response is incomplete.")
    return result


def _valid_app_id(app_id: str) -> str:
    if not _APP_ID.fullmatch(app_id):
        raise ReconciliationError("Slack App ID is invalid.")
    return app_id


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parameter_json(value: Mapping[str, str]) -> str:
    encoded = json.dumps(dict(value), separators=(",", ":"), sort_keys=True)
    if len(encoded.encode("utf-8")) > SSM_STANDARD_VALUE_BYTES:
        raise ReconciliationError("Slack SSM parameter exceeds the Standard-tier value limit.")
    return encoded


class SsmParameterStore:
    """Thin boto3 adapter. Imported dependencies stay lazy for offline planning."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def get(self, name: str, *, decrypt: bool) -> str | None:
        try:
            response = self.client.get_parameter(Name=name, WithDecryption=decrypt)
        except self.client.exceptions.ParameterNotFound:
            return None
        value = response.get("Parameter", {}).get("Value")
        if not isinstance(value, str):
            raise ReconciliationError("Slack SSM parameter is unreadable.")
        return value

    def put_secure_json(self, name: str, value: Mapping[str, str]) -> None:
        self.client.put_parameter(
            Name=name,
            Value=_parameter_json(value),
            Type="SecureString",
            KeyId=SSM_KEY_ID,
            Tier="Standard",
            Overwrite=True,
        )

    def put_binding(self, name: str, value: Mapping[str, str]) -> None:
        self.client.put_parameter(
            Name=name,
            Value=_parameter_json(value),
            Type="String",
            Tier="Standard",
            Overwrite=True,
        )


class SlackSdkProvisionerApi:
    """Slack SDK adapter. Never logs API responses or token-bearing errors."""

    def _client(self, token: str | None = None) -> Any:
        try:
            from slack_sdk import WebClient
        except ModuleNotFoundError as error:
            raise ReconciliationError("Slack SDK is unavailable; install clients/cli/requirements.txt.") from error
        return WebClient(token=token)

    @staticmethod
    def _response(response: Any, operation: str) -> Mapping[str, Any]:
        data = dict(response.data) if hasattr(response, "data") else dict(response)
        if data.get("ok") is not True:
            raise ReconciliationError(f"Slack {operation} failed.")
        return data

    def _call(self, operation: str, request: Callable[[], Any]) -> Mapping[str, Any]:
        try:
            return self._response(request(), operation)
        except ReconciliationError:
            raise
        except Exception as error:
            raise ReconciliationError(f"Slack {operation} failed.") from error

    def rotate_configuration_token(self, refresh_token: str) -> Mapping[str, Any]:
        return self._call(
            "configuration token rotation",
            lambda: self._client().tooling_tokens_rotate(refresh_token=refresh_token),
        )

    def create_manifest(self, configuration_token: str, manifest: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._call(
            "manifest creation",
            lambda: self._client(configuration_token).apps_manifest_create(
                manifest=json.dumps(manifest, separators=(",", ":"), sort_keys=True)
            ),
        )

    def update_manifest(self, configuration_token: str, app_id: str, manifest: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._call(
            "manifest update",
            lambda: self._client(configuration_token).apps_manifest_update(
                app_id=app_id,
                manifest=json.dumps(manifest, separators=(",", ":"), sort_keys=True),
            ),
        )

    def exchange_oauth_code(self, client_id: str, client_secret: str, code: str, redirect_uri: str) -> Mapping[str, Any]:
        return self._call(
            "OAuth exchange",
            lambda: self._client().oauth_v2_access(
                client_id=client_id, client_secret=client_secret, code=code, redirect_uri=redirect_uri
            ),
        )


class SlackReconciler:
    def __init__(
        self,
        parameters: ParameterStore,
        slack: SlackProvisionerApi | None = None,
        *,
        now: Callable[[], str] = _utc_now,
    ) -> None:
        self.parameters = parameters
        self.slack = slack
        self.now = now

    def plan(
        self,
        spec: Mapping[str, Any],
        workspace_id: str,
        paths: ParameterPaths,
        redirect_uri: str,
        events_url: str,
        *,
        adopt_app_id: str | None = None,
    ) -> ReconcileResult:
        if not workspace_id:
            raise ReconciliationError("Slack workspace ID is required.")
        manifest = slack_manifest(dict(spec), redirect_uri, events_url)
        agent_name = _agent_name(spec)
        digest = manifest_digest(manifest)
        binding_raw = self.parameters.get(paths.binding, decrypt=False)
        credentials_present = self.parameters.get(paths.credentials, decrypt=False) is not None
        if binding_raw is None:
            if adopt_app_id is not None:
                return ReconcilePlan("adopt", agent_name, workspace_id, _valid_app_id(adopt_app_id), digest, "approval_required")
            if credentials_present:
                raise AdoptionRequired("Slack binding is missing after credentials exist; provide --adopt-app-id with the exact App ID.")
            return ReconcilePlan("create", agent_name, workspace_id, None, digest, "approval_required")
        try:
            binding = Binding.from_json(binding_raw)
        except AdoptionRequired:
            if adopt_app_id is None:
                raise
            return ReconcilePlan("adopt", agent_name, workspace_id, _valid_app_id(adopt_app_id), digest, "approval_required")
        if binding.workspace_id != workspace_id:
            if adopt_app_id is not None:
                return ReconcilePlan("adopt", agent_name, workspace_id, _valid_app_id(adopt_app_id), digest, "approval_required")
            raise AdoptionRequired("Slack binding workspace does not match; provide --adopt-app-id with the exact App ID after review.")
        if binding.agent_name != agent_name:
            raise ReconciliationError("Slack binding identity does not match metadata.name.")
        if adopt_app_id is not None:
            raise ReconciliationError("Slack binding already exists; adoption is not allowed.")
        if binding.manifest_digest == digest:
            return ReconcilePlan("noop", agent_name, workspace_id, binding.app_id, digest, binding.installation_state)
        return ReconcilePlan("update", agent_name, workspace_id, binding.app_id, digest, binding.installation_state)

    def apply(
        self,
        spec: Mapping[str, Any],
        workspace_id: str,
        paths: ParameterPaths,
        redirect_uri: str,
        events_url: str,
        *,
        adopt_app_id: str | None = None,
    ) -> ReconcilePlan:
        plan = self.plan(spec, workspace_id, paths, redirect_uri, events_url, adopt_app_id=adopt_app_id)
        if plan.action == "noop":
            return ReconcileResult(plan)
        slack = self._slack()
        configuration = _json_object(self.parameters.get(paths.provisioner, decrypt=True), "provisioner configuration")
        if set(configuration) != {"token", "refresh_token"}:
            raise ReconciliationError("Slack provisioner configuration parameter is corrupt.")
        refresh_token = _required(configuration, "refresh_token", "provisioner configuration")
        rotated = slack.rotate_configuration_token(refresh_token)
        configuration_token = _required(rotated, "token", "configuration token rotation")
        rotated_refresh_token = _required(rotated, "refresh_token", "configuration token rotation")
        if _required(rotated, "team_id", "configuration token rotation") != workspace_id:
            raise ReconciliationError("Slack configuration token workspace does not match the requested workspace.")
        self.parameters.put_secure_json(paths.provisioner, {"token": configuration_token, "refresh_token": rotated_refresh_token})

        manifest = slack_manifest(dict(spec), redirect_uri, events_url)
        preserved_binding: Binding | None = None
        if plan.action == "create":
            created = slack.create_manifest(configuration_token, manifest)
            app_id = _valid_app_id(_required(created, "app_id", "manifest creation"))
            credentials_response = created.get("credentials")
            if not isinstance(credentials_response, Mapping):
                raise ReconciliationError("Slack manifest creation response is incomplete.")
            credentials = {
                "client_id": _required(credentials_response, "client_id", "manifest creation"),
                "client_secret": _required(credentials_response, "client_secret", "manifest creation"),
                "signing_secret": _required(credentials_response, "signing_secret", "manifest creation"),
                # Generated locally, never returned by Slack: authenticates the
                # install-link `state` this reconciler mints and the callback
                # Lambda verifies. Never logged or printed.
                "state_signing_key": secrets.token_hex(STATE_SIGNING_KEY_BYTES),
            }
            self.parameters.put_secure_json(paths.credentials, credentials)
            result_plan = ReconcilePlan("create", plan.agent_name, workspace_id, app_id, plan.manifest_digest, plan.installation_state)
            try:
                state = sign_state(
                    agent_name=result_plan.agent_name,
                    workspace_id=workspace_id,
                    app_id=app_id,
                    redirect_uri=redirect_uri,
                    signing_key=credentials["state_signing_key"],
                )
            except StateError as error:
                raise ReconciliationError("Slack installation state could not be signed.") from error
            install_url = _install_url(credentials["client_id"], manifest["oauth_config"]["scopes"]["bot"], redirect_uri, state)
        else:
            assert plan.app_id is not None
            if plan.action == "update":
                preserved_binding = self._binding(paths.binding, workspace_id)
            # Apps created before signed OAuth state was introduced already
            # have Slack client credentials but no locally generated state
            # key. Seed it before changing the manifest so the new callback is
            # usable as soon as the redirect URI takes effect. Preserve bot
            # credentials when migrating an installed app.
            raw_credentials = _json_object(self.parameters.get(paths.credentials, decrypt=True), "credentials")
            legacy_credentials = set(raw_credentials).intersection(_LEGACY_CREDENTIAL_KEYS)
            credentials = self._credentials({key: value for key, value in raw_credentials.items() if key not in legacy_credentials})
            state_signing_key = credentials.get("state_signing_key")
            if state_signing_key is None:
                credentials["state_signing_key"] = secrets.token_hex(STATE_SIGNING_KEY_BYTES)
                try:
                    self.parameters.put_secure_json(paths.credentials, credentials)
                except Exception as error:
                    raise ReconciliationError(
                        "Slack OAuth state key was not persisted; the App manifest was not updated."
                    ) from error
            elif len(state_signing_key) < 32:
                raise ReconciliationError("Slack OAuth state signing key is invalid; the App manifest was not updated.")
            slack.update_manifest(configuration_token, plan.app_id, manifest)
            if legacy_credentials:
                try:
                    self.parameters.put_secure_json(paths.credentials, credentials)
                except Exception as error:
                    raise ReconciliationError("Slack credentials were not sanitized after the App manifest update.") from error
            result_plan = ReconcilePlan(
                plan.action,
                plan.agent_name,
                plan.workspace_id,
                plan.app_id,
                plan.manifest_digest,
                "installed" if "bot_token" in credentials else "approval_required",
            )
            install_url = None

        binding = Binding(
            agent_name=result_plan.agent_name,
            workspace_id=workspace_id,
            app_id=result_plan.app_id or "",
            manifest_digest=result_plan.manifest_digest,
            installation_state=result_plan.installation_state,
            last_successful_reconcile_at=self.now(),
            bot_user_id=preserved_binding.bot_user_id if preserved_binding else None,
            granted_scopes=preserved_binding.granted_scopes if preserved_binding else None,
        )
        try:
            self.parameters.put_binding(paths.binding, binding.as_json())
        except Exception as error:
            if plan.action == "create":
                raise AdoptionRequired("Slack App was created but its binding was not persisted; retry only with --adopt-app-id and the exact App ID.") from error
            raise ReconciliationError("Slack binding was not persisted; the existing App and credentials were preserved.") from error
        return ReconcileResult(result_plan, install_url)

    def installation_url(
        self,
        spec: Mapping[str, Any],
        workspace_id: str,
        paths: ParameterPaths,
        redirect_uri: str,
        events_url: str,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> str:
        """Mint a fresh signed install link for an already-reconciled binding.

        Requires a prior successful `apply` for this exact manifest (same
        `redirect_uri`); performs no Slack call and no SSM write, so it is
        safe to re-run whenever the previous link expired before a human
        approved installation.
        """
        manifest = slack_manifest(dict(spec), redirect_uri, events_url)
        binding = self._binding(paths.binding, workspace_id)
        if binding.manifest_digest != manifest_digest(manifest):
            raise ReconciliationError("Slack manifest is not reconciled for this redirect_uri; run apply first.")
        credentials = self._credentials(_json_object(self.parameters.get(paths.credentials, decrypt=True), "credentials"))
        client_id = _required(credentials, "client_id", "credentials")
        signing_key = _required(credentials, "state_signing_key", "credentials")
        try:
            state = sign_state(
                agent_name=binding.agent_name,
                workspace_id=workspace_id,
                app_id=binding.app_id,
                redirect_uri=redirect_uri,
                signing_key=signing_key,
                ttl_seconds=ttl_seconds,
            )
        except StateError as error:
            raise ReconciliationError("Slack installation state could not be signed.") from error
        return _install_url(client_id, manifest["oauth_config"]["scopes"]["bot"], redirect_uri, state)

    def complete_oauth(self, workspace_id: str, paths: ParameterPaths, code: str, redirect_uri: str) -> Binding:
        if not code:
            raise ReconciliationError("Slack OAuth code is required.")
        binding = self._binding(paths.binding, workspace_id)
        credentials = self._credentials(_json_object(self.parameters.get(paths.credentials, decrypt=True), "credentials"))
        response = self._slack().exchange_oauth_code(
            _required(credentials, "client_id", "credentials"),
            _required(credentials, "client_secret", "credentials"),
            code,
            redirect_uri,
        )
        if _required(response, "app_id", "OAuth exchange") != binding.app_id:
            raise ReconciliationError("Slack OAuth response App ID does not match the binding.")
        team = response.get("team")
        if not isinstance(team, Mapping) or _required(team, "id", "OAuth exchange") != workspace_id:
            raise ReconciliationError("Slack OAuth response workspace does not match the binding.")
        credentials["bot_token"] = _required(response, "access_token", "OAuth exchange")
        # PutParameter replaces one value atomically: a failed write leaves the
        # currently working bot credential in place.  SSM cannot atomically
        # commit this parameter with the independent binding parameter.
        try:
            self.parameters.put_secure_json(paths.credentials, self._credentials(credentials))
        except Exception as error:
            raise ReconciliationError("Slack OAuth credentials were not persisted; the current bot credential was preserved.") from error
        installed = Binding(
            agent_name=binding.agent_name,
            workspace_id=binding.workspace_id,
            app_id=binding.app_id,
            manifest_digest=binding.manifest_digest,
            installation_state="installed",
            last_successful_reconcile_at=self.now(),
            bot_user_id=response.get("bot_user_id") if isinstance(response.get("bot_user_id"), str) else binding.bot_user_id,
            granted_scopes=response.get("scope") if isinstance(response.get("scope"), str) else binding.granted_scopes,
        )
        try:
            self.parameters.put_binding(paths.binding, installed.as_json())
        except Exception as error:
            raise ReconciliationError("Slack OAuth credentials were persisted but installation state was not updated; inspect SSM before another OAuth exchange.") from error
        return installed

    def _binding(self, parameter: str, workspace_id: str) -> Binding:
        raw = self.parameters.get(parameter, decrypt=False)
        if raw is None:
            raise AdoptionRequired("Slack binding is missing; provide --adopt-app-id with the exact App ID.")
        binding = Binding.from_json(raw)
        if binding.workspace_id != workspace_id:
            raise ReconciliationError("Slack binding workspace does not match the requested workspace.")
        return binding

    @staticmethod
    def _credentials(credentials: Mapping[str, str]) -> dict[str, str]:
        unknown = set(credentials).difference(_CREDENTIAL_KEYS)
        if unknown:
            raise ReconciliationError("Slack credentials parameter is corrupt.")
        return dict(credentials)

    def _slack(self) -> SlackProvisionerApi:
        if self.slack is None:
            raise ReconciliationError("Slack API client is required for apply.")
        return self.slack
