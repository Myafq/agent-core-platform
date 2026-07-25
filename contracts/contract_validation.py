"""Shared validation and deterministic identifiers for channel and tool contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"


class ContractError(ValueError):
    """An input or output does not satisfy a frozen public contract."""


def derived_id(namespace: str, *parts: str) -> str:
    """Return a stable, pseudonymous identifier for a trusted adapter value."""
    if not all(isinstance(part, str) and part for part in parts):
        raise ContractError("identifier parts must be non-empty strings")
    digest = hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()
    return f"{namespace}-{digest}"


def runtime_user_id(message: dict[str, Any]) -> str:
    validate_channel_message(message)
    return derived_id("user", message["channel"], message["tenant_id"], message["user_id"])


def session_id(message: dict[str, Any]) -> str:
    validate_channel_message(message)
    return derived_id("session", message["channel"], message["tenant_id"], message["conversation_id"])


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate(instance: dict[str, Any], schema_name: str) -> None:
    schema = load_json(SCHEMAS / schema_name)
    errors = sorted(Draft202012Validator(schema).iter_errors(instance), key=lambda error: list(error.path))
    if errors:
        location = ".".join(str(part) for part in errors[0].absolute_path) or "<root>"
        raise ContractError(f"{location}: {errors[0].message}")


def validate_channel_message(message: dict[str, Any]) -> None:
    _validate(message, "channel-message-v1alpha1.schema.json")


def validate_tool_invocation(invocation: dict[str, Any], allowed_repositories: Iterable[str]) -> None:
    _validate(invocation, "github-tool-invocation-v1alpha1.schema.json")
    arguments = invocation["arguments"]
    repository = f"{arguments['owner']}/{arguments['repo']}"
    if repository not in set(allowed_repositories):
        raise ContractError("repository is not allowed")


def validate_tool_response(response: dict[str, Any]) -> None:
    _validate(response, "github-tool-response-v1alpha1.schema.json")
