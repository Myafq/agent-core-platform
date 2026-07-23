import unittest
from urllib.parse import parse_qsl, urlparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "modules" / "agentcore-gateway"
COMPOSITION = ROOT / "live" / "dev" / "us-east-1" / "platform" / "github-gateway" / "terragrunt.hcl"
SENSITIVE_URL_TERMS = ("token", "code", "secret", "password", "credential", "key")


def is_safe_return_url(value):
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return False
    fragments = parse_qsl(parsed.fragment, keep_blank_values=True)
    parameters = parse_qsl(parsed.query, keep_blank_values=True) + fragments
    return not any(
        term in item.lower()
        for pair in parameters
        for item in pair
        for term in SENSITIVE_URL_TERMS
    )


class AgentCoreGatewayModuleTests(unittest.TestCase):
    def setUp(self):
        self.main = (MODULE / "main.tf").read_text(encoding="utf-8")
        self.outputs = (MODULE / "outputs.tf").read_text(encoding="utf-8")
        self.composition = COMPOSITION.read_text(encoding="utf-8")

    def test_gateway_is_mcp_with_iam_inbound_authorization(self):
        self.assertIn('resource "aws_bedrockagentcore_gateway" "this"', self.main)
        self.assertIn('protocol_type   = "MCP"', self.main)
        self.assertIn('authorizer_type = "AWS_IAM"', self.main)
        self.assertIn("role_arn        = aws_iam_role.this.arn", self.main)

    def test_assume_role_prevents_confused_deputy_access(self):
        self.assertIn('variable = "aws:SourceAccount"', self.main)
        self.assertIn('values   = [data.aws_caller_identity.current.account_id]', self.main)
        self.assertIn('variable = "aws:SourceArn"', self.main)
        self.assertIn(':gateway/${var.name}-*",', self.main)

    def test_service_role_has_only_the_permissions_required_for_the_oauth_target(self):
        self.assertIn('identifiers = ["bedrock-agentcore.amazonaws.com"]', self.main)
        self.assertIn('resource "aws_iam_role_policy" "github_current_user"', self.main)
        self.assertIn('"bedrock-agentcore:GetWorkloadAccessToken"', self.main)
        self.assertIn('"bedrock-agentcore:GetResourceOauth2Token"', self.main)
        self.assertIn('"secretsmanager:GetSecretValue"', self.main)
        self.assertNotIn('resource "aws_iam_policy"', self.main)

    def test_module_exposes_only_non_secret_gateway_values(self):
        for output_name in (
            "gateway_arn",
            "gateway_id",
            "gateway_url",
            "service_role_arn",
            "github_current_user_target_id",
            "github_oauth_provider_arn",
            "github_oauth_client_secret_arn",
        ):
            self.assertIn(f'output "{output_name}"', self.outputs)
        for prohibited in ("access_token", "authorization_code"):
            self.assertNotIn(prohibited, self.outputs.lower())

    def test_target_is_exactly_the_frozen_github_oauth_operation(self):
        self.assertEqual(self.main.count('resource "aws_bedrockagentcore_gateway_target"'), 1)
        self.assertIn('name               = "github-current-user"', self.main)
        self.assertIn('grant_type         = "AUTHORIZATION_CODE"', self.main)
        self.assertIn('scopes             = ["read:user"]', self.main)
        self.assertIn("default_return_url = var.github_post_consent_return_url", self.main)
        self.assertIn("payload = var.github_openapi_payload", self.main)
        self.assertNotIn("repo", self.main)

    def test_gateway_composition_requires_provider_outputs_and_return_url(self):
        self.assertIn('source = "../../../../../modules/agentcore-gateway"', self.composition)
        self.assertIn('name        = "github-assistant-gateway"', self.composition)
        self.assertIn('dependency "github_oauth"', self.composition)
        self.assertIn("credential_provider_arn", self.composition)
        self.assertIn("client_secret_arn", self.composition)
        self.assertIn('get_env("GITHUB_POST_CONSENT_RETURN_URL")', self.composition)
        self.assertIn("contracts/github/openapi.yaml", self.composition)

    def test_post_consent_return_url_is_https_without_sensitive_parts(self):
        variables = (MODULE / "variables.tf").read_text(encoding="utf-8")
        self.assertIn('^https://[^[:space:]]+$', variables)
        self.assertIn('^https://[^/?#]*@', variables)
        for term in SENSITIVE_URL_TERMS:
            self.assertIn(term, variables)

        self.assertTrue(is_safe_return_url("https://example.com/github-consent"))
        for invalid_url in (
            "http://example.com/github-consent",
            "https://user@example.com/github-consent",
            "https://example.com/github-consent?access_token=value",
            "https://example.com/github-consent?state=authorization-code",
            "https://example.com/github-consent#secret=value",
        ):
            self.assertFalse(is_safe_return_url(invalid_url), invalid_url)

    def test_module_declares_the_remote_state_backend_used_by_composition(self):
        versions = (MODULE / "versions.tf").read_text(encoding="utf-8")
        self.assertIn('backend "s3" {}', versions)


if __name__ == "__main__":
    unittest.main()
