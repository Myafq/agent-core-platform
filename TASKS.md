# Implementation plan

Status values: `BACKLOG`, `READY`, `IN_PROGRESS`, `BLOCKED`, `DONE`.

This plan replaces the previous task history. Git history preserves completed
work and failed experiments. Select the first `READY` task with complete
dependencies. Mark it `IN_PROGRESS` before material work.

## Phase 0 — freeze the replacement contract

| ID | Status | Depends on | Task | Acceptance evidence |
|---|---|---|---|---|
| ARCH-001 | DONE | — | Review and reset the design | `docs/design.md`, `docs/status.md`, `docs/runbook.md`, README, and this plan agree on Harness + trusted adapters + IAM Gateway/Lambda + GitHub App installation identity. Official AWS, GitHub, Slack, and Telegram documentation reviewed 2026-07-24. All 55 unit tests, spec/contract validators, compilation, JSON parsing, direct formatting checks, and `git diff --check` passed. No external mutation. |
| ARCH-002 | DONE | ARCH-001 | Freeze channel and GitHub tool contracts | Added strict schemas and checked-in fixtures for `ChannelMessage`, paginated `listRepositories`, `getRepository`, `getFile`, and bounded read responses. `listRepositories` reads the current GitHub App installation scope; additions/removals need no Lambda or Harness update. Deterministic pseudonymous user/session IDs and rejection/partitioning tests passed with `scripts/validate_contracts.py`; removed the superseded OAuth `GET /user` contract and validator. |
| ARCH-003 | DONE | ARCH-001 | Prove provider 6.55 Lambda-target support | Added `tests/fixtures/terraform-lambda-target`: an `AWS_IAM` Gateway with `GATEWAY_IAM_ROLE`, Lambda target, and inline tool schema. With authorized network access, Terraform 1.15.8 initialized AWS provider 6.55.0 and `terraform validate` passed. No plan/apply. |

## Phase 1 — channel core and chat-only Harness

| ID | Status | Depends on | Task | Acceptance evidence |
|---|---|---|---|---|
| CHAN-001 | DONE | ARCH-002 | Extract a channel-neutral Harness client | Added `clients/channel/core.py`; Telegram is now transport-only and uses IAM Harness invocation. The Cognito link/token and JWT-header path was deleted from active clients. Offline tests cover stable pseudonymous identity, `/new`, duplicate messages, stream errors without provider details, allow-lists, empty replies, and chunking. Full 45-test suite, spec/contracts validation, Python compilation, JSON parsing, and `git diff --check` passed. |
| HARNESS-001 | DONE | ARCH-003, CHAN-001 | Define a clean IAM chat-only Harness composition | Chat-only prompt and deny-by-default tool allow-list are declared; no GitHub/OAuth/Token Vault permissions or tools exist in source. Authorized network run on 2026-07-25 passed init/validate; reviewed plan had two in-place updates and was applied by the operator. Post-apply `get-harness` found `READY`, version 3, no tools/skills, `allowedTools: ["@disabled"]`, and the chat-only prompt; follow-up plan was no-change. |
| TG-001 | IN_PROGRESS | CHAN-001, HARNESS-001 | Reconnect Telegram to the shared chat path | Private-chat allow-list, bot-derived identity, long polling, safe typing action refresh while the Harness waits, and IAM invocation are covered offline. Operator handoff uses one bot token, one numeric Telegram user ID, and the deployed Harness ARN. Live `/new` plus reply requires explicit invocation authorization and is recorded separately. |
| SLACK-001 | DONE | CHAN-001, HARNESS-001 | Add Slack Socket Mode adapter | `spec.interfaces.slack.name` renders one app per agent. Every workspace user may start a session by DM or by mentioning an invited bot. Every root starts a Slack thread and one Harness session. Public/private channel follow-ups are accepted only for registered mention roots, which persist as hashes without content or user IDs. Replies are threaded, bounded, plain text, and unfurled links are disabled. All 56 unit tests, agent-spec and contract validation, manifest rendering, compilation, JSON parsing, formatting, and `git diff --check` passed. No Slack/AWS mutation or live invocation. |
| SLACK-002 | IN_PROGRESS | SLACK-001 | Reconcile and operate Slack from agent intent | Source now has an idempotent `plan`/explicit-`apply` reconciler, exact-App-ID adoption, OAuth/app-token completion, Standard-tier SSM adapters, fake-client tests, and a manual selected-agent macOS launcher. The launcher reads merged `main`, verifies the bound manifest and immutable `metadata.name`, decrypts only its agent credentials, and replaces itself with the Socket Mode adapter. No implementation validation, Slack/AWS mutation, installation, connection, or live invocation has run. User validation and bootstrap/live evidence remain required. |
| SLACK-003 | BACKLOG | SLACK-002 | Remove the per-app Socket Mode token step | Add one shared HTTPS Events ingress. Keep separate Slack App/bot identities, verify each app's signing secret, route by App ID to one Harness, and retain Slack install approval. Merge-driven creation uses the manifest API response and no app-level Socket Mode token. |
| CHAT-001 | BACKLOG | TG-001, SLACK-001 | Prove both chat transports | After explicit authorization, one allowed Telegram user and one ordinary user in the bound Slack workspace each start a new session and receive a Harness response. Slack proof covers one DM thread and one mention-started channel thread. Record redacted UTC/request IDs. No GitHub tool attached yet. |

