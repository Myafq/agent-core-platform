# Current status

Last updated: 2026-08-03

## Design decision

The target is now:

```text
Telegram or Slack adapter
  -> IAM/SigV4 AgentCore Harness
  -> IAM AgentCore Gateway
  -> Lambda GitHub tool broker
  -> selected-repository GitHub App installation
```

GitHub uses the agent's installation identity for the first release.
User-delegated OAuth is deferred.

## Verified current evidence

- A basic Harness using `moonshotai.kimi-k2.5` with
  `apiFormat: chat_completions` previously reached `READY` and completed a live
  invocation.
- Telegram private-chat long polling, sessions, chunking, and safe diagnostics
  have offline tests.
- A GitHub OAuth provider is deployed and `READY`.
- The Cognito inbound identity stack was applied.
- The IAM Harness/Gateway experiment was destroyed. JWT Harness/Gateway became
  the only deployed experiment path.
- A JWT Telegram invocation reached Harness GitHub MCP initialization.
- Native Harness 3LO then failed because its `GetResourceOauth2Token` request
  omitted `ResourceOauth2ReturnUrl`. Configuring the return URL on both Harness
  and workload identity did not fix it.
- The current callback deployment is behind source and its last live binding
  attempt hit missing DynamoDB `UpdateItem`; these defects no longer block the
  selected machine-identity design.

## Source state

The uncommitted JWT/Cognito/OAuth experiment source was removed on 2026-07-25:
the callback service, JWT compositions, Cognito module, OAuth provider/Gateway
modules, Telegram linking/token path, and stale tests are absent. This did not
destroy deployed resources or mutate remote state. Those remain operator-managed
legacy state until separate, explicitly authorized destroy plans are reviewed.

## Design validation completed

- Official AWS documentation confirms Harness supports declarative Gateway
  tools and `allowedTools`.
- Official AWS documentation confirms Gateway supports Lambda targets using the
  Gateway IAM role.
- GitHub documents installation tokens as the app-owned identity and selected
  installations/permissions as the authorization boundary.
- Slack documents Socket Mode as a pre-authenticated WebSocket with no public
  request URL.
- The installed 6.55.0 provider has already validated current Harness/Gateway
  resources. Provider-backed validation of the proposed Lambda target remains
  an implementation acceptance gate.
- ARCH-002 freezes strict `ChannelMessage`, `getRepository`, `getFile`, and
  bounded read-response schemas. Its fixtures, identity/session derivation,
  and rejection tests passed locally. All 54 unit tests, agent-spec and new
  contract validators, Python compilation, JSON parsing, direct Terraform
  formatting, and `git diff --check` passed. The obsolete OAuth `GET /user`
  contract and validator were removed. Terragrunt remains unavailable after
  the mise SSM environment hook failed before tool startup.
- GHAPP-001 defines the GitHub App operator contract: selected repositories
  only; Contents, Pull requests, and Issues read/write; no organization/account permissions or
  webhooks; numeric App/installation IDs; a pre-existing private-key secret
  ARN; staged key rotation and rollback. No App, installation, secret, or
  cloud configuration was created or changed.
- GHAPP-002 is implemented offline in `services/github_tool`: `listRepositories`
  reads the App installation's current selected repositories with a bounded
  installation-token request; additions/removals need no Lambda or Harness
  update. The two repository-read tools create per-request narrowed installation
  tokens and call fixed GitHub REST endpoints. All responses are normalized and
  errors safely classified. Fake-client tests verify no credential leakage. The
  current Lambda/Gateway deployment is recorded below; App permissions remain
  an external configuration boundary.
- `GATEWAY-001` applied 2026-07-26: Gateway `github-app-tool-nckdlx01xy` has
  five fixed write targets and Lambda `github-app-tool` is `Active` with a
  `Successful` update at 2026-07-26T12:43:30Z. A live Harness request invoked
  the Gateway/Lambda and listed the selected repositories.
