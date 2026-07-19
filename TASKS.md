# Task tracker

Status values: `BACKLOG`, `READY`, `IN_PROGRESS`, `BLOCKED`, `DONE`.

Agents must preserve task IDs, update status in place, and add evidence or a blocker
before ending work. New work receives the next ID in the relevant area.

## Milestone M0 — local Harness vertical slice

| ID | Status | Task | Acceptance criteria / evidence |
|---|---|---|---|
| CORE-001 | DONE | Define the `v1alpha1` YAML contract | Schema, sample spec, external prompt, and validator exist. YAML and JSON syntax were parsed locally. |
| CORE-002 | DONE | Implement Harness Terraform module | Harness, execution role, Bedrock model configuration, outputs, and tool deny-by-default behavior are represented in HCL. Static formatting only; deployment verification is tracked separately. |
| CORE-003 | DONE | Compose the dev unit with Terragrunt | Dev unit decodes YAML and resolves prompt content into module inputs. |
| CLI-001 | DONE | Implement minimal streaming CLI | CLI supports stable local user ID, new sessions, quit, and Harness event-stream text output. Python syntax verified. |
| TOOL-001 | DONE | Upgrade and verify local tools | Checked 2026-07-19: mise provides Terraform 1.15.8; Terragrunt 1.1.1 and AWS CLI 2.36.2 are installed. Terraform satisfies the `~> 1.15.0` constraint. |
| TEST-001 | DONE | Run dependency-backed local validation | Checked 2026-07-19: installed dependencies in `.venv`; spec validation, CLI help, Python compilation, JSON parsing, Terraform formatting, and Terragrunt formatting passed. |
| TF-001 | DONE | Initialize and validate the Harness unit | Checked 2026-07-19: `terragrunt init` selected hashicorp/aws 6.55.0; `terragrunt validate` passed with Terraform 1.15.8. |
| TF-002 | DONE | Produce the first AWS plan | Checked 2026-07-19 with the default profile in us-east-1: 3 creates only—Harness, execution IAM role, and inline model-invocation policy; no replacements or exposed prompt content. |
| AWS-001 | BLOCKED | Deploy and invoke the basic Harness | Bedrock quotas are reported at zero. The execution-policy update is staged locally; re-plan, re-apply, and CLI invocation wait for quota availability. Depends on TF-002. |

## Milestone M1 — hardening the abstraction

| ID | Status | Task | Acceptance criteria / evidence |
|---|---|---|---|
| SPEC-001 | DONE | Add semantic tests for invalid specs | Checked 2026-07-19: six CLI-level tests pass for valid specs, unknown fields, bad ranges, escaping prompt paths, missing prompts, and unsupported engine/provider values. |
| TG-001 | DONE | Add a local Telegram long-polling adapter | Checked 2026-07-19: private-chat parsing, `/start`, `/help`, `/new`, stable identity/session mapping, offset tracking, and 4,096-character reply splitting are implemented; five token-free adapter tests pass. No webhook or cloud deployment. |
| SPEC-002 | BACKLOG | Introduce normalized spec output | Compiler boundary is explicit and modules do not depend directly on raw YAML naming. |
| IAM-001 | IN_PROGRESS | Scope Bedrock invocation resources | Scoping model invocation to the configured foundation-model ARN; documenting unavoidable runtime service actions. Selected model and account/region are now known. |
| STATE-001 | BACKLOG | Design remote-state bootstrap | Document and implement encrypted S3 state and locking for shared environments without creating a circular dependency. |
| CI-001 | BACKLOG | Add local/CI quality entry point | One command runs schema tests, Python checks, Terraform format/validate, and Terragrunt checks. |

## Milestone M2 — read-only GitHub integration

| ID | Status | Task | Acceptance criteria / evidence |
|---|---|---|---|
| GH-001 | BACKLOG | Validate Harness-to-Gateway user identity propagation | A focused spike proves `runtimeUserId` reaches the OAuth binding used by Gateway. Capture exact AWS behavior. |
| GH-002 | BACKLOG | Define the GitHub App permission set | Read-only metadata, contents, and issues permissions are documented; installation and callback steps are explicit. |
| GH-003 | BACKLOG | Add OAuth credential-provider module | Uses current AWS provider resource, authorization-code flow, and ephemeral/write-only credential inputs. No client secret in state or plan. |
| GH-004 | BACKLOG | Add AgentCore Gateway module | Gateway uses IAM inbound auth and exposes only the selected GitHub surface. |
| GH-005 | BACKLOG | Add curated GitHub OpenAPI target | Only current-user, repositories, repository metadata, contents, and read-only issue operations are tools. |
| GH-006 | BACKLOG | Extend YAML schema for tools and outbound identity | Version-compatible schema maps declarative permissions and tool allow-list to the Gateway modules. |
| GH-007 | BACKLOG | Complete CLI OAuth experience | CLI clearly prints authorization URLs, handles pending consent, retries safely, and never prints tokens. |

## Milestone M3 — production-oriented controls

| ID | Status | Task | Acceptance criteria / evidence |
|---|---|---|---|
| OPS-001 | BACKLOG | Add logs, traces, alarms, and retention | Operational signals and retention are declared and documented. |
| MEM-001 | BACKLOG | Add optional AgentCore Memory | YAML actor/session semantics are defined and tested before enabling memory. |
| SAFE-001 | BACKLOG | Design write-action confirmation | Any future GitHub mutation requires explicit confirmation, least privilege, and an audit trail. |
| RUNTIME-001 | BACKLOG | Define the custom Runtime escape hatch | Add only after a concrete Harness limitation is demonstrated. |
