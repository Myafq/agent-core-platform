"""Behavioral tests for the agent-spec validation CLI."""

from __future__ import annotations

import copy
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = REPOSITORY_ROOT / "scripts" / "validate_spec.py"
SAMPLE_SPEC = REPOSITORY_ROOT / "agents" / "github-assistant" / "agent.yaml"


class ValidateSpecTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary_directory.name)
        self.agent_directory = self.workspace / "agent"
        self.agent_directory.mkdir()
        self.spec = yaml.safe_load(SAMPLE_SPEC.read_text(encoding="utf-8"))

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_spec(self) -> Path:
        (self.agent_directory / "prompts").mkdir(exist_ok=True)
        (self.agent_directory / "prompts" / "system.md").write_text(
            "You are a test agent.\n", encoding="utf-8"
        )
        spec_path = self.agent_directory / "agent.yaml"
        spec_path.write_text(yaml.safe_dump(self.spec), encoding="utf-8")
        return spec_path

    def validate(self, spec_path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), str(spec_path)],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_accepts_a_valid_spec(self) -> None:
        result = self.validate(self.write_spec())

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Valid:", result.stdout)

    def test_rejects_unknown_fields(self) -> None:
        self.spec["spec"]["unexpected"] = True

        result = self.validate(self.write_spec())

        self.assertEqual(result.returncode, 1)
        self.assertIn("Additional properties are not allowed", result.stderr)

    def test_rejects_out_of_range_values(self) -> None:
        self.spec["spec"]["model"]["temperature"] = 2.1

        result = self.validate(self.write_spec())

        self.assertEqual(result.returncode, 1)
        self.assertIn("greater than the maximum of 2", result.stderr)

    def test_rejects_unsupported_engine_and_provider(self) -> None:
        self.spec["spec"]["engine"]["type"] = "runtime"
        self.spec["spec"]["model"]["provider"] = "openai"

        result = self.validate(self.write_spec())

        self.assertEqual(result.returncode, 1)
        self.assertIn("'harness' was expected", result.stderr)
        self.assertIn("'bedrock' was expected", result.stderr)

    def test_rejects_prompt_references_outside_the_agent_directory(self) -> None:
        self.spec["spec"]["instructions"]["system"]["file"] = "../escaped.md"
        (self.workspace / "escaped.md").write_text("Not an agent prompt.\n", encoding="utf-8")

        result = self.validate(self.write_spec())

        self.assertEqual(result.returncode, 1)
        self.assertIn("escapes the agent directory", result.stderr)

    def test_rejects_missing_prompts(self) -> None:
        self.spec["spec"]["instructions"]["system"]["file"] = "prompts/missing.md"

        result = self.validate(self.write_spec())

        self.assertEqual(result.returncode, 1)
        self.assertIn("Referenced prompt does not exist", result.stderr)


if __name__ == "__main__":
    unittest.main()
