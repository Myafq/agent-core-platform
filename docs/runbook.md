# Runbook

Run from the repository root unless noted.

## Bootstrap

```shell
scripts/bootstrap_mise_plugins.sh
mise exec -- terraform version
mise exec -- terragrunt --version
mise exec -- aws --version
python3 --version
```

The repository mise plugin loads SSM values into child processes. Never run
`mise env`; it prints loaded values.

## Offline validation

```shell
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pip install -r clients/cli/requirements.txt
.venv/bin/python -m unittest discover -s tests
.venv/bin/python scripts/validate_spec.py agents/github-assistant/agent.yaml
.venv/bin/python scripts/render_slack_manifest.py agents/github-assistant/agent.yaml \
  --redirect-uri "$SLACK_OAUTH_CALLBACK_URL" >/tmp/github-assistant-slack-manifest.json
.venv/bin/python scripts/validate_contracts.py
.venv/bin/python scripts/containers.py plan --no-registry
python3 -m py_compile scripts/containers.py scripts/validate_spec.py scripts/render_slack_manifest.py clients/cli/chat.py clients/telegram/bot.py clients/slack/reconciliation.py clients/slack/reconcile.py clients/slack/launcher.py contracts/slack_oauth_state.py services/slack_oauth_callback/callback.py services/slack_oauth_callback/handler.py
python3 -m json.tool schemas/agent-v1alpha1.schema.json >/dev/null
mise exec -- terraform fmt -check -recursive modules
mise exec -- terragrunt hcl fmt --check
git diff --check
```

`render_slack_manifest.py` and every `clients/slack/reconcile.py` command that
renders a manifest (`plan`, `apply`, `install-url`, `complete-oauth`) now
require `--redirect-uri`: the platform's public OAuth callback URL. There is
no built-in default and no localhost fallback; before `platform/slack-oauth-callback`
is deployed, use any placeholder `https://` URL for offline validation only
(it never reaches Slack or SSM in `plan`/dry validation).

`validate_contracts.py` checks the frozen channel and GitHub App tool fixtures.
It permits only fixed read, branch, file-write, pull-request, merge, and issue
operations;
the GitHub App installation owns the repository boundary. `listRepositories`
uses the installation token and returns its current selected repositories;
repository additions/removals take effect without a Lambda or Harness update.

Validate the provider fixture without a backend or plan:

```shell
cd tests/fixtures/terraform-lambda-target
terraform init -backend=false
terraform validate
```

If the SSM hook cannot reach AWS, make one normal attempt, report that
environment-loading blocker, and run only direct installed-binary checks that
do not require secrets or provider startup. Do not claim provider validation.

## Target environment

Non-secret configuration:

```shell
export AWS_PROFILE=your-profile
export AWS_REGION=us-east-1
export GITHUB_APP_ID=operator-supplied
export GITHUB_APP_INSTALLATION_ID=operator-supplied
export GITHUB_APP_PRIVATE_KEY_SECRET_ARN=operator-supplied
export SLACK_WORKSPACE_ID=operator-supplied
export SLACK_APP_ID=provisioner-output
export SLACK_OAUTH_CALLBACK_URL=platform/slack-oauth-callback-terraform-output
```

Channel secrets:

```shell
export TELEGRAM_BOT_TOKEN=operator-supplied
export SLACK_BOT_TOKEN=operator-supplied
export SLACK_APP_TOKEN=operator-supplied
```

Slack provisioning parameter names:

```shell
export SLACK_PROVISIONER_PARAMETER=/agent-core/slack/provisioner/config
export SLACK_AGENT_BINDING_PARAMETER=/agent-core/slack/agents/github-assistant/binding
export SLACK_AGENT_CREDENTIALS_PARAMETER=/agent-core/slack/agents/github-assistant/credentials
```

Never commit or print these values. App and installation IDs are non-secret;
tokens, refresh tokens, client/signing secrets, and private-key material are
secrets.