- `HARNESS-002` is Harness version 13 and `READY`. Its single `github-read`
  Gateway tool uses AWS IAM and its exact allow-list has the three read and five
  autonomous write operations. Its deployed model is
  `global.anthropic.claude-sonnet-4-6` with `converse_stream` and a scoped
  standard Bedrock streaming policy. A live Harness attempt reached Sonnet but
  failed before Gateway because the model rejects requests that specify both
  `temperature` and `top_p`. The reviewed repair applied: the deployed model
  has `temperature: 0.2` and no `topP`.
- The `global.anthropic.claude-sonnet-4-6` system inference profile is `ACTIVE`.
  A minimal direct Bedrock Converse request succeeded (12 input and 4 output
  tokens). Source now uses its native `converse_stream` format and scopes the
  Harness role to the profile plus its cross-region and `us-east-1` backing
  model ARNs. The reviewed replacement plan then applied in place. The first
  apply stopped before a Harness change because IAM rejected a regionless ARN;
  the corrected policy uses a valid cross-region wildcard ARN.
- `TG-001` is in progress. The Telegram adapter is transport-only: private
  text parsing, bot-derived tenant identity, configured-user allow-list,
  long-polling offsets, an ephemeral typing action while Harness waits, and
  shared IAM Harness invocation are present in source.
  Starting it requires a supplied bot token, one numeric Telegram user ID, and
  explicit authorization for live polling and invocation.
- `WRITE-001` is in progress. The fixed, selected-repository branch, file,
  pull-request, merge, and issue tools are deployed. Each request gets a new
  repository-narrowed installation token with only the required permission.
  The agent does not insert a confirmation turn. Offline validation and a live
  repository-list request passed; App write permissions and live mutation proof
  remain pending.
- `HARNESS-003` is in progress. Source has an ARM64 Amazon Linux coding image
  with Git, GitHub CLI, Python, Make, jq, and Unix tooling. The Harness module
  binds the immutable private-ECR image and enables built-in shell/file tools.
  The home-lab workspace uses AgentCore-managed per-session storage at
  `/mnt/workspace`, not VPC/NAT/EFS; the installed provider requires the
  controlled post-create filesystem update used for `apiFormat`.
- The private ECR repository `github-app-tool-coding` has immutable tags,
  scan-on-push, and 10-image retention. Its ARM64 coding image is published at
  `sha256:455de191c7d1339fb4124c8570cd71b3b4bda14223c2ecd8bbce41dc2c658d3b`
  and is bound in source. The 2026-08-03 Harness init/validate/plan passed;
  the operator then applied its two in-place updates: container environment and
  allow-list plus repository-scoped private-ECR pull permissions. Read-only
  verification found Harness version 15 `READY`, the exact image digest, and
  built-in shell and file-operation tools. Live coding invocation has no
  redacted evidence record.
- The unapplied VPC/NAT/EFS workspace plan and its Harness mock-output
  dependency were removed on 2026-08-03 to avoid idle home-lab network cost.
  Source now requests AgentCore-managed session storage at `/mnt/workspace`
  while retaining public network mode. It adds no EFS IAM permissions, VPC,
  NAT, security groups, or customer-managed filesystem resources. The operator
  applied its reviewed one-update plan; read-only verification found public
  mode and session storage at `/mnt/workspace`. Use the same
  `runtimeSessionId` to resume the workspace. The operator reports the smoke
  appears to work; redacted same-session persistence evidence is not recorded.
