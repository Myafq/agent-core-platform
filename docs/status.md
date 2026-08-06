# Current status

Last updated: 2026-08-05

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
- GHAPP-002 is implemented offline in `containers/github-tool/service/github_tool`: `listRepositories`
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
  at `github-app-tool-coding@sha256:54450f0aeb93ae43d92f184802fbe12c271e7254eb5c73ae438b62a734b11686`, then pinned in source as `container_uri`; no
  new image build is pending. The existing broker Lambda retains the App
  private key and mints a fresh selected-repository token when the Harness
  credential helper invokes it with its scoped `lambda:InvokeFunction` role
  permission. The token is not in Terraform, Harness configuration, or a
  persisted file, but is deliberately reachable by the root-capable Harness and
  may be exfiltrated for its one-hour lifetime. A prior `terragrunt run --all
  -- plan`/apply cycle was exactly one platform in-place Lambda code update,
  with no Gateway/ECR/resource replacement, plus one Harness post-create
  environment update and in-place IAM/Harness configuration change. Read-only
  verification found Lambda `Active` with `Successful` update status; Harness
  v17 `READY`, the exact credential-helper image digest, only
  `GITHUB_APP_TOKEN_BROKER_FUNCTION_NAME=github-app-tool`, and one scoped
  `lambda:InvokeFunction` permission. Harness dependency mocks shallow-merge
  only new non-secret broker outputs for `validate`/`plan`. No live token mint,
  clone, commit, push, PR, or channel test has run through the deployed path.
  Exact helper instructions for `gh`, clone, and Git network commands are in
  source. Harness v19 then proved control-plane environment variables were not
  present in fresh runtime shells; AgentCore also rejected `AWS_REGION` as a
  reserved key before mutation. The approved repair puts overridable,
  non-secret `us-east-1` and `github-app-tool` defaults in the helper, clears
  the ineffective Harness environment map, and pins image
  `github-app-tool-coding@sha256:ecb32df1a3814a799dc9bfe98d9439341041492b693a7183b62d94da5a0d130a`.
  The Harness-only plan/apply was 0 added, 1 changed, 0 destroyed. Harness v20
  reached `READY` with zero configured environment variables. In a brand-new
  session, with all three override variables explicitly unset, the helper
  minted a `Myafq/dineza` repository-scoped token successfully and discarded
  its value; the diagnostic session was then stopped.
- `WRITE-001` live native proof succeeded on 2026-08-04 in one Harness session
  after injecting only the two non-secret region/broker values into that
  session. Against selected repository `Myafq/dineza`, the agent cloned with
  the credential helper, added six missing `formatHour` tests, ran the Node 24
  suite successfully (5 files, 85 tests), committed
  `2d8fb68f363dedd6cb55d3d4ca7b35558f65d4aa`, pushed branch
  `codex/write-001-native-proof-20260804`, and opened PR #1. Read-only follow-up
  found the PR open against `main` and the workspace clean. No token value was
  emitted or persisted. This proves the App permissions, broker, native
  Git/gh path, push, and PR creation. The later v20 fresh-session check proves
  zero-touch helper initialization.
- Kimi's `chat_completions` tool-call protocol incompatibility is historical;
  the active Harness uses Sonnet with `converse_stream`.

## Not verified

- Historical `SLACK-001` Socket Mode proof passed. `spec.interfaces.slack.name` declared one
  Slack App and bot identity per agent. Every workspace user may start a session
  by DM or by mentioning an invited bot. Every root produces a Slack thread and
  one Harness session. Public/private channel follow-ups are accepted only for
  registered mention roots; roots persist locally as hashes with no content or
  user IDs. The manifest contains the required mention, channel-history,
  private-channel-history, DM-history, and write scopes. The adapter checks the
  workspace and provisioned Slack App ID, acknowledges before Harness work,
  deduplicates retries, rejects bot loops/unregistered threads, and sends
  bounded plain-text threaded replies with unfurls disabled. On 2026-08-04 the
  operator confirmed both DM sessions and mention-started channel threads,
  including threaded follow-ups, work as expected through the live Harness.
