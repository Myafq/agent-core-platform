"""SQS worker for normalized Slack events."""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Mapping

from clients.channel.core import invoke_harness
from slack_events.core import (
    DEFAULT_PARAMETER_PREFIX,
    HarnessInvoker,
    ParameterReader,
    SlackEventsError,
    SlackPoster,
    SlackStateStore,
    SlackWorker,
    load_agent,
    state_hash,
)
from slack_events.ingress import SsmParameterReader


LOG = logging.getLogger(__name__)
LOG.setLevel(os.getenv("LOG_LEVEL", "INFO"))
SLACK_MESSAGE_LIMIT = 4000
EVENT_LEASE_SECONDS = 240


class DynamoSlackState(SlackStateStore):
    """Durable state that stores hashed Slack identifiers and no message text."""

    def __init__(self, client: Any, table_name: str, *, event_ttl_seconds: int = 86400) -> None:
        self.client = client
        self.table_name = table_name
        self.event_ttl_seconds = event_ttl_seconds
        self._claims: dict[tuple[str, str], str] = {}

    def _key(self, tenant_id: str, record_type: str, *identifiers: str) -> dict[str, dict[str, str]]:
        return {
            "pk": {"S": state_hash("tenant", tenant_id)},
            "sk": {"S": f"{record_type}#{state_hash(record_type, *identifiers)}"},
        }

    def claim_event(self, tenant_id: str, event_id: str) -> bool:
        item = self._key(tenant_id, "event", event_id)
        now = int(time.time())
        lease_token = uuid.uuid4().hex
        item.update(
            {
                "status": {"S": "inflight"},
                "lease_until": {"N": str(now + EVENT_LEASE_SECONDS)},
                "lease_token": {"S": lease_token},
                "expires_at": {"N": str(now + self.event_ttl_seconds)},
            }
        )
        try:
            self.client.put_item(TableName=self.table_name, Item=item, ConditionExpression="attribute_not_exists(pk)")
            self._claims[(tenant_id, event_id)] = lease_token
            return True
        except self.client.exceptions.ConditionalCheckFailedException:
            try:
                self.client.update_item(
                    TableName=self.table_name,
                    Key=self._key(tenant_id, "event", event_id),
                    UpdateExpression="SET #status = :inflight, lease_until = :lease_until, lease_token = :lease_token, expires_at = :expires_at",
                    ConditionExpression="#status = :previous_inflight AND lease_until < :now",
                    ExpressionAttributeNames={"#status": "status"},
                    ExpressionAttributeValues={
                        ":inflight": {"S": "inflight"},
                        ":previous_inflight": {"S": "inflight"},
                        ":lease_until": {"N": str(now + EVENT_LEASE_SECONDS)},
                        ":lease_token": {"S": lease_token},
                        ":expires_at": {"N": str(now + self.event_ttl_seconds)},
                        ":now": {"N": str(now)},
                    },
                )
                self._claims[(tenant_id, event_id)] = lease_token
                return True
            except self.client.exceptions.ConditionalCheckFailedException:
                return False

    def complete_event(self, tenant_id: str, event_id: str) -> None:
        lease_token = self._claims.get((tenant_id, event_id))
        if not lease_token:
            raise SlackEventsError("event_lease_missing")
        self.client.update_item(
            TableName=self.table_name,
            Key=self._key(tenant_id, "event", event_id),
            UpdateExpression="SET #status = :completed REMOVE lease_until, lease_token",
            ConditionExpression="#status = :inflight AND lease_token = :lease_token",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":completed": {"S": "completed"}, ":inflight": {"S": "inflight"}, ":lease_token": {"S": lease_token}},
        )
        self._claims.pop((tenant_id, event_id), None)

    def release_event(self, tenant_id: str, event_id: str) -> None:
        lease_token = self._claims.pop((tenant_id, event_id), None)
        if not lease_token:
            return
        try:
            self.client.delete_item(
                TableName=self.table_name,
                Key=self._key(tenant_id, "event", event_id),
                ConditionExpression="#status = :inflight AND lease_token = :lease_token",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":inflight": {"S": "inflight"}, ":lease_token": {"S": lease_token}},
            )
        except self.client.exceptions.ConditionalCheckFailedException:
            return

    def has_thread(self, tenant_id: str, channel_id: str, thread_ts: str) -> bool:
        response = self.client.get_item(
            TableName=self.table_name,
            Key=self._key(tenant_id, "thread", channel_id, thread_ts),
            ConsistentRead=True,
        )
        return "Item" in response

    def register_thread(self, tenant_id: str, channel_id: str, thread_ts: str) -> None:
        self.client.put_item(TableName=self.table_name, Item=self._key(tenant_id, "thread", channel_id, thread_ts))

    def get_active_session(self, tenant_id: str, conversation_id: str) -> str | None:
        response = self.client.get_item(
            TableName=self.table_name,
            Key=self._key(tenant_id, "session", conversation_id),
            ConsistentRead=True,
        )
        value = response.get("Item", {}).get("active_session", {}).get("S")
        return value if isinstance(value, str) and value else None

    def set_active_session(self, tenant_id: str, conversation_id: str, active_session: str) -> None:
        item = self._key(tenant_id, "session", conversation_id)
        item["active_session"] = {"S": active_session}
        self.client.put_item(TableName=self.table_name, Item=item)


