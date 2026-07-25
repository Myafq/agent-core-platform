"""Tests for the frozen channel and GitHub read-tool contracts."""

from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contracts.contract_validation import (  # noqa: E402
    ContractError,
    load_json,
    runtime_user_id,
    session_id,
    validate_channel_message,
    validate_tool_invocation,
    validate_tool_response,
)


class ContractValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.channel_message = load_json(ROOT / "contracts" / "channel_message.json")
        self.get_repository = load_json(ROOT / "contracts" / "github" / "get_repository.json")
        self.get_file = load_json(ROOT / "contracts" / "github" / "get_file.json")
        self.get_file_response = load_json(ROOT / "contracts" / "github" / "get_file_response.json")
        self.allowed = {"example-org/example-repo"}

    def test_channel_message_and_identity_are_stable_and_partitioned(self) -> None:
        self.assertEqual(runtime_user_id(self.channel_message), runtime_user_id(self.channel_message))
        self.assertEqual(session_id(self.channel_message), session_id(self.channel_message))
        other_channel = copy.deepcopy(self.channel_message)
        other_channel["channel"] = "slack"
        self.assertNotEqual(runtime_user_id(self.channel_message), runtime_user_id(other_channel))
        self.assertNotEqual(session_id(self.channel_message), session_id(other_channel))

    def test_channel_message_rejects_unknown_fields(self) -> None:
        message = copy.deepcopy(self.channel_message)
        message["runtimeUserId"] = "model-supplied"
        with self.assertRaisesRegex(ContractError, "Additional properties"):
            validate_channel_message(message)

    def test_tool_invocations_accept_only_reviewed_read_tools(self) -> None:
        validate_tool_invocation(self.get_repository, self.allowed)
        validate_tool_invocation(self.get_file, self.allowed)
        unknown = copy.deepcopy(self.get_file)
        unknown["tool"] = "deleteRepository"
        with self.assertRaises(ContractError):
            validate_tool_invocation(unknown, self.allowed)

    def test_tool_invocations_reject_transport_and_mutation_inputs(self) -> None:
        for field in ("url", "method", "headers", "body"):
            invocation = copy.deepcopy(self.get_file)
            invocation["arguments"][field] = "untrusted"
            with self.subTest(field=field), self.assertRaises(ContractError):
                validate_tool_invocation(invocation, self.allowed)

    def test_tool_invocations_reject_unconfigured_repository_and_unsafe_path_or_ref(self) -> None:
        unconfigured = copy.deepcopy(self.get_file)
        unconfigured["arguments"]["repo"] = "other-repo"
        with self.assertRaisesRegex(ContractError, "not allowed"):
            validate_tool_invocation(unconfigured, self.allowed)
        for field, value in (("path", "../secret"), ("path", "/etc/passwd"), ("ref", "../main"), ("ref", "main//next")):
            invocation = copy.deepcopy(self.get_file)
            invocation["arguments"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ContractError):
                validate_tool_invocation(invocation, self.allowed)

    def test_tool_response_rejects_unknown_and_oversized_content(self) -> None:
        response = copy.deepcopy(self.get_file_response)
        response["file"]["token"] = "secret"
        with self.assertRaises(ContractError):
            validate_tool_response(response)
        response = copy.deepcopy(self.get_file_response)
        response["file"]["content"] = "x" * 65537
        with self.assertRaises(ContractError):
            validate_tool_response(response)


if __name__ == "__main__":
    unittest.main()