- Historical `SLACK-002` is deployed and was user-validated for one macOS host and workspace
  `T0BKR092ATB`. Reconciliation updated exact App `A0BMSFX33T5`; signed OAuth
  installed bot `U0BMVTXSYH1`; the per-app `connections:write` token was stored
  in the agent's `SecureString`; and historical read-only verification found
  binding state `socket_mode_ready`. The operator confirmed DM and
  channel-thread behavior on that old path. No credential value was read or recorded.
- `SLACK-003` now replaces Socket Mode with signed per-agent HTTPS
  Events routes on the existing API Gateway, FIFO SQS dispatch, a separate
  worker Lambda, and hashed DynamoDB event/thread/session state. The old bot,
  launcher, app-token CLI, and tests are removed. The deployed ARM64 image is
  `sha256:f0dacf3770524d466daa480358165cb72d6a8dfaca780a846462f945305a56ee`.
  The 2026-08-04 apply added 16 resources and replaced only the callback's
  API-wide invoke permission with an exact GET permission. Slack App
  `A0BMSFX33T5` accepted `POST /slack/events/github-assistant`; its binding is
  `installed` and reconciliation is a no-op. Both Events Lambdas are ARM64,
  `Active`, and `Successful`; Terraform reports no drift. The first live event
  exposed a literal-route parsing defect (`agent_invalid`), then the worker
  exposed stale SDK request fields (`qualifier`, `runtimeUserId`). The current
  image extracts the agent from HTTP API `rawPath` and uses `actorId` for
  Harness invocation. The next live event exposed a worker-role mismatch: the
  SDK operation is `InvokeHarness`, but IAM authorizes it as
  `bedrock-agentcore:InvokeAgentRuntime` in the prior image and
  `bedrock-agentcore:InvokeHarness` in the refactored image. The worker role now
  grants both action names on the exact Harness ARN; IAM simulation allows the
  current `InvokeHarness` action. The intermediate apply changed both
  Lambda handler overrides to the moved `slack_events.*` modules while retaining
  the old image, causing `Runtime.ImportModuleError` before invocation.
- Container source is now co-located under each `containers/<name>/service`
  tree. `docker-bake.hcl` replaces the deleted Python build framework. All
  three ARM64 service images build and import locally. Refactored Slack Events
  image `sha256:c67c95a9bc224432fb517dcba7bfc1c30ee838e0d9839d8ad03a2d01fac33581`
  was deployed to both Events Lambdas and proved the moved modules imported
  successfully. The later working-status image is recorded below.
- The Slack Events worker now sets Slack's native thread working status before
  Harness invocation. It uses the existing `chat:write` scope, auto-clears when
  the reply posts, and degrades safely if the status API is unavailable. Image
  `sha256:6c4ad76ccf32cc656f086ee202e6c1a4c8dae1dd2ec63f6dad4483c1de704a96`
  was deployed 2026-08-05 to both Events Lambdas. The reviewed apply updated
  both in place and replaced only the exact Events invoke permission: 1 added,
  2 changed, 1 destroyed. Both are ARM64, `Active`, and `Successful`; the exact
  digest is resolved on both, the permission allows only the agent POST route,
  and the follow-up plan has no drift. On 2026-08-05 the operator confirmed the
  working status appears during a live request and clears when the reply arrives.
