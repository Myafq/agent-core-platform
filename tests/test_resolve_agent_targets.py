"""Behavioral tests for the agent target-resolution CLI."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RESOLVER = REPOSITORY_ROOT / "scripts" / "resolve_agent_targets.py"


class ResolveAgentTargetsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary_directory.name)
        self.git("init", "--quiet")
        self.git("config", "user.name", "Test User")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "commit.gpgsign", "false")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def git(self, *arguments: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.repo), *arguments],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def write_agent(self, name: str) -> None:
        agent_directory = self.repo / "agents" / name
        (agent_directory / "prompts").mkdir(parents=True, exist_ok=True)
        (agent_directory / "agent.yaml").write_text(
            f"metadata:\n  name: {name}\n", encoding="utf-8"
        )
        (agent_directory / "prompts" / "system.md").write_text(
            f"You are {name}.\n", encoding="utf-8"
        )

    def commit_all(self, message: str) -> str:
        self.git("add", "--all")
        self.git("commit", "--quiet", "--message", message)
        return self.git("rev-parse", "HEAD")

    def resolve(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(RESOLVER),
                "--repo-root",
                str(self.repo),
                *arguments,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_enumerates_all_manifests_sorted(self) -> None:
        self.write_agent("beta")
        self.write_agent("alpha")

        result = self.resolve()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["agents/alpha/agent.yaml", "agents/beta/agent.yaml"],
        )

    def test_diff_emits_only_the_added_agent(self) -> None:
        self.write_agent("alpha")
        base = self.commit_all("add alpha")
        self.write_agent("beta")
        head = self.commit_all("add beta")

        result = self.resolve("--diff", base, head)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["agents/beta/agent.yaml"])

    def test_diff_emits_agent_with_a_modified_prompt(self) -> None:
        self.write_agent("alpha")
        base = self.commit_all("add alpha")
        (self.repo / "agents" / "alpha" / "prompts" / "system.md").write_text(
            "You are alpha, revised.\n", encoding="utf-8"
        )
        head = self.commit_all("revise prompt")

        result = self.resolve("--diff", base, head)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["agents/alpha/agent.yaml"])

    def test_removed_manifest_fails_without_acknowledgement(self) -> None:
        self.write_agent("alpha")
        base = self.commit_all("add alpha")
        self.git("rm", "--quiet", "-r", "agents/alpha")
        head = self.commit_all("remove alpha")

        result = self.resolve("--diff", base, head)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("agents/alpha/agent.yaml", result.stderr)
        self.assertIn("manifest absence never authorizes destroy", result.stderr)

    def test_removed_manifest_requires_retirement_output(self) -> None:
        self.write_agent("alpha")
        base = self.commit_all("add alpha")
        self.git("rm", "--quiet", "-r", "agents/alpha")
        head = self.commit_all("remove alpha")

        result = self.resolve("--diff", base, head, "--allow-retire", "alpha")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("requires --retirement-output PATH", result.stderr)

    def test_removed_manifest_writes_operational_retirement_descriptor(self) -> None:
        self.write_agent("alpha")
        self.write_agent("beta")
        base = self.commit_all("add agents")
        self.git("rm", "--quiet", "-r", "agents/alpha")
        head = self.commit_all("remove alpha")
        output = self.repo / "artifacts" / "retirements.json"

        result = self.resolve(
            "--diff",
            base,
            head,
            "--allow-retire",
            "alpha",
            "--retirement-output",
            str(output),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("Acknowledged retirement of agents/alpha/agent.yaml", result.stderr)
        self.assertIn(str(output), result.stderr)

        descriptor = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(descriptor["schema_version"], 1)
        self.assertEqual(descriptor["base_revision"], base)
        self.assertEqual(descriptor["head_revision"], head)
        self.assertEqual(len(descriptor["retirements"]), 1)
        retirement = descriptor["retirements"][0]
        self.assertEqual(retirement["manifest_target"], "agents/alpha/agent.yaml")
        self.assertEqual(retirement["manifest_source_revision"], base)
        self.assertEqual(retirement["planned_revision"], head)
        self.assertEqual(retirement["state_key"], "agents/alpha/terraform.tfstate")
        self.assertEqual(retirement["plan_mode"], "destroy")
        self.assertTrue(retirement["requires_reviewed_destroy"])
        self.assertRegex(retirement["manifest_tree_oid"], r"^[0-9a-f]{40}$")
        procedure = retirement["materialize_and_plan"]
        self.assertEqual(
            procedure["expected_manifest_tree_oid"],
            retirement["manifest_tree_oid"],
        )
        commands = "\n".join(procedure["steps"])
        self.assertIn(f"worktree add --detach", commands)
        self.assertIn(head, commands)
        self.assertIn(f"archive {base} -- agents/alpha", commands)
        self.assertIn(f"rev-parse {base}:agents/alpha", commands)
        self.assertIn(retirement["manifest_tree_oid"], commands)
        self.assertIn('test ! -e "${RETIREMENT_WORKTREE}/.venv"', commands)
        self.assertIn(
            'python3 -m venv "${RETIREMENT_WORKTREE}/.venv"', commands
        )
        self.assertIn(
            '"${RETIREMENT_WORKTREE}/.venv/bin/python" -m pip install '
            '--requirement "${RETIREMENT_WORKTREE}/requirements-dev.txt"',
            commands,
        )
        self.assertIn("MANIFEST_TARGET=agents/alpha/agent.yaml", commands)
        self.assertIn("terragrunt plan -destroy", commands)
        self.assertLess(
            commands.index("python3 -m venv"), commands.index("terragrunt")
        )

    def test_retirement_output_is_not_overwritten(self) -> None:
        self.write_agent("alpha")
        base = self.commit_all("add alpha")
        self.git("rm", "--quiet", "-r", "agents/alpha")
        head = self.commit_all("remove alpha")
        output = self.repo / "retirements.json"
        output.write_text("preserve me\n", encoding="utf-8")

        result = self.resolve(
            "--diff",
            base,
            head,
            "--allow-retire",
            "alpha",
            "--retirement-output",
            str(output),
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("Refusing to overwrite retirement output", result.stderr)
        self.assertEqual(output.read_text(encoding="utf-8"), "preserve me\n")

    def test_unmatched_retirement_acknowledgement_is_an_error(self) -> None:
        self.write_agent("alpha")
        base = self.commit_all("add alpha")
        (self.repo / "agents" / "alpha" / "prompts" / "system.md").write_text(
            "changed\n", encoding="utf-8"
        )
        head = self.commit_all("change alpha")
        output = self.repo / "retirements.json"

        result = self.resolve(
            "--diff",
            base,
            head,
            "--allow-retire",
            "alpha",
            "--retirement-output",
            str(output),
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("did not match any removed manifest", result.stderr)
        self.assertFalse(output.exists())

    def test_rename_is_gated_as_retirement_plus_addition(self) -> None:
        self.write_agent("alpha")
        base = self.commit_all("add alpha")
        self.git("mv", "agents/alpha", "agents/gamma")
        head = self.commit_all("rename alpha to gamma")

        ungated = self.resolve("--diff", base, head)
        self.assertEqual(ungated.returncode, 1)
        self.assertEqual(ungated.stdout, "")
        self.assertIn("agents/alpha/agent.yaml", ungated.stderr)
        self.assertIn("manifest absence never authorizes destroy", ungated.stderr)

        output = self.repo / "retirement.json"
        gated = self.resolve(
            "--diff",
            base,
            head,
            "--allow-retire",
            "alpha",
            "--retirement-output",
            str(output),
        )
        self.assertEqual(gated.returncode, 0, gated.stderr)
        self.assertEqual(gated.stdout.splitlines(), ["agents/gamma/agent.yaml"])
        descriptor = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(
            [item["name"] for item in descriptor["retirements"]], ["alpha"]
        )

    def test_shared_agent_changes_fan_out_to_every_head_manifest(self) -> None:
        self.write_agent("alpha")
        self.write_agent("beta")
        base = self.commit_all("add agents")
        shared_paths = [
            "entrypoints/agents/terragrunt.hcl",
            "compositions/agents/main.tf",
            "modules/agentcore-harness/main.tf",
            "schemas/agent-v1alpha1.schema.json",
            "scripts/validate_spec.py",
        ]

        for index, relative_path in enumerate(shared_paths):
            with self.subTest(path=relative_path):
                path = self.repo / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"change {index}\n", encoding="utf-8")
                head = self.commit_all(f"change {relative_path}")

                result = self.resolve("--diff", base, head)

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    result.stdout.splitlines(),
                    ["agents/alpha/agent.yaml", "agents/beta/agent.yaml"],
                )
                base = head

    def test_shared_change_uses_base_head_union_and_gates_removed_manifest(self) -> None:
        self.write_agent("alpha")
        self.write_agent("beta")
        base = self.commit_all("add agents")
        self.git("rm", "--quiet", "-r", "agents/alpha")
        shared = self.repo / "compositions" / "agents" / "main.tf"
        shared.parent.mkdir(parents=True)
        shared.write_text("shared change\n", encoding="utf-8")
        head = self.commit_all("remove alpha and change composition")

        ungated = self.resolve("--diff", base, head)
        self.assertEqual(ungated.returncode, 1)
        self.assertEqual(ungated.stdout, "")
        self.assertIn("agents/alpha/agent.yaml", ungated.stderr)

        output = self.repo / "retirements.json"
        gated = self.resolve(
            "--diff",
            base,
            head,
            "--allow-retire",
            "alpha",
            "--retirement-output",
            str(output),
        )
        self.assertEqual(gated.returncode, 0, gated.stderr)
        self.assertEqual(gated.stdout.splitlines(), ["agents/beta/agent.yaml"])
        descriptor = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(
            [item["name"] for item in descriptor["retirements"]], ["alpha"]
        )

    def test_rejects_invalid_directory_names_in_diff_mode(self) -> None:
        self.write_agent("alpha")
        base = self.commit_all("add alpha")
        self.write_agent("Bad_Name")
        head = self.commit_all("add invalid agent")

        result = self.resolve("--diff", base, head)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("Invalid agent directory name 'Bad_Name'", result.stderr)

    def test_rejects_invalid_directory_names_in_enumerate_mode(self) -> None:
        self.write_agent("alpha")
        self.write_agent("Bad_Name")

        result = self.resolve()

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("Invalid agent directory name 'Bad_Name'", result.stderr)

    def test_errors_when_changed_tree_has_no_manifest_at_head(self) -> None:
        self.write_agent("alpha")
        base = self.commit_all("add alpha")
        notes = self.repo / "agents" / "orphan" / "notes.md"
        notes.parent.mkdir(parents=True)
        notes.write_text("No manifest here.\n", encoding="utf-8")
        head = self.commit_all("add orphan files")

        result = self.resolve("--diff", base, head)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("agents/orphan/agent.yaml does not exist", result.stderr)


if __name__ == "__main__":
    unittest.main()
