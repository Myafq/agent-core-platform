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

For the local Slack phase, `main` merge authorizes only Slack manifest
create/update and exact Slack SSM writes. Human installation approval remains
required. The HTTPS Events migration is pending image publication, plan/apply,
and Slack manifest reconciliation.

## Layout

```text
agents/       portable agent manifests
clients/      CLI and channel adapters
compositions/ typed Terraform wiring
containers/   image definitions and containerized services
contracts/    executable channel/tool contracts
entrypoints/  runtime-parameterized Terragrunt bindings
modules/      Terraform resource mechanics
live/         shared Terragrunt environment resources
scripts/      build, validation, and provisioning tools
docs/         design, status, and runbook
TASKS.md      dependency-ordered implementation plan
```

Deployables are ARM64 container images, including the broker Lambda.
`docker-bake.hcl` declares every target. `mise run container:push` builds a
clean committed revision, pushes it to ECR, and prints the immutable
`@sha256:` URIs that Terragrunt pins.

## Requirements

- mise
- Terraform 1.15.8
- Terragrunt 1.1.1
- AWS CLI v2
- Docker with Buildx
- jq
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
.venv/bin/python scripts/resolve_agent_targets.py
mise run container:check
mise exec -- terraform fmt -check -recursive modules
mise exec -- terraform fmt -check -recursive compositions
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
