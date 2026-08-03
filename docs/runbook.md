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
.venv/bin/python scripts/validate_contracts.py
python3 -m py_compile scripts/validate_spec.py clients/cli/chat.py clients/telegram/bot.py
python3 -m json.tool schemas/agent-v1alpha1.schema.json >/dev/null
mise exec -- terraform fmt -check -recursive modules
mise exec -- terragrunt hcl fmt --check
git diff --check
```

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
```

Channel secrets:

```shell
export TELEGRAM_BOT_TOKEN=operator-supplied
export SLACK_BOT_TOKEN=operator-supplied
export SLACK_APP_TOKEN=operator-supplied
```

Never commit or print these values. App and installation IDs are non-secret;
tokens and private-key material are secrets.

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
   webhooks are inactive.
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

## Plan order

The target units do not exist yet. Implement them under these owners:

```text
platform/github-app-tool
agents/github-assistant
```

Build the Harness coding image for `linux/arm64`, publish it to the private ECR
repository, then plan the Harness-native workspace. The image must include Git,
GitHub CLI, Python, Make, jq, and the project toolchain. The home-lab Harness
uses AgentCore-managed session storage at `/mnt/workspace`; it stays in public
network mode and creates no VPC, NAT, EFS, or dependency-mock infrastructure.
Use the same `runtimeSessionId` to resume the workspace. Add EFS only after a
shared durable workspace becomes necessary.

Plan the transition Gateway while it remains:

```shell
./scripts/package_github_tool.sh
cd live/dev/us-east-1/platform/github-app-tool
mise exec -- terragrunt init
mise exec -- terragrunt validate
mise exec -- terragrunt plan -out=plan.tfplan
```

Accept only the scoped Gateway/Lambda resources, exact tool schemas, logs, and
roles. Reject private-key values, broad Lambda/Gateway IAM, OAuth/Token Vault
resources, repository wildcards, or arbitrary HTTP/Git execution.

Plan the Harness after platform outputs exist:

```shell
cd live/dev/us-east-1/agents/github-assistant
mise exec -- terragrunt init
mise exec -- terragrunt validate
mise exec -- terragrunt plan -out=plan.tfplan
```

Accept only the model/Harness resources, private-ECR image pull permission,
explicit built-in shell/file allow-list, public-mode session storage at the
exact mount path, and no VPC/NAT/EFS resources. Reject Cognito/JWT authorizers,
native GitHub OAuth, Token Vault access, arbitrary host mounts, or broad ECR
permissions.

Plans are safe. Apply requires explicit authorization immediately before use.
Never run `terragrunt run --all apply`.

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

Slack command will be added by SLACK-001. It must use Socket Mode with bot and
app tokens, direct messages, one workspace, and configured users only.

Run chat-only smoke tests before attaching GitHub. Record UTC time and redacted
request IDs. Do not log raw events or tokens.

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