The provisioner and credentials parameters are Standard-tier `SecureString`
JSON values under 4 KB. The binding is a Standard-tier `String` with no secrets.
Use `alias/aws/ssm` for the home-lab phase. Do not add the provisioner parameter
to `mise.toml`; only the reconciler may decrypt it. For `SLACK-002`, an accepted
merge to `main` is standing authorization for Slack manifest create/update and
the exact writes to these three SSM paths. It is not authorization for any other
AWS resource or Terraform action.

## GitHub App operator handoff

GHAPP-001 defines the handoff; it does not authorize registration, installation,
key generation, secret creation, or configuration changes. Before GHAPP-003,
an authorized operator must provide only these non-secret bindings to the
deployment owner:

```text
GITHUB_APP_ID=<numeric App ID, not client ID>
GITHUB_APP_INSTALLATION_ID=<numeric selected-repository installation ID>
GITHUB_APP_PRIVATE_KEY_SECRET_ARN=<pre-existing Secrets Manager secret ARN>
GITHUB_APP_PRIVATE_KEY_SECRET_KEY=agent.pem
```

Operator verification record, kept outside source and without private content:

1. App has Contents, Pull requests, and Issues read/write; no organization or account permissions;
   webhooks are inactive. If permissions were just changed, GitHub requires the
   installation owner to accept the updated permissions before any minted
   installation token reflects them; an installation token request made before
   acceptance fails safely (the broker returns `github_auth_failed`).
2. Installation uses `Only select repositories`. Its repository list is the
   live read boundary for `listRepositories`, `getRepository`, and `getFile`.
3. Numeric App ID and installation ID identify that App and installation.
4. The private key exists only in the referenced pre-existing secret; its ARN,
   not its value, is supplied to Terraform. For a JSON secret, record the key
   name (`agent.pem`) separately; Lambda reads only that value.
5. Private-key rotation has a tested previous secret version and a rollback
   owner. Revoke an old App key only after the replacement works.

If any check fails, do not plan or apply the GitHub slice. Correct the external
configuration first; do not compensate with wildcard repositories, broader App
permissions, user tokens, or key material in Terraform.

## Container images

`containers/manifest.json` is the single source of truth for every buildable
image. Each entry declares its `repository`, `dockerfile`, `context`,
`platform`, and the `sources` prefixes that affect it.

`scripts/containers.py` hashes the working-tree bytes of the tracked files
under those prefixes, plus the build configuration, into a `src-<12 hex>` tag.
ECR repositories use immutable tags, so an unchanged container is skipped
rather than re-pushed. Uncommitted edits change the tag, so a local build
always reflects what is on disk.

```shell
.venv/bin/python scripts/containers.py plan
.venv/bin/python scripts/containers.py build --all --push
.venv/bin/python scripts/containers.py digests --json
```

`plan --no-registry` computes tags with no AWS call. `plan --json` is the
change-detection gate for a future CI pipeline: build only entries whose
`action` is `build`. `build` without `--push` loads the image locally and
publishes nothing. Pushing is a mutation and needs its own authorization.

`digests --json` emits, per container name, the immutable
`<registry>/<repository>@sha256:<digest>` URI. That value — never a tag, never
a hand-written digest — is what gets pinned into Terragrunt.

## Plan order

`platform/github-app-tool` and `agents/github-assistant` are both deployed.

PKG-001 applied on 2026-08-04: the broker Lambda is a digest-pinned `arm64`
container image and `platform/container-registry` is deployed.

To ship a broker code change, repeat this order:

1. `scripts/containers.py plan` — confirm `github-tool` shows `build`.
2. `scripts/containers.py build github-tool --push`.
3. Put that container's `digests --json` `image_uri` into
   `live/dev/us-east-1/platform/github-app-tool/terragrunt.hcl`. A digest that
   was not produced by an actual push is never acceptable; `image_uri`
   validation rejects anything but a full 64-hex digest.
4. Plan `platform/github-app-tool`. A code-only change updates `image_uri` in
   place. Accept a Lambda *replacement* only when package type or architecture
   changes; if the function is replaced, `aws_lambda_permission.gateway` must
   be replaced with it, because deleting a function deletes its resource-based
   policy while `function_name` stays the same. `replace_triggered_by` enforces
   this — do not remove it.
