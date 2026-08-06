# AgentCore YAML lab

A platform for running declarative agents on Amazon Bedrock AgentCore. A
versioned YAML manifest describes an agent; the platform provisions and
operates it. Manifests are the only object-specific surface a human edits.

## The invariant

> One declarative manifest per real-world object; one generic entrypoint per
> kind of object; one state per manifest, addressed by the manifest's own
> identity.

Adding an agent means adding a manifest. It must not add or edit Terraform,
Terragrunt, backend configuration, or any other infrastructure code.

```text
agents/<name>/agent.yaml   declarative intent, the GitOps interface
        |
        v
entrypoints/agents         target selection, backend, providers, translation
        |
        v
compositions/agents        typed resource wiring, no file reads or branching
        |
        v
modules/<resource>         one provider-resource concern, no manifest knowledge
```

Dependencies run one way. Only the entrypoint reads a manifest, derives the
backend key from its identity, configures providers, applies environment
defaults, and translates domain vocabulary into plain typed inputs. Modules
never know a manifest exists.

The target manifest arrives at runtime, so the same invocation serves local,
bulk, and CI runs:

```shell
cd entrypoints/agents
MANIFEST_TARGET=agents/<name>/agent.yaml mise exec -- terragrunt plan
```

Canonical identity is the manifest directory name, and its state lives at
`agents/<name>/terraform.tfstate`. That mapping is total, injective, and
stable, so a rename is a lifecycle operation requiring a reviewed migration —
never an incidental file move.

## Lifecycle rules

- Manifest absence never silently authorizes destroy. Target resolution fails
  on a removed manifest until retirement is explicitly acknowledged, and any
  destroy still needs its own reviewed plan.
- Existing objects are adopted declaratively and idempotently. There is no
  alternate import-only entrypoint for operators.
- CI only maps diffs to targets; it does not own a separate provisioning path.
- Per-target generated data and caches are isolated. One target never reuses
  another's initialized backend or provider artifacts.
- Secrets enter as references. They never appear in a manifest or in state.

## What a manifest owns

```yaml
apiVersion: agentcore.example/v1alpha1
kind: Agent

metadata:
  name: <name>              # must match the directory; it is the identity

spec:
  engine:
    type: harness           # managed agent loop
    container:
      image: <account>.dkr.ecr.<region>.amazonaws.com/<repo>@sha256:<digest>
  model:
    id: <bedrock model or inference profile>
    apiFormat: converse_stream
  instructions:
    system:
      text: |               # the prompt lives in the manifest
        ...
  interfaces:
    slack:
      name: <display name>  # portable channel intent
  tools:
    gateways: [github-app-tool]        # platform tool bindings
    builtins: [shell, file_operations] # deny-by-default allow-list
    codeInterpreter: false
  limits: { maxIterations: 8, maxTokens: 2048, timeoutSeconds: 120 }
```

A manifest is self-contained: intent, prompt, capability allow-lists, and the
pinned image in one versioned file. Image URIs must be digest-pinned, gateway
and built-in tool names come from closed sets, and an unknown name is an error
rather than a silent no-op. Every evaluation runs the manifest through
`scripts/validate_spec.py` before any backend or provider initializes.

The entrypoint derives everything else — repository ARNs, gateway and broker
bindings, backend, provider, tags, and session storage. It is pinned to one
environment and region and rejects an override, so the same agent state can
never be opened under a different provider region or environment tag.
`agents/github-assistant` is the reference manifest.

## Runtime path

```text
Telegram or Slack
  -> trusted adapter
  -> AgentCore Harness
  -> AgentCore Gateway
  -> Lambda tool broker
  -> scoped external identity
```

Harness is the managed agent loop; a custom Runtime is an evidence-driven
escape hatch. An agent gets a shell, file operations, or a code interpreter
only when its manifest asks for them. Adapters are transport-only: contract
validation, pseudonymous identity, allow-lists, and bounded responses live in
the shared channel core.
The platform renders one Slack app manifest per agent from
`spec.interfaces.slack`; workspace and app IDs plus token references stay in
path-scoped, Standard-tier SSM parameters. External identity is the agent's
own installation identity, not a user's OAuth identity.

Merging an agent change to `main` is standing authorization only for Slack
manifest create/update and its exact SSM writes. Human installation approval
is still required, and Terraform apply always needs its own authorization.

## Layout

```text
agents/       portable agent manifests
clients/      CLI and channel adapters
compositions/ typed Terraform wiring
containers/   image definitions and containerized services
contracts/    executable channel/tool contracts
entrypoints/  runtime-parameterized Terragrunt bindings
modules/      Terraform resource mechanics
live/         shared Terragrunt platform resources
schemas/      manifest and contract schemas
scripts/      build, validation, and provisioning tools
docs/         design, status, and runbook
TASKS.md      dependency-ordered implementation plan
```

Deployables are ARM64 container images, including the broker Lambda.
`docker-bake.hcl` declares every target. `mise run container:push` builds a
clean committed revision, pushes it to ECR, and prints the immutable
`@sha256:` URIs that manifests pin.

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
.venv/bin/python scripts/validate_spec.py agents/<name>/agent.yaml
.venv/bin/python scripts/validate_contracts.py
.venv/bin/python scripts/resolve_agent_targets.py
mise run container:check
mise exec -- terraform fmt -check -recursive modules compositions
mise exec -- terragrunt hcl fmt --check
git diff --check
```

`resolve_agent_targets.py` lists every manifest target; `--diff <base> <head>`
maps a change set to the targets to plan.

## Start here

- [Current status](docs/status.md)
- [Implementation plan](TASKS.md)
- [Design and principles](docs/design.md)
- [Runbook](docs/runbook.md)
- [Agent instructions](AGENTS.md)

The prior Cognito/JWT/GitHub OAuth source was removed. Its deployed resources
remain operator-managed legacy state until separately reviewed destroy plans are
explicitly authorized.
