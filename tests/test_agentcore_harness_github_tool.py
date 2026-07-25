"""Static contract tests for the Phase 1 IAM chat-only Harness."""

from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "modules" / "agentcore-harness"
COMPOSITION = ROOT / "live" / "dev" / "us-east-1" / "agents" / "github-assistant" / "terragrunt.hcl"


class AgentCoreHarnessChatOnlyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.main = (MODULE / "main.tf").read_text(encoding="utf-8")
        self.variables = (MODULE / "variables.tf").read_text(encoding="utf-8")
        self.composition = COMPOSITION.read_text(encoding="utf-8")

    def test_composition_is_a_standalone_chat_only_harness(self) -> None:
        self.assertIn('source = "../../../../../modules/agentcore-harness"', self.composition)
        self.assertNotIn('dependency "', self.composition)
        self.assertNotIn("gateway", self.composition.lower())
        self.assertNotIn("oauth", self.composition.lower())
        self.assertNotIn("jwt", self.composition.lower())

    def test_harness_has_model_prompt_limits_and_managed_memory(self) -> None:
        self.assertIn('resource "aws_bedrockagentcore_harness" "this"', self.main)
        self.assertIn("bedrock_model_config", self.main)
        self.assertIn("system_prompt", self.main)
        self.assertIn("max_iterations", self.main)
        self.assertIn("max_tokens", self.main)
        self.assertIn("timeout_seconds", self.main)
        self.assertIn('sid = "HarnessManagedMemory"', self.main)

    def test_execution_role_and_harness_have_no_disabled_capabilities(self) -> None:
        for forbidden in (
            "agentcore_gateway",
            "InvokeGateway",
            "GetResourceOauth2Token",
            "GetWorkloadAccessToken",
            "secretsmanager:GetSecretValue",
            "BrowserSession",
            "CodeInterpreter",
            "authorizer_configuration",
            "custom_jwt_authorizer",
            "oauth",
            "token-vault",
        ):
            self.assertNotIn(forbidden.lower(), self.main.lower())
            self.assertNotIn(forbidden.lower(), self.variables.lower())

    def test_api_format_workaround_remains_explicit(self) -> None:
        self.assertIn('resource "terraform_data" "model_api_format"', self.main)
        self.assertIn("update-harness", self.main)
        self.assertIn("apiFormat", self.main)


if __name__ == "__main__":
    unittest.main()