5. After apply, confirm `State: Active`, `LastUpdateStatus: Successful`, and
   that `aws lambda get-policy` still contains `AgentCoreGatewayInvoke`.

Because change detection reads tracked files only, `git add` new container
sources before building; `containers.py` fails rather than tagging an empty
source set.

Reject any plan that would destroy or recreate `aws_ecr_repository.harness_coding`
(`github-app-tool-coding`). Deployed Harness v20 pins an immutable digest inside
it. Moving that repository into `modules/container-registry` is deferred to
PKG-002.

### HARNESS-003 image and environment repair

This subsection describes a separate, earlier change. Its acceptance rule below
constrains that Harness plan only; it does not govern PKG-001.

Harness v19 proved that control-plane environment variables were absent from
fresh runtime shells. AgentCore also rejected `AWS_REGION` as reserved. The
approved home-lab repair embeds overridable, non-secret defaults in the helper
and clears the ineffective Harness environment map. The ARM64 image is pushed
and pinned at
`github-app-tool-coding@sha256:ecb32df1a3814a799dc9bfe98d9439341041492b693a7183b62d94da5a0d130a`.
Plan only the Harness unit:

```shell
cd live/dev/us-east-1/agents/github-assistant
mise exec -- terragrunt plan
```

The Harness dependency shallow-merges real platform state with checked-in,
non-secret broker-output mocks for `validate` and `plan`; the real platform
outputs already exist in state, so this is not exercising the mock path.
Mocks are never available to `apply`.

In that Harness plan, accept only the one in-place image/environment update.
Reject any Gateway/ECR/Lambda replacement, private-key values, broad IAM,
OAuth/Token Vault resources, repository wildcards, arbitrary HTTP/Git
execution, or host mounts — none of those are part of that change. PKG-001's
authorized Lambda replacement happens in the `platform/github-app-tool` unit
above, not here.

Plans are safe. Apply requires its own explicit authorization immediately
before use:

```shell
mise exec -- terragrunt apply
```

### External dependency: GitHub App write permissions (GHAPP-003)

Before any mutation proof, an authorized operator verifies or updates the
installed GitHub App against the "GitHub App operator handoff" checklist above
(Contents, Pull requests, and Issues each `Read and write`) and, if changed,
lets GitHub's installation owner accept the update. An ad hoc credential-helper
check already showed the broker reaching GitHub and safely returning
`github_auth_failed` while requesting exactly `contents: write`,
`pull_requests: write`, `issues: write` — that isolates the remaining blocker
to this external step, not to source or the deployed Lambda/Harness path. Do
not compensate with broader App permissions, wildcard repositories, or a user
token.

### Controlled native proof (WRITE-001)

The first native mutation proof succeeded on 2026-08-04 against
`Myafq/dineza`: 5 files/85 tests passed, commit
`2d8fb68f363dedd6cb55d3d4ca7b35558f65d4aa` was pushed, and PR #1 opened.
It required per-session injection of the two non-secret region/broker values,
so repeat a read-only token-mint check after the durable image/runtime repair.
For any later proof, use one `runtimeSessionId` and one repository already selected
for the App installation. Keep the token out of shell output and Git
configuration on every command — the credential helper never writes it to a
file or repository config:

```shell
GH_TOKEN="$(github-app-token OWNER REPO)" gh repo view OWNER/REPO

git -c credential.helper='!/usr/local/bin/github-app-git-credential' \
  -c credential.useHttpPath=true clone https://github.com/OWNER/REPO.git
cd REPO

# edit: make the requested change

# test: run the target repository's own test command, e.g. `make test`

git checkout -b <branch>
git add <changed paths>
git commit -m "<message>"
git -c credential.helper='!/usr/local/bin/github-app-git-credential' \
  -c credential.useHttpPath=true push -u origin <branch>

GH_TOKEN="$(github-app-token OWNER REPO)" gh pr create \
  --repo OWNER/REPO --base <default-branch> --head <branch> \
  --title "<title>" --body "<body>"
```