- Temporary direct credential source is implemented in source. The Lambda
  package is built locally and the ARM64 credential-helper image is published
  at `github-app-tool-coding@sha256:54450f0aeb93ae43d92f184802fbe12c271e7254eb5c73ae438b62a734b11686`, then pinned in source. The
  existing broker Lambda retains the App private key and mints a fresh
  selected-repository token when the Harness credential helper invokes it with
  its scoped `lambda:InvokeFunction` role permission. The token is not in
  Terraform, Harness configuration, or a persisted file, but is deliberately
  reachable by the root-capable Harness and may be exfiltrated for its one-hour
  lifetime. `terragrunt run --all -- plan` passed and was applied: platform was
  exactly one in-place Lambda code update, with no Gateway/ECR/resource
  replacement; Harness added one post-create environment update and changed
  IAM/Harness configuration in place. Read-only verification found Lambda
  `Active` with `Successful` update status; Harness v17 `READY`, the exact
  credential-helper image digest, only
  `GITHUB_APP_TOKEN_BROKER_FUNCTION_NAME=github-app-tool`, and one scoped
  `lambda:InvokeFunction` permission. Harness dependency mocks shallow-merge
  only new non-secret broker outputs for `validate`/`plan`. No live token mint,
  clone, commit, push, PR, or channel test has run. Exact helper instructions
  for `gh`, clone, and Git network commands are in source. The corrected
  graph-wide plan has no platform changes; it updates Harness in place and
  deletes only the obsolete Terraform bookkeeping object while retaining the
  provider-owned non-secret broker function name. It is not yet applied. Live
  agent diagnostics found no shell region; source now injects the non-secret
  deployment region and helper explicitly selects it, requiring a new image and
  Harness update. Once an operator-set region allowed invocation, the broker
  safely reported `github_auth_failed` at token minting; verify installed App
  write permissions before retrying.
- Kimi's `chat_completions` tool-call protocol incompatibility is historical;
  the active Harness uses Sonnet with `converse_stream`.

## Not verified

- No Slack adapter exists.
- A direct IAM Harness-to-Gateway request listed selected repositories. No
  Telegram/Slack-to-GitHub invocation or live GitHub mutation has succeeded.
- The current Harness plan and apply evidence is recorded above. No new plan
  or apply was run during this status update.
- ARCH-003 provider proof passed 2026-07-24: the minimal `AWS_IAM`
  Gateway/Lambda-target fixture initialized AWS provider 6.55.0 and passed
  `terraform validate`. It uses `GATEWAY_IAM_ROLE`, a Lambda ARN, and an inline
  tool schema. No plan/apply ran.
- CHAN-001 completed offline on 2026-07-25. `clients/channel/core.py` owns
  contract validation, pseudonymous user/session derivation, allow-lists,
  `/new` and help, duplicate suppression, IAM Harness streaming, bounded
  responses, and safe failure text. Telegram now owns only Bot API parsing,
  long-polling acknowledgement, and message delivery. Its Cognito link/token
  and JWT-header invocation code was removed. All 25 remaining unit tests,
  spec/contracts validation, Python compilation, JSON parsing, and
  `git diff --check` passed.
- HARNESS-001 declares a standalone IAM chat-only composition with a
  deny-by-default tool allow-list. GitHub Gateway, OAuth, Token Vault, JWT,
  browser, and code-interpreter code is absent. Authorized network validation
  on 2026-07-25 passed init/validate. The operator applied the reviewed two
  in-place updates; post-apply `get-harness` reported `READY`, version 3, no
  tools/skills, `allowedTools: ["@disabled"]`, and the chat-only prompt. The
  follow-up plan was no-change.
- The active IAM Harness is version 15 and `READY`; it has one IAM GitHub
  Gateway tool and all eight deployed operations. A direct IAM
  Harness-to-Gateway repository-list invocation succeeded.
- The deployed Harness has the custom container, built-in shell/file allow-list,
  and public-mode AgentCore-managed session storage at `/mnt/workspace`; it has
  no VPC or EFS mount.
- No Telegram/Slack-to-GitHub invocation or live mutation has succeeded.
- The installed GitHub App is not yet verified with `Contents: Read and write`,
  `Pull requests: Read and write`, and `Issues: Read and write`; the new write
  tools cannot succeed until that external configuration and deployment exist.
- No cloud, GitHub, Slack, or Telegram settings were changed during this review.

## Blockers

- GitHub App write permissions must be verified or updated outside this
  environment before the deployed mutation tools can succeed.
- Slack app manifest/install values and tokens are not yet supplied.
- The scoped GitHub platform and Harness plans applied. No GitHub App settings
  changed from this environment.
- User-delegated GitHub remains blocked on a fixed and isolated Harness 3LO path
  or an explicit custom Runtime decision.

## Next

Next: build/package, plan, and—only after immediate explicit authorization—apply
the broker and Harness changes. Then run one redacted selected-repository
clone/edit/test/commit/push/PR proof with one `runtimeSessionId`. Replace direct
token delivery with credential-isolated MCP/service work before production use.
