#!/usr/bin/env python3
"""Render the platform-owned Slack app manifest from an agent specification."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

try:
    import yaml
except ModuleNotFoundError:
    print("Missing validation dependency 'yaml'. Install requirements-dev.txt.", file=sys.stderr)
    raise SystemExit(2) from None


def slack_manifest(spec: dict[str, Any]) -> dict[str, Any]:
    slack = spec.get("spec", {}).get("interfaces", {}).get("slack")
    if not isinstance(slack, dict) or not isinstance(slack.get("name"), str):
        raise ValueError("spec.interfaces.slack.name is required")
    agent_name = spec.get("metadata", {}).get("name")
    if not isinstance(agent_name, str):
        raise ValueError("metadata.name is required")
    description = spec.get("metadata", {}).get("description")
    manifest: dict[str, Any] = {
        "_metadata": {"major_version": 1, "minor_version": 1},
        "display_information": {"name": slack["name"]},
        "features": {
            "app_home": {
                "home_tab_enabled": False,
                "messages_tab_enabled": True,
                "messages_tab_read_only_enabled": False,
            },
            "bot_user": {"display_name": agent_name, "always_online": False},
        },
        "oauth_config": {
            "redirect_urls": ["https://localhost/slack/oauth/callback"],
            "scopes": {
                "bot": ["app_mentions:read", "channels:history", "chat:write", "groups:history", "im:history"]
            }
        },
        "settings": {
            "event_subscriptions": {
                "bot_events": ["app_mention", "message.channels", "message.groups", "message.im"]
            },
            "org_deploy_enabled": False,
            "socket_mode_enabled": True,
            "is_hosted": False,
            "token_rotation_enabled": False,
        },
    }
    if isinstance(description, str) and description:
        manifest["display_information"]["description"] = description[:140]
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("spec", type=Path)
    args = parser.parse_args()
    spec = yaml.safe_load(args.spec.read_text(encoding="utf-8"))
    try:
        manifest = slack_manifest(spec)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    json.dump(manifest, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