`OWNER/REPO` must already be selected for this App installation; the broker
narrows every minted token to the requested repository regardless of what the
agent asks for, so an out-of-scope repository fails at token minting, not at
the Git/GitHub call. Record only redacted request IDs, commit SHA, test
outcome, and PR URL — never the token, its value, or raw command output that
contains it.

This proof exercises native `git`/`gh` through the temporary direct-credential
helper, not the Gateway/Lambda REST tools. Do not retire the Gateway slice
(`platform/github-app-tool`'s Gateway targets and the Harness `github-read`
tool) until this native proof succeeds; it remains the fallback bounded
read/write path until then. Replace this direct-credential mode with a
credential-isolated MCP/service worker before any production use.

## Channel smoke tests

Telegram:

```shell
export TELEGRAM_BOT_TOKEN=operator-supplied
export TELEGRAM_ALLOWED_USER_ID=123456789

.venv/bin/python clients/telegram/bot.py \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE" \
  --allowed-user-id "$TELEGRAM_ALLOWED_USER_ID" \
  --harness-arn "$(cd live/dev/us-east-1/agents/github-assistant && mise exec -- terragrunt output -raw harness_arn)"
```

`TELEGRAM_ALLOWED_USER_ID` is your numeric Telegram account ID, not a username
or chat ID. Private chats and this configured user only. The adapter checks that
no webhook is configured before it starts long polling; it does not remove a
webhook. Use long polling, not a webhook.

Slack:

```shell
export SLACK_BOT_TOKEN=operator-supplied
export SLACK_APP_TOKEN=operator-supplied
export SLACK_APP_ID=A01234567
export SLACK_WORKSPACE_ID=T01234567

.venv/bin/python clients/slack/bot.py \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE" \
  --app-id "$SLACK_APP_ID" \
  --workspace-id "$SLACK_WORKSPACE_ID" \
  --harness-arn "$(cd live/dev/us-east-1/agents/github-assistant && mise exec -- terragrunt output -raw harness_arn)"
```

Render the Slack app manifest from the agent declaration:

```shell
.venv/bin/python scripts/render_slack_manifest.py \
  agents/github-assistant/agent.yaml \
  --redirect-uri "$SLACK_OAUTH_CALLBACK_URL" > /tmp/github-assistant-slack-manifest.json
```

The manifest requests `app_mentions:read`, `channels:history`, `chat:write`,
`groups:history`, and `im:history`; subscribes to `app_mention`,
`message.channels`, `message.groups`, and `message.im`; and enables Socket Mode.
History events are required only so replies in an agent-owned channel thread do
not need to repeat the mention. The adapter ignores unthreaded channel messages
and threads that were not opened by mentioning the bot. It stores registered
channel/thread roots as workspace/App-partitioned hashes in `.slack-threads` and
stores no message content.

## Slack OAuth callback deployment (SLACK-004)

`platform/slack-oauth-callback` (Lambda + HTTP API Gateway,
`modules/slack-oauth-callback`) is the one public HTTP ingress for the Slack
slice: `GET /slack/oauth/callback` only. It must exist, with a known
`callback_url`, before the Slack manifest is rendered/applied for real,
because the manifest's `oauth_config.redirect_urls` and every install link
must carry that exact URL. Its image is already built and pinned; rebuild and
re-pin only if the service source changed, then plan (apply needs its own
explicit authorization):

```shell
.venv/bin/python scripts/containers.py plan
cd live/dev/us-east-1/platform/slack-oauth-callback
mise exec -- terragrunt plan
```

Accept only the one Lambda, one HTTP API (`aws_apigatewayv2_api`), one route
(`GET /slack/oauth/callback`), one `$default` auto-deploy stage, one Lambda
execution role scoped to `ssm:GetParameter`/`ssm:PutParameter` on
`/agent-core/slack/agents/*/{binding,credentials}` plus
`kms:Decrypt`/`kms:Encrypt`/`kms:GenerateDataKey` on `alias/aws/ssm` and
`logs:CreateLogStream`/`logs:PutLogEvents`, and two CloudWatch log groups
(Lambda + API Gateway access logs). Reject anything broader — in particular,
reject any route other than `GET /slack/oauth/callback` and any IAM
statement reaching outside the `agents/*` SSM prefix.

