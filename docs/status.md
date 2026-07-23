# Current status

Last updated: 2026-07-22

## Deployed

- `github-assistant` Harness: `READY`.
- Model: `moonshotai.kimi-k2.5`, Mantle `chat_completions`; live Harness
  invocation previously succeeded.
- AgentCore OAuth provider `github-assistant-oauth`: `READY`.
- Generated OAuth callback registered in the development GitHub OAuth App.
- Encrypted, versioned S3 state with S3-native locking:
  - OAuth: `dev/us-east-1/platform/github-oauth/terraform.tfstate`
  - Agent: `dev/us-east-1/agents/github-assistant/terraform.tfstate`
  - Gateway: `dev/us-east-1/platform/github-gateway/terraform.tfstate`
  - Legacy combined key: empty; older S3 versions retained for rollback.

## Implemented but not deployed

- Shared MCP/IAM Gateway and one `GET /user` OpenAPI target.
- Harness `github` Gateway tool with only
  `@github/getAuthenticatedUser`.
- CLI OAuth event parser and safe consent UX. Live AgentCore event shape remains
  unknown.
- Local Telegram long-polling adapter. Telegram forwarding and OAuth UX are not
  live-verified.

## Latest verification

- State split completed with no AWS resource changes:
  - OAuth state: 1 resource, 2 non-secret outputs.
  - Agent state: 9 resource/data addresses, 3 non-secret outputs.
  - Legacy state: 0 resources, 0 outputs.
  - OAuth and agent refresh-only applies: `0 added, 0 changed, 0 destroyed`.
  - Final OAuth plan: `No changes`.
- OAuth provider and Harness confirmed `READY` after migration.
- Gateway initialized with
  `https://t.me/gh_agent_517_bot?start=github-consent`.
- Gateway plan succeeded: 4 creates only (Gateway, one `GET /user` target,
  scoped role, and scoped policy), with no changes or destroys. A full
  `terragrunt run --all -- plan` also succeeded: OAuth has no changes; the
  Gateway has 4 creates; the existing Harness has 3 in-place changes to attach
  the planned tool and IAM. The unapplied Gateway has shape-valid mock outputs
  for agent `validate`/`plan` only; `apply` cannot use them.
- Current source checks: 44 tests, GitHub contract validation, Terraform and
  Terragrunt formatting, and `git diff --check` passed.

Rollback evidence is retained in S3 version history. Exact version IDs and
resource-level task evidence remain in Git history; they are not operational
inputs.

## Blockers

- IAM/SigV4 Harness invocation does not propagate a verified end-user identity to
  Token Vault. GH-010/GH-001 require a supported Bearer JWT inbound path.
- GitHub OAuth App `repo` scope is unacceptable for read-only private source.
- The local Terraform principal needs the AgentCore control-plane permission used
  by the Harness model-format update when that configuration changes.
- GitHub requires `User-Agent`; confirm AgentCore supplies one during the live
  Gateway test before changing the frozen OpenAPI contract.

## Next

Retry GH-005 Gateway validation and produce a reviewed read-only plan. Do not
apply Gateway or Harness tool changes until the JWT identity dependency and
explicit apply authorization are satisfied. `TASKS.md` is authoritative for
acceptance criteria.