## Phase 2 — agent-owned GitHub read tools

| ID | Status | Depends on | Task | Acceptance evidence |
|---|---|---|---|---|
| GHAPP-001 | DONE | ARCH-002 | Define GitHub App operator contract | `docs/design.md` and `docs/runbook.md` define selected repositories; Contents, Pull requests, and Issues read/write; no organization/account permissions or webhooks; numeric App/installation IDs; a pre-existing private-key secret ARN; staged rotation; and rollback. No App/settings/secret/cloud change. |
| GHAPP-002 | DONE | ARCH-002, ARCH-003, GHAPP-001 | Implement GitHub tool broker | Added `services/github_tool`: Lambda entrypoint plus broker validation, live paginated installation-repository listing, per-request repository-scoped installation tokens for reads, fixed REST endpoints/API version/User-Agent, bounded normalized responses, and classified errors without credentials. Fake-client tests cover read scoping and no credential leakage. No Lambda, secret, GitHub App, or cloud resource exists yet. |
| GATEWAY-001 | DONE | ARCH-003, GHAPP-002 | Implement IAM Gateway and Lambda target | Applied 2026-07-26: five fixed write targets plus the updated Lambda broker. Lambda is `Active` and last update `Successful`. A live Harness request reached Gateway/Lambda and listed the selected repositories. |
| HARNESS-002 | DONE | HARNESS-001, GATEWAY-001 | Attach exact GitHub tools to Harness | Applied 2026-07-26: Harness v13 is `READY`; its exact allow-list contains three read and five write GitHub operations. A live Harness request successfully listed the selected repositories. |
| HARNESS-003 | DONE | HARNESS-002 | Add the native coding workspace | Harness v20 is `READY` with public-mode session storage at `/mnt/workspace`, the scoped broker invocation permission, and immutable ARM64 image `github-app-tool-coding@sha256:ecb32df1a3814a799dc9bfe98d9439341041492b693a7183b62d94da5a0d130a`. The helper has overridable non-secret defaults and needs no Harness environment variables. A fresh session with all overrides unset minted and discarded one `Myafq/dineza` token successfully. The earlier one-session native proof cloned, tested, committed, pushed, and opened PR #1. Temporary risk remains: the root-capable Harness can retrieve/exfiltrate the one-hour token; replace it with a credential-isolated service before production use. |
| GHAPP-003 | DONE | GHAPP-001, GATEWAY-001, HARNESS-002 | Create/install App and deploy GitHub slice | Operator verified/accepted Contents, Pull requests, and Issues `Read and write`. On 2026-08-04 a repository-narrowed token successfully cloned, pushed commit `2d8fb68f363dedd6cb55d3d4ca7b35558f65d4aa`, and opened `Myafq/dineza` PR #1. This proves the selected-repository App permission and mutation boundary; no token value was emitted. |
| E2E-001 | BLOCKED | CHAT-001, GHAPP-003 | Prove channel-to-GitHub read path | Telegram and Slack each retrieve one allowed repository/file through Harness. Disallowed repo, unsafe path/ref, unknown tool, mutation prompt, and oversized response fail safely. Record redacted evidence; no token or private content in logs. |

## Phase 3 — hardening and cleanup

| ID | Status | Depends on | Task | Acceptance evidence |
|---|---|---|---|---|
| CI-001 | BACKLOG | ARCH-002 | Add one quality command | One command runs contracts, unit tests, Python compilation, Terraform format/validate, Terragrunt format, secret/stale-reference scans, and `git diff --check`. |
| OPS-001 | BACKLOG | E2E-001 | Add production controls | Retention, metrics, alarms, tracing, rate/concurrency limits, retry budgets, GitHub rate-limit behavior, and safe audit fields are declared and tested. |
| CLEAN-001 | BLOCKED | E2E-001 | Retire failed OAuth/JWT/Cognito experiment | Inventory deployed resources/state; produce per-unit destroy plans and source-removal diff. Requires explicit destroy authorization. Preserve versioned state history and remove no shared resource accidentally. |
| DELEGATE-001 | BLOCKED | E2E-001 | Re-evaluate user-delegated GitHub | Start only with a fixed Harness 3LO release or explicit custom Runtime approval. Use GitHub App user tokens, not OAuth App `repo`; require two-user isolation, revocation, and no model-supplied identity. |
| WRITE-001 | DONE | HARNESS-003 | Add autonomous GitHub mutations | The 2026-08-04 native proof succeeded in one Harness session: clone, six-test change, Node 24 validation (5 files/85 tests), commit `2d8fb68f363dedd6cb55d3d4ca7b35558f65d4aa`, push, and open `Myafq/dineza` PR #1. Harness v20 then minted a fresh repository-scoped token with every override variable unset. The private key remains Lambda-only; no token value was logged or persisted. The accepted temporary root-token risk must be replaced before production use. Gateway retirement remains separately gated. |

## Stop conditions

- No apply, destroy, state mutation, secret creation, GitHub/Slack settings
  change, OAuth consent, or live channel invocation without explicit approval.
- Do not implement user delegation inside a Lambda target by trusting tool
  arguments for user identity.
- Do not broaden GitHub permissions to OAuth `repo`, all repositories, or any
  write permission.
- Stop after one provider/network validation failure when the failure is
  environmental; preserve the exact operator command.
