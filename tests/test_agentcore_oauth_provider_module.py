import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "modules" / "agentcore-oauth-provider"
COMPOSITION = ROOT / "live" / "dev" / "us-east-1" / "platform" / "github-oauth" / "terragrunt.hcl"


class AgentCoreOauthProviderModuleTests(unittest.TestCase):
    def setUp(self):
        self.main = (MODULE / "main.tf").read_text(encoding="utf-8")
        self.variables = (MODULE / "variables.tf").read_text(encoding="utf-8")
        self.outputs = (MODULE / "outputs.tf").read_text(encoding="utf-8")
        self.composition = COMPOSITION.read_text(encoding="utf-8")

    def test_module_owns_only_the_shared_github_oauth_provider(self):
        self.assertEqual(
            self.main.count('resource "aws_bedrockagentcore_oauth2_credential_provider"'),
            1,
        )
        self.assertIn('credential_provider_vendor = "GithubOauth2"', self.main)
        self.assertNotIn("aws_bedrockagentcore_harness", self.main)
        self.assertNotIn("aws_bedrockagentcore_gateway", self.main)

    def test_credentials_are_ephemeral_and_write_only(self):
        for name in ("github_client_id", "github_client_secret"):
            self.assertIn(f'variable "{name}"', self.variables)
        self.assertGreaterEqual(self.variables.count("ephemeral   = true"), 2)
        self.assertIn("client_id_wo", self.main)
        self.assertIn("client_secret_wo", self.main)

    def test_outputs_are_non_secret_resource_identifiers(self):
        for name in ("credential_provider_arn", "client_secret_arn"):
            self.assertIn(f'output "{name}"', self.outputs)
        self.assertIn("one(aws_bedrockagentcore_oauth2_credential_provider.github.client_secret_arn).secret_arn", self.outputs)
        self.assertNotIn('output "client_secret"', self.outputs)
        self.assertNotIn('output "callback_url"', self.outputs)

    def test_platform_composition_preserves_the_applied_provider_name(self):
        self.assertIn('source = "../../../../../modules/agentcore-oauth-provider"', self.composition)
        self.assertIn('name        = "github-assistant-oauth"', self.composition)


if __name__ == "__main__":
    unittest.main()
