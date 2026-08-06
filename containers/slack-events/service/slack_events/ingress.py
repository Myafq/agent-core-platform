"""Lambda HTTP ingress for signed Slack Events requests."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any, Mapping

from slack_events.core import DEFAULT_PARAMETER_PREFIX, EventDispatcher, ParameterReader, SlackEventsError, ingress_response


LOG = logging.getLogger(__name__)
LOG.setLevel(os.getenv("LOG_LEVEL", "INFO"))


class SsmParameterReader(ParameterReader):
    def __init__(self, client: Any) -> None:
        self.client = client

    def get(self, name: str, *, decrypt: bool) -> str | None:
        try:
            result = self.client.get_parameter(Name=name, WithDecryption=decrypt)
        except self.client.exceptions.ParameterNotFound:
            return None
        value = result.get("Parameter", {}).get("Value")
        return value if isinstance(value, str) else None


class SqsFifoDispatcher(EventDispatcher):
    def __init__(self, client: Any, queue_url: str) -> None:
        self.client = client
        self.queue_url = queue_url

    def dispatch(self, envelope: Mapping[str, Any]) -> None:
        agent = envelope["agent"]
        event_id = envelope["event_id"]
        app_id = envelope.get("app_id")
        event = envelope.get("event")
        if not isinstance(agent, str) or not isinstance(event_id, str) or not isinstance(app_id, str) or not isinstance(event, Mapping):
            raise SlackEventsError("queue_invalid")
        channel_id = event.get("channel")
        thread_ts = event.get("thread_ts") or event.get("ts")
        if not isinstance(channel_id, str) or not isinstance(thread_ts, str):
            raise SlackEventsError("queue_invalid")
        self.client.send_message(
            QueueUrl=self.queue_url,
            MessageBody=json.dumps(dict(envelope), separators=(",", ":"), sort_keys=True),
            MessageGroupId=hashlib.sha256(f"{app_id}:{channel_id}:{thread_ts}".encode("utf-8")).hexdigest(),
            MessageDeduplicationId=hashlib.sha256(event_id.encode("utf-8")).hexdigest(),
        )


def _response(status: int) -> dict[str, Any]:
    return {"statusCode": status, "headers": {"Content-Type": "application/json"}, "body": "{\"ok\":false}"}


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = getattr(context, "aws_request_id", "unknown")
    try:
        prefix = os.getenv("SLACK_AGENT_PARAMETER_PREFIX", DEFAULT_PARAMETER_PREFIX)
        queue_url = os.environ["SLACK_EVENT_QUEUE_URL"]
        response = ingress_response(event, SsmParameterReader(_ssm_client()), SqsFifoDispatcher(_sqs_client(), queue_url), prefix=prefix, now=int(time.time()))
        LOG.info("slack_events_ingress request_id=%s result=accepted", request_id)
        return response
    except SlackEventsError as error:
        status = 401 if error.log_class.startswith(("signature", "timestamp", "routing")) else 400
        LOG.warning("slack_events_ingress request_id=%s error_class=%s", request_id, error.log_class)
        return _response(status)
    except Exception:
        LOG.error("slack_events_ingress request_id=%s error_class=internal_error", request_id)
        return _response(500)


def _ssm_client() -> Any:
    import boto3

    return boto3.client("ssm")


def _sqs_client() -> Any:
    import boto3

    return boto3.client("sqs")