class BotoHarnessInvoker(HarnessInvoker):
    def __init__(self, client: Any) -> None:
        self.client = client

    def invoke(self, harness_arn: str, runtime_session_id: str, runtime_user_id: str, text: str) -> str:
        return invoke_harness(self.client, harness_arn, runtime_session_id, runtime_user_id, text)


class UrllibSlackPoster(SlackPoster):
    endpoint = "https://slack.com/api/chat.postMessage"

    def post(self, bot_token: str, channel_id: str, thread_ts: str, text: str) -> None:
        for offset in range(0, len(text) or 1, SLACK_MESSAGE_LIMIT):
            body = json.dumps(
                {
                    "channel": channel_id,
                    "thread_ts": thread_ts,
                    "text": text[offset : offset + SLACK_MESSAGE_LIMIT],
                    "mrkdwn": False,
                    "unfurl_links": False,
                    "unfurl_media": False,
                },
                separators=(",", ":"),
            ).encode("utf-8")
            request = urllib.request.Request(
                self.endpoint,
                data=body,
                method="POST",
                headers={"Authorization": f"Bearer {bot_token}", "Content-Type": "application/json; charset=utf-8"},
            )
            try:
                with urllib.request.urlopen(request, timeout=10) as response:
                    payload = json.loads(response.read())
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                raise RuntimeError("slack_unavailable") from error
            if not isinstance(payload, dict) or payload.get("ok") is not True:
                raise RuntimeError("slack_rejected")


def _harnesses_from_environment() -> dict[str, str]:
    try:
        values = json.loads(os.environ["SLACK_AGENT_HARNESSES"])
    except (KeyError, json.JSONDecodeError) as error:
        raise SlackEventsError("config_invalid") from error
    if not isinstance(values, dict) or not all(isinstance(agent, str) and isinstance(arn, str) and arn for agent, arn in values.items()):
        raise SlackEventsError("config_invalid")
    return values


def _record_envelope(record: Mapping[str, Any]) -> dict[str, Any]:
    body = record.get("body")
    try:
        envelope = json.loads(body)
    except (TypeError, json.JSONDecodeError) as error:
        raise SlackEventsError("queue_invalid") from error
    if not isinstance(envelope, dict):
        raise SlackEventsError("queue_invalid")
    return envelope


def _process_record(
    record: Mapping[str, Any],
    *,
    reader: ParameterReader,
    harnesses: Mapping[str, str],
    prefix: str,
    worker: SlackWorker,
) -> None:
    envelope = _record_envelope(record)
    agent_name = envelope.get("agent")
    if not isinstance(agent_name, str) or agent_name not in harnesses:
        raise SlackEventsError("queue_routing_invalid")
    agent = load_agent(reader, agent_name, prefix)
    if envelope.get("workspace_id") != agent.binding.workspace_id or envelope.get("app_id") != agent.binding.app_id:
        raise SlackEventsError("queue_routing_invalid")
    if not agent.credentials.bot_token:
        raise SlackEventsError("bot_token_missing")
    worker.process(envelope, harness_arn=harnesses[agent_name], bot_token=agent.credentials.bot_token)


def lambda_handler(event: dict[str, Any], context: Any) -> None:
    prefix = os.getenv("SLACK_AGENT_PARAMETER_PREFIX", DEFAULT_PARAMETER_PREFIX)
    request_id = getattr(context, "aws_request_id", "unknown")
    try:
        table_name = os.environ["SLACK_EVENT_STATE_TABLE"]
        reader = SsmParameterReader(_ssm_client())
        worker = SlackWorker(DynamoSlackState(_dynamodb_client(), table_name), BotoHarnessInvoker(_harness_client()), UrllibSlackPoster())
        for record in event.get("Records", []):
            _process_record(
                record,
                reader=reader,
                harnesses=_harnesses_from_environment(),
                prefix=prefix,
                worker=worker,
            )
        return None
    except SlackEventsError as error:
        LOG.warning("slack_events_worker request_id=%s error_class=%s", request_id, error.log_class)
        raise
    except Exception:
        LOG.error("slack_events_worker request_id=%s error_class=internal_error", request_id)
        raise


def _ssm_client() -> Any:
    import boto3

    return boto3.client("ssm")


def _dynamodb_client() -> Any:
    import boto3

    return boto3.client("dynamodb")


def _harness_client() -> Any:
    import boto3

    return boto3.client("bedrock-agentcore")
