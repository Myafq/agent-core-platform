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

## Apply

Apply only with explicit user authorization:

```shell
cd live/dev/us-east-1/github-assistant
terragrunt apply plan.tfplan
terragrunt output -raw harness_arn
```

Record non-sensitive resource identifiers and the provider/tool versions in
`docs/status.md`.

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
