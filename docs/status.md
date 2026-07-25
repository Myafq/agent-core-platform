# Current status

Last updated: 2026-07-24

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

## Not verified

- No Slack adapter exists.
- No shared channel core exists.
- No GitHub App, installation, private-key secret, Lambda broker, or Lambda
  Gateway target exists in source.
- No Terraform plan exists for the replacement architecture.
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
- HARNESS-001 source is a standalone IAM chat-only composition. It has only
  model, prompt, limits, managed memory/session, and observability permissions;
  GitHub Gateway, OAuth, Token Vault, JWT, browser, and code-interpreter code
  was removed. Static formatting and tests passed. Its Terragrunt init/validate/
  plan attempt was blocked before startup by the mise AWS SSM hook failing to
  reach `https://ssm.us-east-1.amazonaws.com/`; no plan was generated.
- No replacement IAM Harness is deployed.
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

Next: restore AWS/SSM connectivity, then rerun the HARNESS-001 create-only
Terragrunt init/validate/plan commands. No apply is authorized.
