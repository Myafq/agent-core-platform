#!/usr/bin/env python3
"""Minimal interactive client for a Terraform-deployed AgentCore Harness."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import sys
import uuid


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--harness-arn", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--profile", default="default")
    return parser.parse_args()


def new_session_id() -> str:
    return f"cli-{uuid.uuid4().hex}"


def local_user_id() -> str:
    username = getpass.getuser().encode("utf-8")
    digest = hashlib.sha256(username).hexdigest()[:20]
    return f"cli-{digest}"


def stream_response(client, harness_arn: str, session_id: str, user_id: str, text: str) -> None:
    response = client.invoke_harness(
        harnessArn=harness_arn,
        qualifier="DEFAULT",
        runtimeSessionId=session_id,
        runtimeUserId=user_id,
        messages=[{"role": "user", "content": [{"text": text}]}],
    )

    printed_text = False
    for event in response["stream"]:
        delta = event.get("contentBlockDelta", {}).get("delta", {})
        if "text" in delta:
            print(delta["text"], end="", flush=True)
            printed_text = True
        for error_name in ("runtimeClientError", "internalServerException", "validationException"):
            if error_name in event:
                raise RuntimeError(f"{error_name}: {event[error_name]}")
    if printed_text:
        print()


def main() -> int:
    args = parse_args()
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ModuleNotFoundError as error:
        print(
            f"Missing CLI dependency {error.name!r}. "
            "Install clients/cli/requirements.txt in a virtual environment.",
            file=sys.stderr,
        )
        return 2

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    client = session.client("bedrock-agentcore")
    session_id = new_session_id()
    user_id = local_user_id()

    print(f"AgentCore CLI session: {session_id}")
    print("Commands: /new, /quit")

    while True:
        try:
            prompt = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not prompt:
            continue
        if prompt == "/quit":
            return 0
        if prompt == "/new":
            session_id = new_session_id()
            print(f"Started session: {session_id}")
            continue

        print("Agent: ", end="", flush=True)
        try:
            stream_response(client, args.harness_arn, session_id, user_id, prompt)
        except (BotoCoreError, ClientError, RuntimeError) as error:
            print(f"\nInvocation failed: {error}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
