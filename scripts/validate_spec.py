#!/usr/bin/env python3
"""Validate an AgentCore declarative agent specification and local references."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

try:
    import jsonschema
    import yaml
except ModuleNotFoundError as error:
    dependency = error.name
    print(
        f"Missing validation dependency {dependency!r}. "
        "Install requirements-dev.txt in a virtual environment.",
        file=sys.stderr,
    )
    raise SystemExit(2) from None


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPOSITORY_ROOT / "schemas" / "agent-v1alpha1.schema.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("spec", type=Path, help="Path to agent.yaml")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    spec_path = args.spec.resolve()

    with SCHEMA_PATH.open(encoding="utf-8") as schema_file:
        schema = json.load(schema_file)
    with spec_path.open(encoding="utf-8") as spec_file:
        spec = yaml.safe_load(spec_file)

    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(spec), key=lambda error: list(error.path))
    if errors:
        for error in errors:
            location = ".".join(str(part) for part in error.absolute_path) or "<root>"
            print(f"{location}: {error.message}", file=sys.stderr)
        return 1

    prompt_reference = spec["spec"]["instructions"]["system"]["file"]
    prompt_path = (spec_path.parent / prompt_reference).resolve()
    try:
        prompt_path.relative_to(spec_path.parent)
    except ValueError:
        print("spec.instructions.system.file escapes the agent directory", file=sys.stderr)
        return 1

    if not prompt_path.is_file():
        print(f"Referenced prompt does not exist: {prompt_path}", file=sys.stderr)
        return 1
    if not prompt_path.read_text(encoding="utf-8").strip():
        print(f"Referenced prompt is empty: {prompt_path}", file=sys.stderr)
        return 1

    print(f"Valid: {spec_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
