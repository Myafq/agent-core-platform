# AgentCore YAML lab

Versioned YAML for declarative AgentCore Harness agents.

Target path:

```text
Telegram or Slack
  -> trusted adapter
  -> AgentCore Harness
  -> AgentCore Gateway
  -> Lambda GitHub tool broker
  -> selected-repository GitHub App installation
```

Harness remains the managed agent loop. GitHub initially uses the agent's
installation identity, not a user's OAuth identity.

Portable interface intent belongs in the agent spec:

```yaml
spec:
  interfaces:
    slack:
      name: GitHub Assistant
```

The platform renders one Slack manifest per agent. Workspace/App IDs and secret
token references remain environment configuration; every workspace user may
start a thread by DM or by mentioning an invited bot.

Slack provisioning and per-agent credentials use path-scoped, Standard-tier SSM
parameters; secret values never enter agent YAML or Terraform state.

For the local `SLACK-002` phase, `main` merge authorizes only Slack manifest
create/update and exact Slack SSM writes. Human installation approval and one
per-app Socket Mode `connections:write` token remain required; each macOS
adapter is launched manually. Shared HTTPS Events ingress is deferred to
`SLACK-003`.

## Layout

```text
agents/       portable agent specs and prompts
clients/      CLI and channel adapters
contracts/    executable channel/tool contracts
modules/      Terraform resource mechanics
live/         Terragrunt environment composition
docs/         design, status, and runbook
TASKS.md      dependency-ordered implementation plan
```

## Requirements

- mise
- Terraform 1.15.8
- Terragrunt 1.1.1
- AWS CLI v2
- Python 3.11+

## Bootstrap

```shell
scripts/bootstrap_mise_plugins.sh
mise exec -- terraform version
mise exec -- terragrunt --version
mise exec -- aws --version
python3 --version
```

The mise plugin loads referenced SSM values only for child commands. Never run
`mise env`; it prints loaded values.

## Validate

```shell
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pip install -r clients/cli/requirements.txt
.venv/bin/python -m unittest discover -s tests
.venv/bin/python scripts/validate_spec.py agents/github-assistant/agent.yaml
.venv/bin/python scripts/validate_contracts.py
mise exec -- terraform fmt -check -recursive modules
mise exec -- terragrunt hcl fmt --check
git diff --check
```

## Start here

- [Current status](docs/status.md)
- [Implementation plan](TASKS.md)
- [Design and principles](docs/design.md)
- [Runbook](docs/runbook.md)
- [Agent instructions](AGENTS.md)

The prior Cognito/JWT/GitHub OAuth source was removed. Its deployed resources
remain operator-managed legacy state until separately reviewed destroy plans are
explicitly authorized.
