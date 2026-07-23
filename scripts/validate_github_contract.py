#!/usr/bin/env python3
"""Validate the offline GitHub OpenAPI and wiring contracts."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml


EXPECTED_SERVER = "https://api.github.com"
EXPECTED_SCOPE = "read:user"
EXPECTED_OPERATION_ID = "getAuthenticatedUser"


def fail(message: str) -> None:
    raise ValueError(message)


def reject_forbidden_openapi_fields(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"security", "securitySchemes"}:
                fail(f"OpenAPI security credentials are not allowed at {path}.{key}")
            if key in {"headers", "requestBody"}:
                fail(f"OpenAPI {key} is not allowed at {path}.{key}")
            reject_forbidden_openapi_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_forbidden_openapi_fields(child, f"{path}[{index}]")


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        fail(f"cannot read {path}: {error}")
    if not isinstance(value, dict):
        fail(f"{path} must contain a YAML mapping")
    return value


def validate_openapi(document: dict[str, Any]) -> None:
    if document.get("openapi") != "3.0.3":
        fail("OpenAPI version must be 3.0.3")
    servers = document.get("servers")
    if servers != [{"url": EXPECTED_SERVER}]:
        fail(f"servers must contain only {EXPECTED_SERVER}")

    paths = document.get("paths")
    if not isinstance(paths, dict) or set(paths) != {"/user"}:
        fail("paths must contain exactly /user")
    user_path = paths["/user"]
    if not isinstance(user_path, dict) or set(user_path) != {"get"}:
        fail("/user must contain exactly GET")
    operation = user_path["get"]
    if not isinstance(operation, dict):
        fail("GET /user must be an operation object")
    if operation.get("operationId") != EXPECTED_OPERATION_ID:
        fail(f"operationId must be {EXPECTED_OPERATION_ID}")
    if any(key in operation for key in ("security", "requestBody", "parameters")):
        fail("GET /user must not define security, requestBody, or parameters")

    responses = operation.get("responses")
    if not isinstance(responses, dict) or not {"200", "401", "403", "default"} <= set(responses):
        fail("GET /user must define 200, 401, 403, and default responses")
    success_schema = responses["200"].get("content", {}).get("application/json", {}).get("schema", {})
    if not isinstance(success_schema, dict):
        fail("200 response must define an application/json schema")
    if success_schema.get("$ref") != "#/components/schemas/AuthenticatedUser":
        fail("200 response must use AuthenticatedUser")
    user_schema = document.get("components", {}).get("schemas", {}).get("AuthenticatedUser", {})
    required = set(user_schema.get("required", [])) if isinstance(user_schema, dict) else set()
    if not {"login", "id", "html_url"} <= required:
        fail("AuthenticatedUser must require login, id, and html_url")
    reject_forbidden_openapi_fields(document)


def validate_wiring(contract: dict[str, Any]) -> None:
    if contract.get("provider", {}).get("name") != "github-assistant-oauth":
        fail("provider name is incorrect")
    if contract.get("gateway", {}).get("name") != "github-assistant-gateway":
        fail("gateway name is incorrect")
    target = contract.get("target", {})
    if target.get("name") != "github-current-user" or target.get("server") != "github":
        fail("target name or Harness server name is incorrect")
    provider = contract["provider"]
    if provider.get("grant") != "AUTHORIZATION_CODE":
        fail("OAuth grant must be AUTHORIZATION_CODE")
    if provider.get("scopes") != [EXPECTED_SCOPE]:
        fail("OAuth scopes must be exactly [read:user]")
    return_url_input = contract.get("post_consent", {}).get("return_url_input")
    if not isinstance(return_url_input, str) or not return_url_input.strip():
        fail("post-consent return URL must reference a required input")
    if contract["post_consent"].get("required") is not True:
        fail("post-consent return URL input must be required")
    lowered_input = return_url_input.lower()
    if "://" in return_url_input or "localhost" in lowered_input or "token" in lowered_input:
        fail("post-consent return URL reference must not contain a URL, localhost, or token")


def validate(openapi_path: Path, wiring_path: Path) -> None:
    validate_openapi(load_yaml(openapi_path))
    validate_wiring(load_yaml(wiring_path))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--openapi", type=Path, default=Path("contracts/github/openapi.yaml"))
    parser.add_argument("--wiring", type=Path, default=Path("contracts/github/integration.yaml"))
    args = parser.parse_args()
    try:
        validate(args.openapi, args.wiring)
    except ValueError as error:
        parser.error(str(error))
    print("GitHub integration contract is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