```shell
mise exec -- terragrunt apply
mise exec -- terragrunt output -raw callback_url
```

Export the output as `SLACK_OAUTH_CALLBACK_URL` for every command below that
takes `--redirect-uri`. Rollback: revert to the prior Lambda version or
remove the API Gateway route; no Slack App, installation, or SSM parameter
needs to change. Safe observability: CloudWatch Logs for the Lambda contain
only `request_id`, a fixed error classification, and (on success) the agent
name, App ID, bot user ID, and scope count — never the query string, state
token, code, or any secret. The API Gateway access log format
(`modules/slack-oauth-callback/main.tf`) has no query-string field for the
same reason.

## Slack-002 operator sequence

Scope: one existing macOS host, one Slack workspace, and manually launched
per-agent Socket Mode processes. `SLACK-003` is deferred; do not introduce an
HTTPS Events ingress in this sequence. Complete "Slack OAuth callback
deployment" above first and export `SLACK_OAUTH_CALLBACK_URL`.

1. **Bootstrap, once:** an authorized workspace owner supplies one configuration
   token plus refresh token for `/agent-core/slack/provisioner/config`. The
   reconciler alone decrypts it. This is not an adapter credential.
2. **Merge reconciliation:** after an agent change is accepted on `main`, the
   standing authorization covers only `apps.manifest.create`/update and writes
   to the exact provisioner, binding, and credentials SSM paths. Validate and
   render the manifest with `--redirect-uri "$SLACK_OAUTH_CALLBACK_URL"`, then
   create once or update the Slack App ID in the binding. `metadata.name` is
   immutable after binding creation; its path and workspace are the identity.
   `spec.interfaces.slack.name` is mutable display intent and must never be
   used to look up an app. `apply` also generates a `state_signing_key` for a
   newly created app and stores it in the same credentials `SecureString`.
