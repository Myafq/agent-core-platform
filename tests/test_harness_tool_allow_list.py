"""Static contract tests for manifest-declared Harness tool capabilities.

The Harness allow-list must be assembled from what a manifest requests, never
from the incidental presence of another capability. These tests pin that the
three groups (built-ins, gateway operations, Code Interpreter) are independent
and that requesting nothing still denies everything.
"""

from __future__ import annotations

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "modules" / "agentcore-harness"
COMPOSITION = ROOT / "compositions" / "agents"
ENTRYPOINT = ROOT / "entrypoints" / "agents" / "terragrunt.hcl"
SCHEMA = ROOT / "schemas" / "agent-v1alpha1.schema.json"
GITHUB_ASSISTANT = ROOT / "agents" / "github-assistant" / "agent.yaml"


class HarnessToolAllowListTests(unittest.TestCase):
    def setUp(self) -> None:
        self.main = (MODULE / "main.tf").read_text(encoding="utf-8")
        self.variables = (MODULE / "variables.tf").read_text(encoding="utf-8")
        self.composition_main = (COMPOSITION / "main.tf").read_text(encoding="utf-8")
        self.composition_variables = (COMPOSITION / "variables.tf").read_text(encoding="utf-8")
        self.entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
        self.schema = SCHEMA.read_text(encoding="utf-8")

    def test_allow_list_is_composed_from_independent_capability_groups(self) -> None:
        self.assertIn("allowed_tools = local.allowed_tools", self.main)
        self.assertIn(
            'builtin_tool_entries = [for builtin in var.allowed_builtin_tools : "@builtin/${builtin}"]',
            self.main,
        )
        self.assertIn("gateway_tool_entries = var.gateway_arn == null ? [] : [", self.main)
        self.assertIn(
            'code_interpreter_tool_entries = var.enable_code_interpreter ? ["@${local.code_interpreter_tool_name}"] : []',
            self.main,
        )
        self.assertIn("requested_tools = concat(", self.main)

        # The retired coupling: built-ins must not depend on a gateway ARN.
        self.assertNotIn('var.gateway_arn == null ? ["@disabled"] : [', self.main)
        self.assertNotIn('"@builtin/shell",', self.main)

    def test_requesting_no_tool_denies_every_tool(self) -> None:
        self.assertIn(
            'allowed_tools = length(local.requested_tools) == 0 ? ["@disabled"] : local.requested_tools',
            self.main,
        )

    def test_builtin_tool_names_are_closed_at_module_and_binding(self) -> None:
        self.assertIn('contains(["shell", "file_operations"], builtin)', self.variables)
        self.assertIn("allowed_builtin_tools may contain only shell and file_operations", self.variables)
        self.assertIn('known_builtins     = ["shell", "file_operations"]', self.entrypoint)
        self.assertIn("guard_builtins", self.entrypoint)
        self.assertIn("names unknown built-in tool(s)", self.entrypoint)

    def test_code_interpreter_is_opt_in_and_scoped_to_the_managed_sandbox(self) -> None:
        self.assertIn('variable "enable_code_interpreter"', self.variables)
        self.assertIn("default     = false", self.variables)
        self.assertIn('type = "agentcore_code_interpreter"', self.main)
        self.assertIn('sid = "AgentCoreCodeInterpreterDefault"', self.main)
        for action in (
            "StartCodeInterpreterSession",
            "StopCodeInterpreterSession",
            "GetCodeInterpreterSession",
            "ListCodeInterpreterSessions",
            "InvokeCodeInterpreter",
        ):
            self.assertIn(f'"bedrock-agentcore:{action}"', self.main)
        self.assertIn(
            'resources = ["arn:${data.aws_partition.current.partition}:bedrock-agentcore:'
            '${data.aws_region.current.region}:aws:code-interpreter/*"]',
            self.main,
        )
        # The managed sandbox is service-owned: no customer interpreter is
        # created and no config block names one.
        self.assertNotIn("aws_bedrockagentcore_code_interpreter", self.main)
        self.assertNotIn("agentcore_code_interpreter {", self.main)
        self.assertNotIn("code_interpreter_arn =", self.main)

    def test_capabilities_are_declared_in_the_manifest_and_passed_through(self) -> None:
        self.assertIn('"builtins"', self.schema)
        self.assertIn('"codeInterpreter": {"type": "boolean"}', self.schema)
        self.assertIn('{"enum": ["shell", "file_operations"]}', self.schema)
        self.assertIn("requested_builtins = try(local.manifest.spec.tools.builtins, [])", self.entrypoint)
        self.assertIn(
            "use_code_interpreter = try(local.manifest.spec.tools.codeInterpreter, false)",
            self.entrypoint,
        )
        self.assertIn("allowed_builtin_tools                 = local.allowed_builtin_tools", self.entrypoint)
        self.assertIn("enable_code_interpreter               = local.use_code_interpreter", self.entrypoint)
        self.assertIn("allowed_builtin_tools                 = var.allowed_builtin_tools", self.composition_main)
        self.assertIn("enable_code_interpreter               = var.enable_code_interpreter", self.composition_main)
        self.assertIn('variable "allowed_builtin_tools"', self.composition_variables)
        self.assertIn('variable "enable_code_interpreter"', self.composition_variables)

    def test_github_assistant_declares_the_builtins_it_had_implicitly(self) -> None:
        manifest = yaml.safe_load(GITHUB_ASSISTANT.read_text(encoding="utf-8"))
        tools = manifest["spec"]["tools"]
        self.assertEqual(tools["builtins"], ["shell", "file_operations"])
        self.assertEqual(tools["gateways"], ["github-app-tool"])
        self.assertNotIn("codeInterpreter", tools)


if __name__ == "__main__":
    unittest.main()
