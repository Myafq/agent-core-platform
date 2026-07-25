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

`validate_contracts.py` checks the frozen channel and GitHub App read-tool
fixtures. It permits only `getRepository` and `getFile`; production repository
allow-lists remain environment-owned and are enforced by the broker.

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
export GITHUB_ALLOWED_REPOSITORIES=owner/repo
```

Channel secrets:

```shell
export TELEGRAM_BOT_TOKEN=operator-supplied
export SLACK_BOT_TOKEN=operator-supplied
export SLACK_APP_TOKEN=operator-supplied
```

Never commit or print these values. App and installation IDs are non-secret;
tokens and private-key material are secrets.

## Plan order

The target units do not exist yet. Implement them under these owners:

```text
platform/github-app-tool
agents/github-assistant
```

Plan platform first:

```shell
cd live/dev/us-east-1/platform/github-app-tool
mise exec -- terragrunt init
mise exec -- terragrunt validate
mise exec -- terragrunt plan -out=plan.tfplan
```

Accept only the scoped Gateway/Lambda resources, exact tool schemas, logs, and
roles. Reject private-key values, broad Lambda/Gateway IAM, OAuth/Token Vault
resources, repository wildcards, or mutation tools.

Plan the Harness after platform outputs exist:

```shell
cd live/dev/us-east-1/agents/github-assistant
mise exec -- terragrunt init
mise exec -- terragrunt validate
mise exec -- terragrunt plan -out=plan.tfplan
```

Accept only the model/Harness resources, scoped execution role, and exact
Gateway tool allow-list. Reject Cognito/JWT authorizers, native GitHub OAuth,
Token Vault access, built-in shell/filesystem/browser/code tools, or a platform
resource owned by the agent state.

Plans are safe. Apply requires explicit authorization immediately before use.
Never run `terragrunt run --all apply`.

## Channel smoke tests

Telegram:

```shell
.venv/bin/python clients/telegram/bot.py \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE" \
  --harness-arn "$(cd live/dev/us-east-1/agents/github-assistant && mise exec -- terragrunt output -raw harness_arn)"
```

Private chats and configured users only. Use long polling, not a webhook.

Slack command will be added by SLACK-001. It must use Socket Mode with bot and
app tokens, direct messages, one workspace, and configured users only.

Run chat-only smoke tests before attaching GitHub. Record UTC time and redacted
request IDs. Do not log raw events or tokens.

## GitHub smoke tests

After an explicitly authorized GitHub App installation and deployment:

1. Confirm the App is installed on only the expected repositories.
2. Confirm permissions are read-only Contents plus metadata.
3. Call `getRepository` for one allowed repository.
4. Call `getFile` for one small text file.
5. Reject a repository outside the allow-list.
6. Reject an unsafe path/ref, unknown tool, mutation request, and oversized
   response.
7. Inspect logs for request metadata only; no credentials or private content.
8. Repeat one allowed read from Telegram and Slack.

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
