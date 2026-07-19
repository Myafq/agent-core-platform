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
| TOOL-001 | BLOCKED | Upgrade and verify local tools | User is upgrading to Terraform 1.15.7, Terragrunt 1.1.1, and AWS CLI v2. Verify versions after upgrade. |
| TEST-001 | READY | Run dependency-backed local validation | Install dev and CLI dependencies; schema validation and CLI help must pass in `.venv`. Depends on no AWS access. |
| TF-001 | READY | Initialize and validate the Harness unit | `terragrunt init` and `terragrunt validate` succeed with Terraform 1.15.7 and AWS provider 6.55.x. Depends on TOOL-001. |
| TF-002 | READY | Produce the first AWS plan | Plan contains the expected IAM role/policy and Harness only; no unexpected replacement or secret material. Depends on TF-001 and AWS credentials. |
| AWS-001 | BACKLOG | Deploy and invoke the basic Harness | Authorized apply succeeds, CLI streams a response, and identifiers/evidence are recorded without secrets. Depends on TF-002 and explicit user authorization. |

## Milestone M1 — hardening the abstraction

| ID | Status | Task | Acceptance criteria / evidence |
|---|---|---|---|
| SPEC-001 | READY | Add semantic tests for invalid specs | Tests cover unknown fields, bad ranges, escaping prompt paths, missing prompts, and unsupported engine/provider values. |
| SPEC-002 | BACKLOG | Introduce normalized spec output | Compiler boundary is explicit and modules do not depend directly on raw YAML naming. |
| IAM-001 | BACKLOG | Scope Bedrock invocation resources | Replace the execution policy resource wildcard where Bedrock ARN semantics allow it; document any unavoidable wildcard. Depends on the selected model and account/region discovery. |
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

