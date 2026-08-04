"""Lambda entrypoint for `GET /slack/oauth/callback` behind API Gateway (HTTP API, payload format 2.0)."""

from __future__ import annotations

import html
import logging
import os
from typing import Any

from services.slack_oauth_callback.callback import (
    CallbackConfig,
    CallbackError,
    SsmParameterStore,
    UrllibSlackOAuthClient,
    complete_installation,
)

LOG = logging.getLogger(__name__)
LOG.setLevel(os.getenv("LOG_LEVEL", "INFO"))


def _page(title: str, message: str, correlation_id: str | None) -> str:
    reference = f"<p>Reference: {html.escape(correlation_id)}</p>" if correlation_id else ""
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{html.escape(title)}</title></head><body>"
        f"<h1>{html.escape(title)}</h1>"
        f"<p>{html.escape(message)}</p>"
        f"{reference}"
        "</body></html>"
    )


def _response(status: int, title: str, message: str, correlation_id: str | None = None) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"},
        "body": _page(title, message, correlation_id),
    }


def _query_parameters(event: dict[str, Any]) -> dict[str, str]:
    query = event.get("queryStringParameters")
    if not isinstance(query, dict):
        return {}
    return {key: value for key, value in query.items() if isinstance(key, str) and isinstance(value, str)}


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    correlation_id = getattr(context, "aws_request_id", "unknown")
    try:
        config = CallbackConfig.from_environment()
        parameters = SsmParameterStore(_ssm_client())
        result = complete_installation(_query_parameters(event), parameters, UrllibSlackOAuthClient(), config)
        LOG.info(
            "slack_oauth_callback request_id=%s agent=%s app_id=%s bot_user_id=%s scopes=%d result=success",
            correlation_id,
            result.agent_name,
            result.app_id,
            result.bot_user_id or "unknown",
            len(result.granted_scopes),
        )
        return _response(200, "Installation complete", "The Slack app was installed successfully. You may close this window.")
    except CallbackError as error:
        LOG.warning("slack_oauth_callback request_id=%s error_class=%s", correlation_id, error.log_class)
        return _response(400, "Installation failed", error.safe_message, correlation_id)
    except Exception:
        LOG.error("slack_oauth_callback request_id=%s error_class=internal_error", correlation_id)
        return _response(500, "Installation failed", "An unexpected error occurred. Try again or contact the operator.", correlation_id)


def _ssm_client() -> Any:
    import boto3

    return boto3.client("ssm")
