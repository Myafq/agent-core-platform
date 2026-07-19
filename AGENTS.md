# Repository instructions for coding agents

This file is the entry point for any agent continuing work in this repository.

## Start here

Read these files before changing code:

1. `docs/status.md` — what currently works, what has been verified, and blockers.
2. `TASKS.md` — ordered work queue and acceptance criteria.
3. `docs/design.md` — architecture, boundaries, and target state.
4. `docs/decisions/` — decisions that should not be silently reversed.
5. `docs/runbook.md` — local validation and deployment commands.

Pick the first `READY` task whose dependencies are complete unless the user asks
for something else. Mark it `IN_PROGRESS` before material work and update its
status and evidence when finished.

## Project objective

Build a versioned YAML abstraction for Amazon Bedrock AgentCore agents. Terragrunt
resolves the YAML and environment context; Terraform owns AWS infrastructure;
small clients and adapters own protocol-specific behavior. The first interface is
a local CLI. The first external integration will be read-only GitHub access using
AgentCore Gateway and user-delegated OAuth.

## Current technical direction

- AgentCore Harness is the default declarative engine.
- AgentCore Runtime is a future escape hatch for custom orchestration.
- YAML describes intent, not arbitrary executable business logic.
- Prompts live in reviewable files referenced by YAML.
- Terragrunt is the composition/compiler layer; Terraform modules receive resolved,
  typed inputs.
- GitHub should use a GitHub App user access token so effective access is the
  intersection of app permissions, installation access, and user permissions.
- No secret values belong in YAML, HCL, Git history, plans, or normal Terraform
  state. Use references and ephemeral/write-only inputs.

## Supported toolchain

- Terraform `~> 1.15.0`; local pin: `1.15.7`
- Terragrunt `~> 1.1`; local pin: `1.1.1`
- AWS provider `~> 6.55`
- AWS CLI v2
- Python 3.11+

Do not add workarounds for the legacy tools that happened to be installed when the
repository was created.

## Safety and scope

- `terraform plan`, schema validation, formatting, and read-only AWS discovery are
  safe when credentials are available.
- Do not run `apply`, `destroy`, modify GitHub App settings, register OAuth callback
  URLs, or create credentials unless the user explicitly authorizes that action.
- Never commit `.terraform/`, `.terragrunt-cache/`, state, credentials, `.env`
  files, generated plans, or Python virtual environments.
- Keep IAM permissions narrow. Temporary wildcards must be documented in
  `docs/status.md` and tracked in `TASKS.md`.
- Preserve unrelated user changes and inspect the worktree before edits.

## Change workflow

1. Update the selected task to `IN_PROGRESS` in `TASKS.md`.
2. Make the smallest coherent change.
3. Run the checks in `docs/runbook.md` that apply.
4. Update documentation when behavior, architecture, assumptions, or blockers
   change.
5. Mark the task `DONE` only with concrete verification evidence. Otherwise mark
   it `BLOCKED` or leave it `IN_PROGRESS` with an explicit next step.
6. Create an ADR in `docs/decisions/` for decisions that constrain future design.

## Definition of done

A task is done when implementation, tests or validation, documentation, and task
tracking agree. A Terraform feature is not deployment-verified merely because its
HCL formats; record `terraform validate`, `plan`, and apply/invocation separately.