- `SLACK-004` is deployed: the temporary
  `https://localhost/slack/oauth/callback` workflow is fully removed from
  source and docs and replaced with `containers/slack-oauth-callback`, a
  single-purpose Lambda behind `modules/slack-oauth-callback` (HTTP API
  Gateway; its only currently deployed public route is `GET /slack/oauth/callback`).
  `contracts/slack_oauth_state.py` signs/verifies a compact, expiring,
  per-agent HMAC state; `clients/slack/reconciliation.py` now generates a
  `state_signing_key` per agent, threads an exact `redirect_uri` into
  `oauth.v2.access`, and adds a no-Slack/no-SSM-write `install-url` command;
  `render_slack_manifest.py` and `reconcile.py` require explicit callback and
  Events URLs. All 126 repository unit tests passed at that deployment (27 new for
  the callback, 20 new for state signing), covering missing/malformed/
  expired/tampered state, workspace/App/bot-token mismatches, exact
  `redirect_uri` equality, canonical SSM paths and `SecureString` writes, and
  that a duplicate/replayed callback cannot corrupt a completed installation.
  Current validation passes all 130 repository unit tests. The authorized
  2026-08-04 apply created exactly 10 resources, 0 changed, and 0 destroyed.
  Read-only verification found the digest-pinned `arm64` image Lambda `Active`
  with `LastUpdateStatus: Successful`, API Gateway route exactly
  `GET /slack/oauth/callback`, its scoped invoke permission, and a no-change
  follow-up plan. The callback URL is
  `https://weil984s77.execute-api.us-east-1.amazonaws.com/slack/oauth/callback`.
  The signed installation callback succeeded at 2026-08-04T23:50:41Z with
  redacted-safe request ID `5bc3846c-2fd8-4677-ae08-1aaf772fb931`, App and
  workspace validation, five granted scopes, and no secret output.
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
- The active IAM Harness is version 20 and `READY`; it has one IAM GitHub
  Gateway tool and all eight deployed operations. A direct IAM
  Harness-to-Gateway repository-list invocation succeeded.
- The deployed Harness has the custom container, built-in shell/file allow-list,
  and public-mode AgentCore-managed session storage at `/mnt/workspace`; it has
  no VPC or EFS mount.
- No Telegram/Slack-to-GitHub invocation or live mutation has succeeded.
- The installed GitHub App write permissions and selected-repository mutation
  path are verified by the successful native proof above.
- The Slack OAuth callback infrastructure was applied; no GitHub, Slack, or
  Telegram setting was changed.
- PKG-001 is applied. The broker Lambda is now a digest-pinned `arm64`
  container image (`PackageType: Image`, `Active`, `LastUpdateStatus:
  Successful`), not a zip package. A read-only `listRepositories` invocation
  against the new image returned both selected repositories, so the image
  reads the secret, mints an App JWT, and reaches GitHub. Zip packaging is
  gone from source and from the deployment.
- Both Lambdas in the repository are deployed as container images.
  `slack-oauth-callback` uses the pinned digest
  `sha256:80d4fc9962a491300005855a8d7a5ad5467a9f09c1129f3edb5d72e1119027e7`.
- Plan review caught a defect the plan could not show: destroying a Lambda
  deletes its resource-based policy, but `aws_lambda_permission.gateway` keys
  off an unchanged `function_name` and so showed no diff. Without
  `replace_triggered_by` the Gateway would have lost invoke permission
  silently. The applied plan recreated the permission with the function.
- `aws_ecr_repository.harness_coding` was not touched. Harness v20's pinned
  coding-image digest is unchanged.

## Blockers

- Events control-plane rollout is complete. Live DM and mention-thread proof on
  the new path remains.
- The scoped GitHub platform and Harness plans applied. No GitHub App settings
  changed from this environment.
- User-delegated GitHub remains blocked on a fixed and isolated Harness 3LO path
  or an explicit custom Runtime decision.

## Next

Next for Slack: run one DM and one mention-thread conversation through the new
Events path, then revoke the obsolete Slack app-level Socket Mode token.
`CHAT-001` and `E2E-001` remain separate gates.

Next after PKG-001: the broker path is proven at the Lambda boundary only. A
2026-08-04 Harness retry did not reach Gateway: `get-harness` showed v20
`READY`, the `github-read` Gateway, and all nine `@github-read/*` operations,
but the fresh runtime session exposed only `shell` and `file_operations` and
rejected `@github-read/listRepositories` as unavailable. The Lambda log showed
no Gateway invocation for that retry. Diagnose this control-plane/runtime tool
discrepancy separately; do not attribute it to the container Lambda, whose
direct read-only invocation succeeded. PKG-002 (moving the coding-image
repository into `container-registry`) and CI-001 (wiring Bake validation and
authorized pushes into a pipeline) remain open.

Next for the GitHub/Harness slice: review PR #1 and separately decide whether to
retire the now-proven Gateway fallback. No PR merge, Gateway retirement, or
resource deletion is authorized. Replace direct token delivery with
credential-isolated MCP/service work before production use.
