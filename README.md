# AgentCore YAML lab

Versioned YAML for Amazon Bedrock AgentCore agents. Terragrunt resolves agent
intent and environment context; Terraform owns AWS resources; clients own
protocol behavior.

## Layout

```text
agents/                         agent specs and prompts
contracts/github/               executable GitHub API and wiring contracts
modules/                        reusable Terraform resource mechanics
live/dev/us-east-1/platform/    shared OAuth and Gateway stacks
live/dev/us-east-1/agents/      per-agent Harness stacks
clients/                        CLI and Telegram adapters
```

Shared dependencies flow one way:

```text
platform/github-oauth -> platform/github-gateway -> agents/github-assistant
```

## Bootstrap

Requirements: mise, Terraform 1.15.8, Terragrunt 1.1.1, AWS CLI v2, and
Python 3.11+.

```shell
scripts/bootstrap_mise_plugins.sh
mise exec -- terraform version
mise exec -- terragrunt --version
mise exec -- aws --version
python3 --version
```

The mise plugin loads GitHub OAuth credentials from SSM only for the child
command. Never run `mise env`; it prints environment values.

## Validate

```shell
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pip install -r clients/cli/requirements.txt
.venv/bin/python -m unittest discover -s tests
.venv/bin/python scripts/validate_github_contract.py
mise exec -- terraform fmt -check -recursive modules
mise exec -- terragrunt hcl fmt --check
git diff --check
```

## Current deployment

The GitHub OAuth provider and `github-assistant` Harness are deployed and
`READY`. Their states are separated. Gateway, Gateway target, and Harness
Gateway-tool changes are staged but not deployed. Per-user OAuth testing remains
blocked on JWT-backed inbound identity.

See:

- [Current status](docs/status.md)
- [Design and principles](docs/design.md)
- [Runbook](docs/runbook.md)
- [Task tracker](TASKS.md)
- [Agent instructions](AGENTS.md)