3. **External approval:** each newly created Slack app still requires a human
   workspace installation approval. Generate a signed install link with
   `clients/slack/reconcile.py install-url --redirect-uri
   "$SLACK_OAUTH_CALLBACK_URL"` (it performs no Slack or SSM write, so it is
   safe to re-run if the previous link's 10-minute state expired), and send it
   to the approving workspace member. Record the App ID, workspace ID,
   installer, manifest digest, and UTC time — never the state token or code.
   Approval redirects the browser to the deployed
   `platform/slack-oauth-callback` Lambda, which verifies the state, exchanges
   the code with the exact same `redirect_uri`, and writes the bot token to
   that agent's credentials parameter and `installation_state: installed` to
   its binding — no further manual step completes installation. If the
   callback infrastructure is not deployed yet, `clients/slack/reconcile.py
   complete-oauth --redirect-uri "$SLACK_OAUTH_CALLBACK_URL"` remains
   available as a manual fallback for one exact `code`, read from an
   environment variable and never pasted into chat or logs.
4. **External app token:** a human creates one per-app `connections:write`
   token for Socket Mode. Store it only in that agent credentials parameter.
   Neither a merge nor the provisioner token approves installation or creates
   this token.
5. **Manual process start:** the macOS operator invokes the selected agent
   launcher with the same `--redirect-uri "$SLACK_OAUTH_CALLBACK_URL"` used
   above (it recomputes the manifest digest to confirm the binding matches),
   which replaces itself with the adapter. Load its binding and credentials
   only into the process environment; do not load the provisioner value. The
   bot token must authenticate to the exact `SLACK_WORKSPACE_ID`; every event
   must carry the exact non-secret `SLACK_APP_ID`.
6. **User validation and live invocation:** only after the preceding external
   approvals and manual process start, obtain explicit authorization to run the
   chat-only DM/mention proof. Record UTC time and redacted request IDs; do not
   log raw events, messages, identities, or tokens. This is neither Terraform
   plan/apply evidence nor GitHub-tool proof.

If a binding is absent after an app may have been created, stop. Resume only
with explicit adoption of the exact Slack App ID in the same workspace; never
search by display name or create a replacement. A failed reconciliation leaves
the previous binding, credentials, external Slack state, and running processes
unchanged. Removing an agent from source never deletes, disables, revokes, or
stops external state; record it for separate operator review.

Terraform plan and apply are outside Slack reconciliation. A plan remains
separate evidence; apply needs its own immediate explicit authorization.

Plan merged agent intent without Slack mutation or SSM writes:

```shell
.venv/bin/python clients/slack/reconcile.py plan \
  --spec agents/github-assistant/agent.yaml \
  --workspace-id "$SLACK_WORKSPACE_ID" \
  --redirect-uri "$SLACK_OAUTH_CALLBACK_URL" \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE"
```

After merge to `main`, the standing Slack/SSM authorization permits replacing
`plan` with `apply`. A `noop` performs no token rotation, Slack call, or SSM
write. If exact-ID adoption is required, review the workspace and App ID first,
then add `--adopt-app-id "$SLACK_APP_ID"`.

Mint a fresh signed install link for an already-reconciled binding (no Slack
or SSM write; safe to re-run if the previous state expired):

```shell
.venv/bin/python clients/slack/reconcile.py install-url \
  --spec agents/github-assistant/agent.yaml \
  --workspace-id "$SLACK_WORKSPACE_ID" \
  --redirect-uri "$SLACK_OAUTH_CALLBACK_URL" \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE"
```

With `platform/slack-oauth-callback` deployed, that link's approval flow
completes installation automatically; `complete-oauth` below is only the
manual fallback. Keep approval codes and app tokens out of command arguments
and shell history — read them silently into temporary environment variables:

```shell
read -s SLACK_OAUTH_CODE
export SLACK_OAUTH_CODE
.venv/bin/python clients/slack/reconcile.py complete-oauth \
  --spec agents/github-assistant/agent.yaml \
  --workspace-id "$SLACK_WORKSPACE_ID" \
  --redirect-uri "$SLACK_OAUTH_CALLBACK_URL" \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE" \
  --oauth-code-env SLACK_OAUTH_CODE
unset SLACK_OAUTH_CODE

read -s SLACK_SOCKET_APP_TOKEN
export SLACK_SOCKET_APP_TOKEN
.venv/bin/python clients/slack/reconcile.py set-app-token \
  --spec agents/github-assistant/agent.yaml \
  --workspace-id "$SLACK_WORKSPACE_ID" \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE" \
  --app-token-env SLACK_SOCKET_APP_TOKEN
unset SLACK_SOCKET_APP_TOKEN
```

Start one fully provisioned adapter manually from the local `main` ref:

```shell
.venv/bin/python clients/slack/launcher.py \
  --agent github-assistant \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE" \
  --redirect-uri "$SLACK_OAUTH_CALLBACK_URL" \
  --harness-arn "$(cd live/dev/us-east-1/agents/github-assistant && mise exec -- terragrunt output -raw harness_arn)"
```

## GitHub smoke tests

After an explicitly authorized GitHub App installation and deployment:

1. Confirm the App is installed on only the expected repositories.
2. Confirm permissions are Contents, Pull requests, and Issues read/write plus metadata.
3. Call `listRepositories`; it returns the installation's current selected repositories.
4. Call `getRepository` for one listed repository.
5. Call `getFile` for one small text file.
6. Reject a repository outside the installation.
7. Reject an unsafe path/ref, unknown tool, arbitrary HTTP/Git request, and
   oversized response.
8. Inspect logs for request metadata only; no credentials or private content.
9. Repeat one allowed read from Telegram and Slack.

Readiness is not invocation. A successful Lambda call alone is not a successful
Harness/channel path.

## Legacy experiment

Current legacy state owners (source removed):

```text
platform/github-oauth
platform/cognito-inbound-identity
platform/github-gateway-jwt
agents/github-assistant-jwt
```

Freeze them. Do not apply them as part of the replacement. Read-only inspection
and reviewed plans are safe. Destroy each unit separately only after E2E-001 and
explicit authorization. Preserve encrypted versioned state; never print or
commit raw state.
