# Repository instructions for coding agents

## Start here

Read, in order:

1. `docs/status.md` — current deployment, verification, blockers, next step.
2. `TASKS.md` — authoritative work queue and acceptance evidence.
3. `docs/design.md` — architecture, ownership, and design principles.
4. `docs/runbook.md` — current commands and safety gates.

User-requested work overrides queue order. Otherwise select the first `READY`
task with complete dependencies. Mark it `IN_PROGRESS` before material work.

## Objective

Build a versioned YAML abstraction for AgentCore agents. YAML owns intent,
Terragrunt composition, Terraform AWS resources, and clients protocol behavior.
Harness is the default engine; custom Runtime is an evidence-driven escape hatch.

## Toolchain

- Terraform `~> 1.15.0`; local pin `1.15.8`
- Terragrunt `~> 1.1`; local pin `1.1.1`
- AWS provider `~> 6.55`
- AWS CLI v2
- Python 3.11+

Use current supported tools. Do not add compatibility for obsolete local
installations.

## Safety

- Formatting, validation, plans, and read-only AWS discovery are safe.
- Require explicit authorization for apply, destroy, state mutation, credential
  creation, GitHub settings, or callback changes.
- Never commit state, plans, credentials, `.env`, caches, or virtual environments.
- Secrets enter through references, ephemeral variables, and write-only fields.
- Preserve unrelated changes.
- Keep IAM and exposed tool operations narrowly scoped.
- Static validation, plan, apply, readiness, and successful invocation are
  separate claims. Record only what was verified.

## Workflow

1. Update the selected `TASKS.md` row.
2. Make the smallest coherent change consistent with `docs/design.md`.
3. Run applicable `docs/runbook.md` checks.
4. Update current status, task evidence, and design principles when behavior or
   constraints change.
5. Mark `DONE` only when implementation, validation, documentation, and task
   evidence agree. Otherwise leave `IN_PROGRESS` or record a real blocker.

Do not create separate decision documents. Durable decisions belong in the
principles and ownership sections of `docs/design.md`.
