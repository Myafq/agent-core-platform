# Runbook

Run from the repository root unless noted.

## Bootstrap and validate

```shell
scripts/bootstrap_mise_plugins.sh
mise exec -- terraform version
mise exec -- terragrunt --version
mise exec -- aws --version
python3 --version

python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pip install -r clients/cli/requirements.txt
.venv/bin/python -m unittest discover -s tests
.venv/bin/python scripts/validate_spec.py agents/github-assistant/agent.yaml
.venv/bin/python scripts/validate_github_contract.py
python3 -m py_compile scripts/validate_spec.py clients/cli/chat.py
python3 -m json.tool schemas/agent-v1alpha1.schema.json >/dev/null
mise exec -- terraform fmt -check -recursive modules
mise exec -- terragrunt hcl fmt --check
git diff --check
```

Do not run `mise env`; it prints values loaded from SSM.

## Environment

```shell
export AWS_PROFILE=your-profile
export AWS_REGION=us-east-1
export GITHUB_POST_CONSENT_RETURN_URL='https://t.me/gh_agent_517_bot?start=github-consent'
```

The return URL is the browser destination after consent. It is not the
AgentCore-generated OAuth callback registered in GitHub.

## State

Use only these state owners:

```text
platform/github-oauth       dev/us-east-1/platform/github-oauth/terraform.tfstate
platform/github-gateway     dev/us-east-1/platform/github-gateway/terraform.tfstate
agents/github-assistant     dev/us-east-1/agents/github-assistant/terraform.tfstate
```

The legacy `dev/us-east-1/github-assistant/terraform.tfstate` current version is
empty. Restore an older version only as an explicitly reviewed rollback. Never
print or commit raw state.

## Plan in dependency order

OAuth is deployed and should plan with no changes:

```shell
cd live/dev/us-east-1/platform/github-oauth
mise exec -- terragrunt init
mise exec -- terragrunt validate
mise exec -- terragrunt plan -out=plan.tfplan
```

Gateway is next:

```shell
cd live/dev/us-east-1/platform/github-gateway
mise exec -- terragrunt init
mise exec -- terragrunt validate
mise exec -- terragrunt plan -out=plan.tfplan
```

Accept only the Gateway, scoped role/policy, and one
`github-current-user` target. Reject provider/Harness replacement, secret
output, operations other than `GET /user`, scopes other than `read:user`, or
broader IAM.

After the Gateway exists, plan the agent:

```shell
cd live/dev/us-east-1/agents/github-assistant
mise exec -- terragrunt init
mise exec -- terragrunt validate
mise exec -- terragrunt plan -out=plan.tfplan
```

Accept one `github` Gateway tool, exactly
`@github/getAuthenticatedUser`, and narrowly scoped Gateway/Token
Vault/workload-identity/client-secret access. The provider 6.55 Harness
`apiFormat` workaround runs `update-harness`; the operator needs that
control-plane permission.

Plans are safe. Apply or destroy requires explicit authorization. Do not apply
the GitHub tool slice until JWT-backed inbound identity exists.

If AWS provider startup times out, rerun `terragrunt init --source-update` once.
If it repeats, stop and record the blocker; repeated initialization is not
verification.

## Inspect OAuth without secrets

```shell
aws bedrock-agentcore-control get-oauth2-credential-provider \
  --name github-assistant-oauth \
  --region "$AWS_REGION" \
  --query '{name:name,arn:credentialProviderArn,status:status,vendor:credentialProviderVendor}' \
  --output json
```

Retrieve `callbackUrl` only for a local comparison with the GitHub OAuth App.
Do not paste it into shared logs.

## Invoke

```shell
.venv/bin/python clients/cli/chat.py \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE" \
  --harness-arn "$(cd live/dev/us-east-1/agents/github-assistant && mise exec -- terragrunt output -raw harness_arn)"
```

Use `/new` for a new session and `/quit` to exit. A consent URL may be shown
once; authorize, return, and retry. The current IAM caller path is not proof of
per-user OAuth isolation.

## Telegram

```shell
export TELEGRAM_BOT_TOKEN=your-bot-token
.venv/bin/python clients/telegram/bot.py \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE" \
  --harness-arn "$(cd live/dev/us-east-1/agents/github-assistant && mise exec -- terragrunt output -raw harness_arn)"
```

Private chats only. No webhook. Never commit or log the bot token.

## Cleanup

Destroy agents separately from shared platform resources. Authorization to
destroy an agent does not authorize destroying OAuth or Gateway stacks. Review a
destroy plan for the exact unit before execution.
