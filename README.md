# AgentCore YAML lab

Declarative Amazon Bedrock AgentCore Harness agents: YAML describes agent intent,
Terragrunt compiles it with environment context, Terraform owns AWS resources,
and local clients invoke the deployed Harness.

The current development unit is `github-assistant`. It uses Kimi K2.5 through
Bedrock Mantle Chat Completions. GitHub OAuth is declared in the same state and
will be created by the next explicitly authorized apply.

## Requirements

- mise, with shell activation enabled.
- Terraform 1.15.8, Terragrunt 1.1.1, AWS CLI v2, and Python 3.11+ available
  through mise or `PATH`.
- An AWS profile and region. Planning, apply, and invocation need the relevant
  Bedrock AgentCore and IAM permissions.
- `ssm:GetParameter` for the two configured OAuth parameters. The repository
  loads them for every `mise exec`; customer-managed parameters also need
  `kms:Decrypt`.

Never put secret values in YAML, HCL, `.env` files, plans, state, or Git.

## First use

Run this once after checkout, before using mise from this repository:

```shell
scripts/bootstrap_mise_plugins.sh
```

It links the repository-owned `aws-ssm` mise environment plugin. The checked-in
`mise.toml` maps Parameter Store names—not values—to the GitHub OAuth Terraform
variables. The plugin fetches those values dynamically, only in a mise command.
Do not run `mise env`: it prints environment values.

Confirm the toolchain:

```shell
mise exec -- terraform version
mise exec -- terragrunt --version
mise exec -- aws --version
python3 --version
```

## Local validation

```shell
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pip install -r clients/cli/requirements.txt

.venv/bin/python scripts/validate_spec.py agents/github-assistant/agent.yaml
python3 -m py_compile scripts/validate_spec.py clients/cli/chat.py
python3 -m json.tool schemas/agent-v1alpha1.schema.json >/dev/null
mise exec -- terraform fmt -check -recursive modules
mise exec -- terragrunt hcl fmt --check
```

## Plan the development Harness

Set the profile and region before running AWS-backed commands:

```shell
export AWS_PROFILE=your-profile
export AWS_REGION=us-east-1
cd live/dev/us-east-1/github-assistant
mise exec -- terragrunt init
mise exec -- terragrunt validate
mise exec -- terragrunt plan -out=plan.tfplan
```

Inspect the plan before accepting it. Do not commit plans, state, caches, or
credentials. Development state uses the encrypted S3 backend and S3-native
locking; see the [runbook](docs/runbook.md) for the state key and recovery note.

## Apply and invoke

Apply changes only with explicit authorization:

```shell
cd live/dev/us-east-1/github-assistant
mise exec -- terragrunt apply plan.tfplan
mise exec -- terragrunt output -raw harness_arn
```

Invoke the Harness:

```shell
.venv/bin/python clients/cli/chat.py \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE" \
  --harness-arn "$(cd live/dev/us-east-1/github-assistant && mise exec -- terragrunt output -raw harness_arn)"
```

Use `/new` for a new session and `/quit` to exit. The invoking principal needs
Harness invocation permission.

## GitHub OAuth credentials

The OAuth provider creates an AWS Identity resource. With explicit
authorization, run:

```shell
export AWS_PROFILE=your-profile
export AWS_REGION=us-east-1
cd live/dev/us-east-1/github-assistant
mise exec -- terragrunt apply
```

Mise retrieves the Parameter Store values only inside `mise exec`. Retrieve the
generated callback URL with the command in the runbook; it never prints a
secret.

## More detail

- [Current status](docs/status.md)
- [Development runbook](docs/runbook.md)
- [System design](docs/design.md)
- [Task tracker](TASKS.md)
- [Architecture decisions](docs/decisions/)
- [Agent instructions](AGENTS.md)
