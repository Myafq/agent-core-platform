#!/usr/bin/env python3
"""Manually launch one provisioned Slack Socket Mode adapter from merged main."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable, Mapping, Protocol, Sequence

try:
    import yaml
except ModuleNotFoundError:
    yaml = None

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
LOGGER = logging.getLogger(__name__)
DEFAULT_BINDING_PREFIX = "/agent-core/slack/agents"
COMPLETE_INSTALLATION_STATES = frozenset({"installed", "socket_mode_ready"})


class ReconcileError(Exception):
    """An agent cannot safely be launched at this time."""


class MainContentReader(Protocol):
    def agent_paths(self) -> Sequence[str]: ...

    def read(self, path: str) -> str: ...


class ParameterStore(Protocol):
    def get(self, name: str, *, decrypt: bool) -> str: ...


@dataclass(frozen=True)
class AgentSource:
    name: str
    path: str
    raw_spec: str
    manifest_digest: str


@dataclass(frozen=True)
class AdapterConfig:
    name: str
    workspace_id: str
    app_id: str
    harness_arn: str
    bot_token: str
    app_token: str
    credentials_path: str


class GitMainContentReader:
    """Reads desired agent specifications from an already merged Git ref."""

    def __init__(self, repository: Path, ref: str = "main") -> None:
        self.repository = repository
        self.ref = ref

    def _git(self, arguments: Sequence[str]) -> str:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=self.repository,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise ReconcileError("unable to read merged main content")
        return completed.stdout

    def agent_paths(self) -> Sequence[str]:
        paths = self._git(["ls-tree", "-r", "--name-only", self.ref, "--", "agents"])
        return tuple(path for path in paths.splitlines() if path.endswith("/agent.yaml"))

    def read(self, path: str) -> str:
        if not path.startswith("agents/") or ":" in path:
            raise ReconcileError("invalid agent path from merged main content")
        return self._git(["show", f"{self.ref}:{path}"])


class AwsParameterStore:
    """Small SSM wrapper; imports boto3 only for an explicit live launch."""

    def __init__(self, region: str, profile: str) -> None:
        try:
            import boto3
        except ModuleNotFoundError as error:
            raise ReconcileError("missing client dependency 'boto3'") from error
        self.client = boto3.Session(profile_name=profile, region_name=region).client("ssm")

    def get(self, name: str, *, decrypt: bool) -> str:
        try:
            response = self.client.get_parameter(Name=name, WithDecryption=decrypt)
            value = response["Parameter"]["Value"]
        except Exception as error:
            raise ReconcileError(f"SSM parameter unavailable: {name}") from error
        if not isinstance(value, str):
            raise ReconcileError(f"SSM parameter has no string value: {name}")
        return value


def _mapping(value: str, parameter_name: str) -> dict[str, Any]:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as error:
        raise ReconcileError(f"invalid JSON in SSM parameter: {parameter_name}") from error
    if not isinstance(decoded, dict):
        raise ReconcileError(f"SSM parameter must contain a JSON object: {parameter_name}")
    return decoded


def _required_string(values: Mapping[str, Any], field: str, source: str) -> str:
    value = values.get(field)
    if not isinstance(value, str) or not value:
        raise ReconcileError(f"missing {field} in {source}")
    return value


def _agent_source(path: str, raw_spec: str, redirect_uri: str) -> AgentSource | None:
    if yaml is None:
        raise ReconcileError("missing runtime dependency 'yaml'")
    try:
        spec = yaml.safe_load(raw_spec)
    except yaml.YAMLError as error:
        raise ReconcileError(f"invalid agent YAML: {path}") from error
    if not isinstance(spec, dict):
        raise ReconcileError(f"agent YAML is not an object: {path}")
    metadata = spec.get("metadata")
    interfaces = spec.get("spec", {}).get("interfaces") if isinstance(spec.get("spec"), dict) else None
    slack = interfaces.get("slack") if isinstance(interfaces, dict) else None
    if slack is None:
        return None
    if not isinstance(metadata, dict) or not isinstance(metadata.get("name"), str) or not metadata["name"]:
        raise ReconcileError(f"Slack agent has no metadata.name: {path}")
    if not isinstance(slack, dict) or not isinstance(slack.get("name"), str) or not slack["name"]:
        raise ReconcileError(f"Slack agent has no spec.interfaces.slack.name: {path}")
    try:
        from scripts.render_slack_manifest import slack_manifest

        manifest = slack_manifest(spec, redirect_uri)
    except (ImportError, ValueError) as error:
        raise ReconcileError(f"unable to render Slack manifest: {path}") from error
    manifest_json = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return AgentSource(
        name=metadata["name"],
        path=path,
        raw_spec=raw_spec,
        manifest_digest=hashlib.sha256(manifest_json).hexdigest(),
    )


def discover_slack_agents(reader: MainContentReader, redirect_uri: str) -> dict[str, AgentSource]:
    """Return Slack-enabled agents from the selected merged Git ref.

    `redirect_uri` must be the same platform OAuth callback URL reconciliation
    used, so the recomputed manifest digest can confirm the binding is
    reconciled for that URL.

    Any malformed enabled spec aborts the whole discovery, preventing a Git read
    failure from being mistaken for deletion of locally running adapters.
    """
    agents: dict[str, AgentSource] = {}
    for path in reader.agent_paths():
        source = _agent_source(path, reader.read(path), redirect_uri)
        if source is None:
            continue
        if source.name in agents:
            raise ReconcileError(f"duplicate Slack agent name in merged main: {source.name}")
        agents[source.name] = source
    return agents


def binding_path(agent_name: str, prefix: str = DEFAULT_BINDING_PREFIX) -> str:
    return f"{prefix.rstrip('/')}/{agent_name}/binding"


def credentials_path(agent_name: str, prefix: str = DEFAULT_BINDING_PREFIX) -> str:
    return f"{prefix.rstrip('/')}/{agent_name}/credentials"


def adapter_config(
    source: AgentSource,
    parameters: ParameterStore,
    harness_arn: str | None,
    *,
    parameter_prefix: str = DEFAULT_BINDING_PREFIX,
) -> AdapterConfig:
    """Read one public binding then decrypt only that agent's credentials path."""
    if not harness_arn:
        raise ReconcileError(f"no Harness ARN configured for Slack agent: {source.name}")
    public_path = binding_path(source.name, parameter_prefix)
    secret_path = credentials_path(source.name, parameter_prefix)
    binding = _mapping(parameters.get(public_path, decrypt=False), public_path)
    agent_name = _required_string(binding, "agent_name", public_path)
    workspace_id = _required_string(binding, "workspace_id", public_path)
    app_id = _required_string(binding, "app_id", public_path)
    manifest_digest = _required_string(binding, "manifest_digest", public_path)
    installation_state = _required_string(binding, "installation_state", public_path)
    if agent_name != source.name:
        raise ReconcileError(f"Slack binding identity does not match agent: {source.name}")
    if manifest_digest != source.manifest_digest:
        raise ReconcileError(f"Slack manifest not reconciled for agent: {source.name}")
    if installation_state not in COMPLETE_INSTALLATION_STATES:
        raise ReconcileError(f"Slack installation is not complete for agent: {source.name}")
    if not workspace_id.startswith("T") or not app_id.startswith("A"):
        raise ReconcileError(f"invalid Slack workspace/App binding for agent: {source.name}")

    credentials = _mapping(parameters.get(secret_path, decrypt=True), secret_path)
    return AdapterConfig(
        name=source.name,
        workspace_id=workspace_id,
        app_id=app_id,
        harness_arn=harness_arn,
        bot_token=_required_string(credentials, "bot_token", secret_path),
        app_token=_required_string(credentials, "app_token", secret_path),
        credentials_path=secret_path,
    )


