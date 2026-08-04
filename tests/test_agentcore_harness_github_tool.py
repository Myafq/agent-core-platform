"""Static contract tests for the IAM Harness GitHub Gateway attachment."""

from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "modules" / "agentcore-harness"
COMPOSITION = ROOT / "live" / "dev" / "us-east-1" / "agents" / "github-assistant" / "terragrunt.hcl"
PROMPT = ROOT / "agents" / "github-assistant" / "prompts" / "system.md"


class AgentCoreHarnessChatOnlyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.main = (MODULE / "main.tf").read_text(encoding="utf-8")
        self.variables = (MODULE / "variables.tf").read_text(encoding="utf-8")
        self.composition = COMPOSITION.read_text(encoding="utf-8")
        self.prompt = PROMPT.read_text(encoding="utf-8")
        self.coding_image = ROOT / "containers" / "harness-coding"

    def test_composition_consumes_only_the_platform_gateway_output(self) -> None:
        self.assertIn('source = "../../../../../modules/agentcore-harness"', self.composition)
        self.assertIn('dependency "github_app_tool"', self.composition)
        self.assertIn('config_path = "../../platform/github-app-tool"', self.composition)
        self.assertRegex(
            self.composition,
            r"gateway_arn\s+= dependency\.github_app_tool\.outputs\.gateway_arn",
        )
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

    def test_execution_role_streams_only_the_configured_bedrock_model_or_profile(self) -> None:
        self.assertIn('sid       = "InvokeConfiguredBedrockModelStream"', self.main)
        self.assertIn('actions   = ["bedrock:InvokeModelWithResponseStream"]', self.main)
        self.assertIn("resources = local.bedrock_invocation_resources", self.main)
        self.assertIn('startswith(var.model_id, "us.")', self.main)
        self.assertIn('startswith(var.model_id, "global.")', self.main)
        self.assertIn('inference-profile/${var.model_id}', self.main)
        self.assertIn('bedrock:*::foundation-model/${local.foundation_model_id}', self.main)

    def test_private_coding_image_pull_is_scoped_to_its_repository(self) -> None:
        self.assertIn('sid       = "GetPrivateEcrToken"', self.main)
        self.assertIn('sid = "PullCodingContainer"', self.main)
        self.assertIn('"ecr:BatchGetImage"', self.main)
        self.assertIn('"ecr:GetDownloadUrlForLayer"', self.main)
        self.assertIn('resources = [statement.value]', self.main)
        self.assertIn('container_repository_arn', self.variables)
        self.assertIn('container_repository_arn is required when container_uri is set', self.main)
        self.assertRegex(self.composition, r'container_repository_arn\s+= "arn:aws:ecr:')

    def test_workspace_uses_per_session_managed_storage(self) -> None:
        self.assertIn('resource "terraform_data" "session_storage_environment"', self.main)
        self.assertIn('networkMode = "PUBLIC"', self.main)
        self.assertIn('sessionStorage', self.main)
        self.assertIn('session_storage_mount_path must be directly under /mnt', self.variables)
        self.assertIn('session_storage_mount_path', self.composition)
        self.assertNotIn('agentcore-workspace', self.composition)
        self.assertNotIn('elasticfilesystem:', self.main)

    def test_harness_attaches_the_iam_github_gateway_tools(self) -> None:
        self.assertIn('sid       = "InvokeGitHubReadGateway"', self.main)
        self.assertIn('actions   = ["bedrock-agentcore:InvokeGateway"]', self.main)
        self.assertIn('resources = [statement.value]', self.main)
        self.assertIn('type = "agentcore_gateway"', self.main)
        self.assertIn('name = "github-read"', self.main)
        self.assertIn('aws_iam = true', self.main)
        self.assertIn('"@github-read/listRepositories"', self.main)
        self.assertIn('"@github-read/getRepository"', self.main)
        self.assertIn('"@github-read/getFile"', self.main)
        self.assertIn('"@github-read/pullRepository"', self.main)
        self.assertIn('"@github-read/createBranch"', self.main)
        self.assertIn('"@github-read/putFile"', self.main)
        self.assertIn('"@github-read/createPullRequest"', self.main)
        self.assertIn('"@github-read/mergePullRequest"', self.main)
        self.assertIn('"@github-read/createIssue"', self.main)

    def test_prompt_describes_the_attached_tools_as_autonomous(self) -> None:
        self.assertIn("`listRepositories`", self.prompt)
        self.assertIn("`getRepository`", self.prompt)
        self.assertIn("`getFile`", self.prompt)
        self.assertIn("Never claim a tool call", self.prompt)
        self.assertIn("`putFile`", self.prompt)
        self.assertIn("`pullRepository`", self.prompt)
        self.assertIn("Do not\nask for a confirmation turn", self.prompt)
        self.assertIn('GH_TOKEN="$(github-app-token OWNER REPO)" gh <command>', self.prompt)
        self.assertIn("github-app-git-credential", self.prompt)
        self.assertIn("credential.useHttpPath=true", self.prompt)

    def test_execution_role_and_harness_have_no_unreviewed_capabilities(self) -> None:
        for forbidden in (
            "bedrock-mantle:",
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

    def test_temporary_git_credential_is_brokered_not_configured(self) -> None:
        self.assertIn('sid       = "MintTemporaryGitHubCredential"', self.main)
        self.assertIn('actions   = ["lambda:InvokeFunction"]', self.main)
        self.assertIn("environment_variables = {}", self.main)
        self.assertNotIn('resource "terraform_data" "credential_broker_environment"', self.main)
        self.assertNotIn("GITHUB_TOKEN", self.main)
        self.assertIn("github-app-token", (self.coding_image / "Dockerfile").read_text(encoding="utf-8"))
        token_helper = (self.coding_image / "github-app-token").read_text(encoding="utf-8")
        credential_helper = (self.coding_image / "github-app-git-credential").read_text(encoding="utf-8")
        self.assertIn('"operation": "mintGitCredential"', token_helper)
        self.assertIn("GITHUB_APP_TOKEN_BROKER_FUNCTION_NAME", token_helper)
        self.assertIn('os.environ.get("AWS_REGION")', token_helper)
        self.assertIn('DEFAULT_FUNCTION_NAME = "github-app-tool"', token_helper)
        self.assertIn('DEFAULT_REGION = "us-east-1"', token_helper)
        self.assertIn("github-app-token", credential_helper)
        self.assertNotIn("GITHUB_APP_PRIVATE_KEY", token_helper)

    def test_api_format_workaround_remains_explicit(self) -> None:
        self.assertIn('resource "terraform_data" "model_api_format"', self.main)
        self.assertIn("update-harness", self.main)
        self.assertIn("apiFormat", self.main)
        self.assertIn("var.top_p == null ? {} : { topP = var.top_p }", self.main)


if __name__ == "__main__":
    unittest.main()
