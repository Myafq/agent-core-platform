# Development runbook

Run commands from the repository root unless a command says otherwise.

## Verify tools

```shell
terraform version
terragrunt --version
aws --version
python3 --version
```

Expected release lines are recorded in `AGENTS.md` and the version files.

## Create the Python environment

```shell
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pip install -r clients/cli/requirements.txt
```

## Validate locally

```shell
.venv/bin/python scripts/validate_spec.py agents/github-assistant/agent.yaml
python3 -m py_compile scripts/validate_spec.py clients/cli/chat.py
python3 -m json.tool schemas/agent-v1alpha1.schema.json >/dev/null
terraform fmt -check -recursive modules
terragrunt hcl fmt --check
```

If the installed Terragrunt release uses a different non-deprecated formatting
command, update this runbook and record the exact verified command in
`docs/status.md`.

## Initialize and validate Terraform

```shell
export AWS_PROFILE=your-profile
export AWS_REGION=us-east-1
cd live/dev/us-east-1/github-assistant
terragrunt init
terragrunt validate
terragrunt plan -out=plan.tfplan
```

Before accepting a plan, confirm it contains only the expected Harness IAM role,
inline policy, and Harness. Do not commit `plan.tfplan`, generated state, or caches.

The apply also runs the AWS CLI to set the Harness model API format because AWS
provider 6.55 does not expose that control-plane field. The local principal must
have permission to update the Harness in addition to the normal Terraform
permissions.

Terraform state is stored in the encrypted S3 backend with S3-native locking.
The development state key is `dev/us-east-1/github-assistant/terraform.tfstate`.
Do not delete the local cache copy until migration and `terragrunt plan` have
both completed successfully.

## Apply

Apply only with explicit user authorization:

```shell
cd live/dev/us-east-1/github-assistant
terragrunt apply plan.tfplan
terragrunt output -raw harness_arn
```

Record non-sensitive resource identifiers and the provider/tool versions in
`docs/status.md`.

## Create the GitHub OAuth credential provider

The GitHub OAuth App client ID and secret are read locally from the existing SSM
Parameter Store SecureString parameters. They are supplied only to ephemeral
variables in the `github-assistant` unit and the AWS provider's write-only
arguments; do not use an `aws_ssm_parameter` Terraform data source because the
parameter value would be recorded in Terraform state.

Before using mise in this repository, run the idempotent bootstrap once:

```shell
scripts/bootstrap_mise_plugins.sh
```

The repository `mise.toml` maps the required Terraform variables to Parameter
Store names. Set `AWS_PROFILE` and `AWS_REGION` in the shell, then use
`mise exec` for every Terraform or Terragrunt command; it fetches the values
only for that command.

This creates an AWS Identity resource. Run it only with explicit authorization:

```shell
export AWS_PROFILE=your-profile
export AWS_REGION=us-east-1
cd live/dev/us-east-1/github-assistant
mise exec -- terragrunt apply
```

After creation, retrieve the generated callback URL and register it in the
GitHub OAuth App. This command does not read any secret:

```shell
aws bedrock-agentcore-control get-oauth2-credential-provider \
  --name github-assistant-oauth \
  --region "$AWS_REGION" \
  --query 'callbackUrl' \
  --output text
```

## Invoke

```shell
.venv/bin/python clients/cli/chat.py \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE" \
  --harness-arn "$(cd live/dev/us-east-1/github-assistant && terragrunt output -raw harness_arn)"
```

The invoking AWS principal needs the relevant AgentCore Harness invocation
permissions. Never paste tokens or credentials into the chat transcript.

## Run the local Telegram adapter

Create a bot with Telegram's `@BotFather`, then export its token locally. Do not
commit it or place it in YAML. Long polling cannot run while a Telegram webhook
is configured.

```shell
export TELEGRAM_BOT_TOKEN=your-bot-token
.venv/bin/python clients/telegram/bot.py \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE" \
  --harness-arn "$(cd live/dev/us-east-1/github-assistant && terragrunt output -raw harness_arn)"
```

The adapter handles private text chats only. Use `/new` for a new Harness
session. Stop it with `Ctrl-C`; no Telegram or AWS resource is changed.

Append `--debug` to log Telegram requests and responses, incoming updates,
offsets, session changes, and Harness stream events to stderr. Debug logs include
chat content and resource identifiers, but never the bot token; do not share
them outside the trusted development environment.

## Cleanup

Destroy is destructive and requires explicit user authorization:

```shell
cd live/dev/us-east-1/github-assistant
terragrunt plan -destroy
terragrunt destroy
```

After cleanup, verify the Harness and IAM role are gone and update
`docs/status.md`. Local state is the only resource inventory until remote state is
introduced, so protect it while resources exist.
