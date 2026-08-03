"""Lambda entrypoint. Gateway adapters must pass the frozen invocation object."""

from __future__ import annotations

import logging
import json
import os
from typing import Any

from services.github_tool.broker import BrokerConfig, BrokerError, GitHubBroker, PyJwtSigner, UrllibGitHubClient

LOG = logging.getLogger(__name__)
LOG.setLevel(os.getenv("LOG_LEVEL", "INFO"))
ALLOWED_TOOLS = frozenset({"listRepositories", "getRepository", "getFile", "pullRepository", "createBranch", "putFile", "createPullRequest", "mergePullRequest", "createIssue"})


class SecretsManagerReader:
    def __init__(self, secret_key: str) -> None:
        import boto3

        self.client = boto3.client("secretsmanager")
        self.secret_key = secret_key

    def get_secret_string(self, secret_arn: str) -> str:
        value = self.client.get_secret_value(SecretId=secret_arn).get("SecretString")
        try:
            private_key = json.loads(value)[self.secret_key]
        except (TypeError, KeyError, json.JSONDecodeError) as error:
            raise BrokerError("secret_unavailable") from error
        if not isinstance(private_key, str):
            raise BrokerError("secret_unavailable")
        return private_key


def gateway_tool_name(context: Any) -> str:
    """Read the Lambda-target tool name from AgentCore's client context."""
    custom = getattr(getattr(context, "client_context", None), "custom", {})
    if not isinstance(custom, dict):
        raise BrokerError("invalid_request")
    full_name = custom.get("bedrockAgentCoreToolName")
    if not isinstance(full_name, str):
        raise BrokerError("invalid_request")
    _, delimiter, tool_name = full_name.rpartition("___")
    if delimiter != "___" or tool_name not in ALLOWED_TOOLS:
        raise BrokerError("invalid_request")
    return tool_name


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = getattr(context, "aws_request_id", "unknown")
    try:
        config = BrokerConfig.from_environment()
        tool_name = gateway_tool_name(context)
        result = GitHubBroker(config, SecretsManagerReader(config.private_key_secret_key), PyJwtSigner(), UrllibGitHubClient()).execute({"tool": tool_name, "arguments": event})
        LOG.info("github request_id=%s tool=%s result=success", request_id, tool_name)
        return result
    except BrokerError as error:
        LOG.warning("github request_id=%s error_class=%s", request_id, error)
        return {"error": "github_unavailable"}
    except Exception:
        LOG.error("github request_id=%s error_class=internal_error", request_id)
        return {"error": "github_unavailable"}
