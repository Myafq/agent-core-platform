#!/usr/bin/env python3
"""Plan and apply Slack App reconciliation from one agent specification."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import yaml
except ModuleNotFoundError:
    print("Missing PyYAML. Install clients/cli/requirements.txt.", file=sys.stderr)
    raise SystemExit(2) from None

from clients.slack.reconciliation import (
    AdoptionRequired,
    ParameterPaths,
    ReconciliationError,
    SlackReconciler,
    SlackSdkProvisionerApi,
    SsmParameterStore,
)


REDIRECT_URI_COMMANDS = frozenset({"plan", "apply", "install-url", "complete-oauth"})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("plan", "apply", "install-url", "complete-oauth", "set-app-token"))
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--profile", default="default")
    parser.add_argument("--provisioner-parameter", default="/agent-core/slack/provisioner/config")
    parser.add_argument("--binding-parameter")
    parser.add_argument("--credentials-parameter")
    parser.add_argument("--adopt-app-id")
    parser.add_argument("--oauth-code-env")
    parser.add_argument("--app-token-env")
    parser.add_argument(
        "--redirect-uri",
        help="Public platform OAuth callback URL (required for plan, apply, install-url, complete-oauth).",
    )
    args = parser.parse_args()
    if args.command in REDIRECT_URI_COMMANDS and not args.redirect_uri:
        parser.error(f"--redirect-uri is required for {args.command!r}.")
    return args


def parameter_paths(args: argparse.Namespace, spec: dict[str, Any]) -> ParameterPaths:
    name = spec.get("metadata", {}).get("name") if isinstance(spec.get("metadata"), dict) else None
    if not isinstance(name, str) or not name:
        raise ReconciliationError("Agent metadata.name is required.")
    root = f"/agent-core/slack/agents/{name}"
    return ParameterPaths(args.provisioner_parameter, args.binding_parameter or f"{root}/binding", args.credentials_parameter or f"{root}/credentials")


def load_spec(path: Path) -> dict[str, Any]:
    try:
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ReconciliationError("Slack agent specification could not be read.") from error
    if not isinstance(spec, dict):
        raise ReconciliationError("Slack agent specification must be an object.")
    return spec


def main() -> int:
    args = parse_args()
    try:
        spec = load_spec(args.spec)
        paths = parameter_paths(args, spec)
        if args.command == "plan":
            reconciler = SlackReconciler(_ssm(args))
            print(json.dumps(reconciler.plan(spec, args.workspace_id, paths, args.redirect_uri, adopt_app_id=args.adopt_app_id).safe_output(), sort_keys=True))
            return 0
        if args.command == "install-url":
            if args.adopt_app_id is not None:
                raise ReconciliationError("--adopt-app-id is only valid for plan or apply.")
            reconciler = SlackReconciler(_ssm(args))
            print(reconciler.installation_url(spec, args.workspace_id, paths, args.redirect_uri))
            return 0
        reconciler = SlackReconciler(_ssm(args), SlackSdkProvisionerApi())
        if args.command == "apply":
            print(json.dumps(reconciler.apply(spec, args.workspace_id, paths, args.redirect_uri, adopt_app_id=args.adopt_app_id).safe_output(), sort_keys=True))
            return 0
        if args.adopt_app_id is not None:
            raise ReconciliationError("--adopt-app-id is only valid for plan or apply.")
        if args.command == "complete-oauth":
            code = _environment_value(args.oauth_code_env, "--oauth-code-env")
            binding = reconciler.complete_oauth(args.workspace_id, paths, code, args.redirect_uri)
            print(json.dumps({"action": "oauth_completed", "app_id": binding.app_id, "workspace_id": binding.workspace_id}, sort_keys=True))
            return 0
        app_token = _environment_value(args.app_token_env, "--app-token-env")
        binding = reconciler.set_app_token(args.workspace_id, paths, app_token)
        print(json.dumps({"action": "app_token_updated", "app_id": binding.app_id, "workspace_id": binding.workspace_id}, sort_keys=True))
        return 0
    except AdoptionRequired as error:
        print(str(error), file=sys.stderr)
        return 3
    except ReconciliationError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        print("Slack reconciliation failed.", file=sys.stderr)
        return 1


def _environment_value(variable: str | None, option: str) -> str:
    if not variable:
        raise ReconciliationError(f"{option} is required.")
    value = os.environ.get(variable)
    if not value:
        raise ReconciliationError(f"Environment variable named by {option} is required.")
    return value


def _ssm(args: argparse.Namespace) -> SsmParameterStore:
    try:
        import boto3
    except ModuleNotFoundError as error:
        raise ReconciliationError("boto3 is unavailable; install clients/cli/requirements.txt.") from error
    return SsmParameterStore(boto3.Session(profile_name=args.profile, region_name=args.region).client("ssm"))


if __name__ == "__main__":
    raise SystemExit(main())
