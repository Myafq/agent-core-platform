# AgentCore YAML lab

This repository deploys declarative Amazon Bedrock AgentCore Harness agents with
Terraform and uses Terragrunt to translate an environment-independent YAML agent
specification into Terraform module inputs.

The first vertical slice is intentionally small:

1. `agents/github-assistant/agent.yaml` defines the agent.
2. Terragrunt resolves the YAML and prompt file.
3. Terraform creates the Harness and its least-privilege execution role.
4. `clients/cli/chat.py` invokes the deployed Harness as an interactive terminal chat.

GitHub Gateway and OAuth support will be added after this Harness-only path is
deployed and invoked successfully.

## Project documentation

- [Agent handoff instructions](AGENTS.md)
- [Task tracker](TASKS.md)
- [System design](docs/design.md)
- [Current status](docs/status.md)
- [Development runbook](docs/runbook.md)
- [Architecture decisions](docs/decisions/)

## Prerequisites

- Terraform `~> 1.15.0` (`1.15.8` is pinned for local development)
- Terragrunt `~> 1.1` (`1.1.1` is pinned for local development)
- AWS CLI v2 with a configured profile
- Python 3.11+

The checked-in `.terraform-version` and `.terragrunt-version` select the current
stable release lines. We intentionally do not support legacy Terraform or
Terragrunt behavior in this lab.

## Validate the specification

```shell
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python scripts/validate_spec.py agents/github-assistant/agent.yaml
```

## Plan the development Harness

The first slice uses local Terraform state. Remote state will be introduced as a
separate platform bootstrap step before shared environments are created.

```shell
export AWS_PROFILE=your-profile
export AWS_REGION=us-east-1
cd live/dev/us-east-1/github-assistant
terragrunt plan
terragrunt apply
```

After apply, retrieve `harness_arn` from `terragrunt output`.

## Run the CLI

The AWS principal used by the CLI needs `bedrock-agentcore:InvokeHarness` on the
deployed Harness.

```shell
.venv/bin/pip install -r clients/cli/requirements.txt
.venv/bin/python clients/cli/chat.py \
  --region us-east-1 \
  --harness-arn "$(cd live/dev/us-east-1/github-assistant && terragrunt output -raw harness_arn)"
```

Type `/new` to start a fresh AgentCore session and `/quit` to exit.
