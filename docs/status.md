# Current status

Last updated: 2026-07-25

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
  only; `Contents: Read-only`; no organization/account permissions or
  webhooks; numeric App/installation IDs; a pre-existing private-key secret
  ARN; staged key rotation and rollback. No App, installation, secret, or
  cloud configuration was created or changed.
- GHAPP-002 is implemented offline in `services/github_tool`: `listRepositories`
  reads the App installation's current selected repositories with a bounded
  installation-token request; additions/removals need no Lambda or Harness
  update. The two repository-read tools create per-request narrowed installation
  tokens and call fixed GitHub REST endpoints. All responses are normalized and
  errors safely classified. Fake-client tests verify no credential leakage. No
  Lambda, secret, GitHub App, or cloud resource was created.
- The operator applied `GATEWAY-001` on 2026-07-25. Read-only checks found
  Gateway `github-app-tool-nckdlx01xy` and Lambda `github-app-tool`; Lambda is
  `Active` and its last update is `Successful`. No broker or Gateway tool
  invocation has run. AWS Lambda-target documentation showed that the Gateway
  passes tool arguments as the event and the tool name in client context; source
  now adapts that contract, pending package and platform update.
- `HARNESS-002` reached Harness version 4 and `READY`: one `github-read`
  Gateway tool uses AWS IAM and `allowedTools` contains only
  `@github-read/getRepository` and `@github-read/getFile`. Its deployed prompt
  was still chat-only; source now corrects it, pending a separate reviewed
  Harness update.
- `TG-001` is in progress. The Telegram adapter is transport-only: private
  text parsing, bot-derived tenant identity, configured-user allow-list,
  long-polling offsets, and shared IAM Harness invocation are present in source.
  Starting it requires a supplied bot token, one numeric Telegram user ID, and
  explicit authorization for live polling and invocation.
- The first restricted Telegram poll reached Harness streaming. Kimi's
  `chat_completions` path emitted raw tool-call protocol text instead of
  executing the configured Gateway tool. Source now selects Nova 2 Lite's
  native `converse_stream` path through the active US inference profile
  `us.amazon.nova-2-lite-v1:0`; IAM is limited to that profile and its three
  documented backing foundation models. Pending reviewed apply and retry.

## Not verified

- No Slack adapter exists.
- No GitHub broker or Gateway tool invocation has succeeded. The GitHub App,
  selected installation, secret binding, and exact repository scope still need
  live verification before any read test.
- No Terraform plan exists for the replacement architecture. Direct
  Terragrunt init for `platform/github-app-tool` passed on 2026-07-25, but its
  provider-backed validate did not start because the local AWS provider 6.55.0
  exited before schema negotiation. Harness validation remains pending on the
  same local provider issue.
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
- An IAM chat-only Harness is deployed and `READY`; it has no configured
  tools/skills and its allow-list is `@disabled`. No channel invocation proof
  exists yet.
- No end-to-end Telegram/Slack-to-GitHub invocation has succeeded.
- No cloud, GitHub, Slack, or Telegram settings were changed during this review.

## Blockers

- GitHub App registration, installation, selected repositories, App ID,
  installation ID, and private-key secret ARN require explicit operator work.
- Slack app manifest/install values and tokens are not yet supplied.
- Apply, destroy, secret creation, and external app settings require explicit
  authorization.
- User-delegated GitHub remains blocked on a fixed and isolated Harness 3LO path
  or an explicit custom Runtime decision.

## Next

Next: review and apply the Nova 2 Lite model/profile change. Restart the
Telegram adapter restricted to user `111436346`, prove `/new` and one reply,
then stop it and record the redacted request ID. No channel invocation beyond
that one-user smoke test is authorized.