def child_environment(config: AdapterConfig, region: str, profile: str) -> tuple[dict[str, str], str, str]:
    """Return a deliberately narrow child environment and token variable names."""
    token_prefix = "AGENTCORE_SLACK_" + config.name.upper().replace("-", "_")
    bot_token_env = f"{token_prefix}_BOT_TOKEN"
    app_token_env = f"{token_prefix}_APP_TOKEN"
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", ""),
        "AWS_REGION": region,
        "AWS_PROFILE": profile,
        "PYTHONUNBUFFERED": "1",
        bot_token_env: config.bot_token,
        app_token_env: config.app_token,
    }
    for name in ("AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        if os.environ.get(name):
            environment[name] = os.environ[name]
    return environment, bot_token_env, app_token_env


def exec_adapter(
    config: AdapterConfig,
    *,
    region: str,
    profile: str,
    executor: Callable[[str, Sequence[str], Mapping[str, str]], Any] = os.execve,
) -> None:
    """Replace this launcher with one selected adapter; never supervise it."""
    environment, bot_token_env, app_token_env = child_environment(config, region, profile)
    thread_state_path = PROJECT_ROOT / ".slack-threads" / config.name
    thread_state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    thread_state_path.parent.chmod(0o700)
    command = (
        sys.executable,
        str(PROJECT_ROOT / "clients" / "slack" / "bot.py"),
        "--region",
        region,
        "--profile",
        profile,
        "--harness-arn",
        config.harness_arn,
        "--app-id",
        config.app_id,
        "--workspace-id",
        config.workspace_id,
        "--bot-token-env",
        bot_token_env,
        "--app-token-env",
        app_token_env,
        "--thread-state-file",
        str(thread_state_path),
    )
    executor(sys.executable, command, environment)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--profile", default="default")
    parser.add_argument("--agent", required=True, help="metadata.name of one Slack-enabled agent")
    parser.add_argument("--harness-arn", required=True)
    parser.add_argument("--redirect-uri", required=True, help="Platform OAuth callback URL used by reconciliation.")
    parser.add_argument("--parameter-prefix", default=DEFAULT_BINDING_PREFIX)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    return args


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        source = discover_slack_agents(GitMainContentReader(PROJECT_ROOT), args.redirect_uri).get(args.agent)
        if source is None:
            raise ReconcileError(f"Slack agent is not enabled in merged main: {args.agent}")
        config = adapter_config(
            source,
            AwsParameterStore(args.region, args.profile),
            args.harness_arn,
            parameter_prefix=args.parameter_prefix,
        )
        exec_adapter(config, region=args.region, profile=args.profile)
    except ReconcileError as error:
        LOGGER.error("Slack launcher refused to start agent=%s class=%s", args.agent, type(error).__name__)
        return 1
    except OSError as error:
        LOGGER.error("Slack launcher exec failed agent=%s class=%s", args.agent, type(error).__name__)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
