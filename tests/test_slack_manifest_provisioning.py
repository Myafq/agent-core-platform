"""Static contract tests for manifest-derived shared Slack provisioning."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
UNIT = ROOT / "live" / "dev" / "us-east-1" / "platform" / "slack-oauth-callback" / "terragrunt.hcl"
MODULE = ROOT / "modules" / "slack-oauth-callback"


class SlackManifestProvisioningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.unit = UNIT.read_text(encoding="utf-8")
        self.main = (MODULE / "main.tf").read_text(encoding="utf-8")
        self.variables = (MODULE / "variables.tf").read_text(encoding="utf-8")

    def test_platform_unit_derives_membership_from_slack_manifest_intent(self) -> None:
        self.assertIn('fileset(local.repo_root, "agents/*/agent.yaml")', self.unit)
        self.assertIn("spec.interfaces.slack.name", self.unit)
        self.assertIn("slack_agent_names = local.slack_agent_names", self.unit)
        self.assertNotIn("github-assistant", self.unit)
        self.assertNotIn("harness/", self.unit)
        self.assertNotIn("app_id", self.unit)

    def test_environment_binding_and_agent_state_are_joined_read_only(self) -> None:
        self.assertIn('data "aws_ssm_parameter" "agent_binding"', self.main)
        self.assertIn('name            = "${var.agent_parameter_prefix}/${each.key}/binding"', self.main)
        self.assertIn("with_decryption = false", self.main)
        self.assertIn('data "terraform_remote_state" "agent"', self.main)
        self.assertIn('key    = "agents/${each.key}/terraform.tfstate"', self.main)
        self.assertIn("agent_name => state.outputs.harness_arn", self.main)
        self.assertNotIn('data "aws_ssm_parameter" "agent_credentials"', self.main)

    def test_shared_state_remains_the_only_route_and_permission_owner(self) -> None:
        membership = "{ for agent_name in var.slack_agent_names : agent_name => agent_name }"
        self.assertEqual(self.main.count('resource "aws_apigatewayv2_route" "events"'), 1)
        self.assertEqual(self.main.count('resource "aws_lambda_permission" "events_ingress"'), 1)
        self.assertGreaterEqual(self.main.count(membership), 2)
        self.assertNotIn('variable "slack_agents"', self.variables)

    def test_binding_checks_match_manifest_identity_workspace_and_app(self) -> None:
        self.assertNotIn('check "slack_environment_bindings"', self.main)
        self.assertIn("precondition {", self.main)
        self.assertIn("try(local.slack_bindings[each.key].agent_name, null) == each.key", self.main)
        self.assertIn("try(local.slack_bindings[each.key].workspace_id, null) == var.slack_workspace_id", self.main)
        self.assertIn(
            'can(regex("^A[A-Z0-9]+$", try(local.slack_bindings[each.key].app_id, "")))',
            self.main,
        )
        self.assertIn("try(local.slack_agent_harnesses[each.key], \"\")", self.main)
        self.assertNotIn('resource "terraform_data"', self.main)


if __name__ == "__main__":
    unittest.main()
