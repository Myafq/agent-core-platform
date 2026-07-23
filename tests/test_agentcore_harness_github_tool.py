import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "modules" / "agentcore-harness"
COMPOSITION = ROOT / "live" / "dev" / "us-east-1" / "agents" / "github-assistant" / "terragrunt.hcl"
PROMPT = ROOT / "agents" / "github-assistant" / "prompts" / "system.md"


class AgentCoreHarnessGitHubToolTests(unittest.TestCase):
    def setUp(self):
        self.main = (MODULE / "main.tf").read_text(encoding="utf-8")
        self.variables = (MODULE / "variables.tf").read_text(encoding="utf-8")
        self.composition = COMPOSITION.read_text(encoding="utf-8")
        self.prompt = PROMPT.read_text(encoding="utf-8")

    def test_exactly_one_github_gateway_tool_uses_the_existing_provider(self):
        self.assertNotIn(
            'resource "aws_bedrockagentcore_oauth2_credential_provider"', self.main
        )
        self.assertEqual(self.main.count('type = "agentcore_gateway"'), 1)
        self.assertIn('name = "github"', self.main)
        self.assertIn("gateway_arn = var.github_gateway_arn", self.main)
        self.assertIn("provider_arn", self.main)
        self.assertIn("var.github_oauth_provider_arn", self.main)
        self.assertIn('grant_type', self.main)
        self.assertIn('"AUTHORIZATION_CODE"', self.main)
        self.assertIn("default_return_url = var.github_post_consent_return_url", self.main)
        self.assertIn('scopes', self.main)
        self.assertIn('["read:user"]', self.main)
        self.assertIn("dependency.github_gateway.outputs.github_oauth_provider_arn", self.composition)

    def test_allow_list_exposes_only_the_generated_current_user_operation(self):
        self.assertIn('allowed_tools   = ["@github/getAuthenticatedUser"]', self.main)
        self.assertNotIn("__no_tools_configured__", self.main)
        self.assertNotIn('allowed_tools   = ["*"]', self.main)

    def test_execution_role_has_only_documented_gateway_oauth_permissions(self):
        self.assertIn('sid       = "InvokeGitHubGateway"', self.main)
        self.assertIn('actions   = ["bedrock-agentcore:InvokeGateway"]', self.main)
        self.assertIn("resources = [var.github_gateway_arn]", self.main)
        self.assertIn('actions = ["bedrock-agentcore:GetResourceOauth2Token"]', self.main)
        self.assertIn('var.github_oauth_provider_arn', self.main)
        self.assertIn('"secretsmanager:GetSecretValue"', self.main)
        self.assertIn('resources = [var.github_client_secret_arn]', self.main)

    def test_composition_depends_only_on_the_shared_gateway_unit(self):
        self.assertIn('github_gateway_arn', self.composition)
        self.assertIn('dependency "github_gateway"', self.composition)
        self.assertIn('config_path = "../../platform/github-gateway"', self.composition)
        self.assertIn('dependency.github_gateway.outputs.gateway_arn', self.composition)
        self.assertIn('github_post_consent_return_url', self.composition)
        self.assertIn('get_env("GITHUB_POST_CONSENT_RETURN_URL")', self.composition)
        self.assertIn('variable "github_gateway_arn"', self.variables)
        self.assertNotIn('GITHUB_GATEWAY_ARN', self.composition)

    def test_prompt_restricts_github_to_authenticated_current_user(self):
        self.assertIn("authenticated user's", self.prompt)
        self.assertIn("identity", self.prompt)
        for prohibited in (
            "repositories",
            "issues",
            "pull requests",
            "arbitrary URLs",
            "mutations",
            "private-source access",
        ):
            self.assertIn(prohibited, self.prompt)


if __name__ == "__main__":
    unittest.main()
