#!/usr/bin/env python3
"""Validate the checked-in channel and GitHub read-tool contract fixtures."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contracts.contract_validation import (  # noqa: E402
    load_json,
    validate_channel_message,
    validate_tool_invocation,
    validate_tool_response,
)


def main() -> int:
    contracts = ROOT / "contracts"
    validate_channel_message(load_json(contracts / "channel_message.json"))
    allowed = {"example-org/example-repo"}
    validate_tool_invocation(load_json(contracts / "github" / "get_repository.json"), allowed)
    validate_tool_invocation(load_json(contracts / "github" / "get_file.json"), allowed)
    validate_tool_response(load_json(contracts / "github" / "get_file_response.json"))
    print("Channel and GitHub tool contracts are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
