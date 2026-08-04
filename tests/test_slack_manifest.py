"""Slack manifest generation from portable agent intent."""

from __future__ import annotations

import copy
from pathlib import Path
import unittest

import yaml

from scripts.render_slack_manifest import slack_manifest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_SPEC = REPOSITORY_ROOT / "agents" / "github-assistant" / "agent.yaml"


class SlackManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = yaml.safe_load(SAMPLE_SPEC.read_text(encoding="utf-8"))

    def test_renders_minimal_direct_message_socket_mode_manifest(self) -> None:
        manifest = slack_manifest(self.spec)
        self.assertEqual(manifest["display_information"]["name"], "GitHub Assistant")
        self.assertEqual(manifest["features"]["bot_user"]["display_name"], "github-assistant")
        self.assertEqual(
            manifest["oauth_config"]["scopes"]["bot"],
            ["app_mentions:read", "channels:history", "chat:write", "groups:history", "im:history"],
        )
        self.assertEqual(
            manifest["settings"]["event_subscriptions"]["bot_events"],
            ["app_mention", "message.channels", "message.groups", "message.im"],
        )
        self.assertTrue(manifest["settings"]["socket_mode_enabled"])
        self.assertNotIn("request_url", manifest["settings"]["event_subscriptions"])

    def test_requires_explicit_slack_name(self) -> None:
        spec = copy.deepcopy(self.spec)
        del spec["spec"]["interfaces"]["slack"]
        with self.assertRaisesRegex(ValueError, "spec.interfaces.slack.name"):
            slack_manifest(spec)


if __name__ == "__main__":
    unittest.main()
