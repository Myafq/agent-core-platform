# Implementation plan

Status values: `BACKLOG`, `READY`, `IN_PROGRESS`, `BLOCKED`, `DONE`.

This plan replaces the previous task history. Git history preserves completed
work and failed experiments. Select the first `READY` task with complete
dependencies. Mark it `IN_PROGRESS` before material work.

## Phase 0 — freeze the replacement contract

| ID | Status | Depends on | Task | Acceptance evidence |
|---|---|---|---|---|
| ARCH-001 | DONE | — | Review and reset the design | `docs/design.md`, `docs/status.md`, `docs/runbook.md`, README, and this plan agree on Harness + trusted adapters + IAM Gateway/Lambda + GitHub App installation identity. Official AWS, GitHub, Slack, and Telegram documentation reviewed 2026-07-24. All 55 unit tests, spec/contract validators, compilation, JSON parsing, direct formatting checks, and `git diff --check` passed. No external mutation. |
| ARCH-002 | DONE | ARCH-001 | Freeze channel and GitHub tool contracts | Added strict schemas and checked-in fixtures for `ChannelMessage`, `getRepository`, `getFile`, and bounded read responses. Deterministic pseudonymous user/session IDs and six rejection/partitioning tests passed with `scripts/validate_contracts.py`; removed the superseded OAuth `GET /user` contract and validator. |
| ARCH-003 | DONE | ARCH-001 | Prove provider 6.55 Lambda-target support | Added `tests/fixtures/terraform-lambda-target`: an `AWS_IAM` Gateway with `GATEWAY_IAM_ROLE`, Lambda target, and inline tool schema. With authorized network access, Terraform 1.15.8 initialized AWS provider 6.55.0 and `terraform validate` passed. No plan/apply. |

## Phase 1 — channel core and chat-only Harness

| ID | Status | Depends on | Task | Acceptance evidence |
|---|---|---|---|---|
| CHAN-001 | DONE | ARCH-002 | Extract a channel-neutral Harness client | Added `clients/channel/core.py`; Telegram is now transport-only and uses IAM Harness invocation. The Cognito link/token and JWT-header path was deleted from active clients. Offline tests cover stable pseudonymous identity, `/new`, duplicate messages, stream errors without provider details, allow-lists, empty replies, and chunking. Full 45-test suite, spec/contracts validation, Python compilation, JSON parsing, and `git diff --check` passed. |
| HARNESS-001 | IN_PROGRESS | ARCH-003, CHAN-001 | Define a clean IAM chat-only Harness composition | New composition has model, prompt, limits, memory/session permissions, and no GitHub/OAuth/Token Vault permissions or tools. Validate and produce a reviewed create-only plan. Apply remains separately authorized. |
| TG-001 | BACKLOG | CHAN-001, HARNESS-001 | Reconnect Telegram to the shared chat path | Private-chat allow-list, bot-derived identity, long polling, and IAM invocation are covered offline. Live `/new` plus reply requires explicit invocation authorization and is recorded separately. |
| SLACK-001 | BACKLOG | CHAN-001, HARNESS-001 | Add Slack Socket Mode adapter | Manifest template uses minimal granular scopes. Direct messages only; workspace/user allow-list; bot/app tokens are environment references. Tests cover acknowledgement, retries, duplicate events, threads, bot-message loops, chunking, sanitization, and `/new`. |
| CHAT-001 | BACKLOG | TG-001, SLACK-001 | Prove both chat transports | After explicit authorization, one Telegram user and one allowed Slack user each start a new session and receive a Harness response. Record redacted UTC/request IDs. No GitHub tool attached yet. |

## Phase 2 — agent-owned GitHub read tools

| ID | Status | Depends on | Task | Acceptance evidence |
|---|---|---|---|---|
| GHAPP-001 | BACKLOG | ARCH-002 | Define GitHub App operator contract | Document exact App permissions (`Contents: read`, metadata only), selected-repository installation, App/installation IDs, private-key rotation, pre-existing secret ARN, and rollback. No App/settings/secret creation. |
| GHAPP-002 | BACKLOG | ARCH-002, ARCH-003, GHAPP-001 | Implement GitHub tool broker | Lambda validates tool/input/repository allow-list, creates short-lived installation tokens, calls fixed versioned GitHub endpoints with `User-Agent`, bounds output, and sanitizes errors/logs. Unit tests use HTTP/secret clients as fakes and verify no credential leakage. |
| GATEWAY-001 | BACKLOG | ARCH-003, GHAPP-002 | Implement IAM Gateway and Lambda target | Separate module/composition owns one Gateway, scoped role, Lambda target/schema, Lambda permission, logs, and outputs. Provider-backed validation passes. Reviewed plan contains only expected creates and no secret values. |
| HARNESS-002 | BACKLOG | HARNESS-001, GATEWAY-001 | Attach exact GitHub tools to Harness | Harness role can invoke one Gateway; `allowedTools` contains only `getRepository` and `getFile`; native OAuth and Token Vault permissions are absent. Offline tests, validation, and reviewed plan pass. |
| GHAPP-003 | BLOCKED | GHAPP-001, GATEWAY-001, HARNESS-002 | Create/install App and deploy GitHub slice | Needs explicit authorization for GitHub settings, secret creation, Terraform apply, and live invocation. Verify selected repositories and read-only permissions before apply. |
| E2E-001 | BLOCKED | CHAT-001, GHAPP-003 | Prove channel-to-GitHub read path | Telegram and Slack each retrieve one allowed repository/file through Harness. Disallowed repo, unsafe path/ref, unknown tool, mutation prompt, and oversized response fail safely. Record redacted evidence; no token or private content in logs. |

## Phase 3 — hardening and cleanup

| ID | Status | Depends on | Task | Acceptance evidence |
|---|---|---|---|---|
| CI-001 | BACKLOG | ARCH-002 | Add one quality command | One command runs contracts, unit tests, Python compilation, Terraform format/validate, Terragrunt format, secret/stale-reference scans, and `git diff --check`. |
| OPS-001 | BACKLOG | E2E-001 | Add production controls | Retention, metrics, alarms, tracing, rate/concurrency limits, retry budgets, GitHub rate-limit behavior, and safe audit fields are declared and tested. |
| CLEAN-001 | BLOCKED | E2E-001 | Retire failed OAuth/JWT/Cognito experiment | Inventory deployed resources/state; produce per-unit destroy plans and source-removal diff. Requires explicit destroy authorization. Preserve versioned state history and remove no shared resource accidentally. |
| DELEGATE-001 | BLOCKED | E2E-001 | Re-evaluate user-delegated GitHub | Start only with a fixed Harness 3LO release or explicit custom Runtime approval. Use GitHub App user tokens, not OAuth App `repo`; require two-user isolation, revocation, and no model-supplied identity. |
| WRITE-001 | BLOCKED | OPS-001, DELEGATE-001 | Design GitHub mutations | Separate tools, least privilege, exact confirmation, idempotency, branch/PR-only initial scope, and immutable audit evidence. No default-branch writes. |

## Stop conditions

- No apply, destroy, state mutation, secret creation, GitHub/Slack settings
  change, OAuth consent, or live channel invocation without explicit approval.
- Do not implement user delegation inside a Lambda target by trusting tool
  arguments for user identity.
- Do not broaden GitHub permissions to OAuth `repo`, all repositories, or any
  write permission.
- Stop after one provider/network validation failure when the failure is
  environmental; preserve the exact operator command.
