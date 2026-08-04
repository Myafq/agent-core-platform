"""Offline tests for the manually started Slack adapter launcher."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from clients.slack.launcher import (
    AdapterConfig,
    AgentSource,
    ReconcileError,
    adapter_config,
    child_environment,
    discover_slack_agents,
    exec_adapter,
)


class FakeReader:
    def __init__(self, specs: dict[str, str]) -> None:
        self.specs = specs

    def agent_paths(self) -> list[str]:
        return list(self.specs)

    def read(self, path: str) -> str:
        return self.specs[path]


class FakeParameters:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values
        self.calls: list[tuple[str, bool]] = []

    def get(self, name: str, *, decrypt: bool) -> str:
        self.calls.append((name, decrypt))
        return self.values[name]


SPEC = """\
apiVersion: agentcore.example/v1alpha1
kind: Agent
metadata:
  name: github-assistant
  description: Test
spec:
  interfaces:
    slack:
      name: GitHub Assistant
"""


def values(manifest_digest: str, *, state: str = "socket_mode_ready", bot_token: str = "xbot", app_token: str = "xapp") -> dict[str, str]:
    return {
        "/agent-core/slack/agents/github-assistant/binding": json.dumps(
            {
                "agent_name": "github-assistant",
                "workspace_id": "T1",
                "app_id": "A1",
                "manifest_digest": manifest_digest,
                "installation_state": state,
            }
        ),
        "/agent-core/slack/agents/github-assistant/credentials": json.dumps(
            {"bot_token": bot_token, "app_token": app_token}
        ),
    }


REDIRECT_URI = "https://callback.example/slack/oauth/callback"


class SlackLauncherTests(unittest.TestCase):
    def source(self) -> AgentSource:
        return discover_slack_agents(FakeReader({"agents/github-assistant/agent.yaml": SPEC}), REDIRECT_URI)["github-assistant"]

    def test_discovers_only_slack_agents_from_main_content(self) -> None:
        reader = FakeReader(
            {
                "agents/github-assistant/agent.yaml": SPEC,
                "agents/no-slack/agent.yaml": SPEC.replace("  interfaces:\n    slack:\n      name: GitHub Assistant\n", ""),
            }
        )
        agents = discover_slack_agents(reader, REDIRECT_URI)
        self.assertEqual(set(agents), {"github-assistant"})

    def test_binding_must_match_rendered_manifest_and_decrypts_only_agent_credentials(self) -> None:
        source = self.source()
        parameters = FakeParameters(values(source.manifest_digest))
        config = adapter_config(source, parameters, "arn:harness")
        self.assertEqual(config.workspace_id, "T1")
        self.assertEqual(
            parameters.calls,
            [
                ("/agent-core/slack/agents/github-assistant/binding", False),
                ("/agent-core/slack/agents/github-assistant/credentials", True),
            ],
        )
        with self.assertRaisesRegex(ReconcileError, "manifest not reconciled"):
            adapter_config(source, FakeParameters(values("different")), "arn:harness")

    def test_exec_launcher_passes_tokens_only_in_the_child_environment(self) -> None:
        config = AdapterConfig("github-assistant", "T1", "A1", "arn:harness", "secret-bot", "secret-app", "path")
        environment, bot_name, app_name = child_environment(config, "us-east-1", "dev")
        self.assertEqual(environment[bot_name], "secret-bot")
        self.assertEqual(environment[app_name], "secret-app")
        self.assertNotIn("SLACK_BOT_TOKEN", environment)
        self.assertNotIn("SLACK_APP_TOKEN", environment)
        observed: dict[str, object] = {}

        def executor(path: str, argv: object, env: object) -> None:
            observed.update(path=path, argv=argv, env=env)

        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch("clients.slack.launcher.PROJECT_ROOT", Path(temporary_directory)):
                exec_adapter(config, region="us-east-1", profile="dev", executor=executor)
            state_directory = Path(temporary_directory) / ".slack-threads"
            self.assertEqual(state_directory.stat().st_mode & 0o777, 0o700)
        self.assertNotIn("secret-bot", observed["argv"])
        self.assertNotIn("secret-app", observed["argv"])
        self.assertEqual(observed["env"], environment)


if __name__ == "__main__":
    unittest.main()
