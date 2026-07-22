# Current status

Last updated: 2026-07-22

## Summary

The repository contains a deployed M0 YAML-defined AgentCore Harness and a local
streaming CLI. The Harness has been successfully tested with Kimi K2.5 through
Bedrock Mantle Chat Completions.

## Implemented

- `v1alpha1` JSON Schema and sample `github-assistant` YAML.
- External system prompt with directory-bound reference validation.
- Terragrunt dev unit that decodes YAML and resolves the prompt.
- Terraform module for Harness, execution role/policy, model settings, limits,
  tags, and outputs.
- Kimi K2.5 through Bedrock Mantle (`moonshotai.kimi-k2.5`) with declarative
  `chat_completions` API-format selection. Kimi does not support Mantle
  `/v1/responses`.
- Streaming Python CLI with stable local user ID and replaceable session ID.
- Optional local Telegram long-polling adapter for private text chats, with no
  public ingress or checked-in bot token.
- Current release pins: Terraform 1.15.8 and Terragrunt 1.1.1.
- GitHub OAuth credential provider in the existing `github-assistant` Harness
  module and state. Mise passes SSM parameters only to ephemeral Terraform
  variables and write-only provider arguments.
- Repository handoff documentation and task tracker.

## Verification evidence

- Python source compiled with Python 3.13.1.
- JSON Schema parsed with Python's standard JSON parser.
- Agent YAML parsed with Ruby Psych.
- HCL files were formatted by the previously installed Terragrunt 0.31.0 parser.
- CLI argument parser was exercised.
- Checked 2026-07-19 in `.venv` with Python 3.14.6: `jsonschema` and PyYAML
  installed, sample spec validation and CLI help passed; Python compilation, JSON
  parsing, Terraform format check, and Terragrunt HCL format check passed.
- Checked 2026-07-19: `terragrunt init` selected hashicorp/aws 6.55.0 and
  `terragrunt validate` passed with Terraform 1.15.8.
- Checked 2026-07-19 with the default AWS profile in us-east-1: the first plan
  contains 3 creates only—the Harness, execution role, and its inline
  model-invocation policy. No replacements or prompt content were exposed.
- Applied 2026-07-19 in us-east-1. Harness output resolved; the CLI reached the
  service, but invocation failed because the Harness execution role lacks
  `bedrock-agentcore:ListEvents` on its memory resource.
- Checked 2026-07-19: six standard-library CLI-level validator tests passed,
  covering valid and invalid specs plus prompt-reference safety.
- Checked 2026-07-19: five token-free Telegram adapter tests, all validator
  tests, Python compilation, and Telegram CLI help passed.
- Checked 2026-07-19: Telegram `--debug` help is present and all 11 offline
  tests pass. Debug output excludes the bot token.
- Checked 2026-07-20: Kimi K2.5 model spec validation, 11 offline tests,
  Terraform formatting, Terragrunt formatting, and `terragrunt validate` passed.
  Validation reports existing AWS provider deprecation warnings for
  `data.aws_region.current.name`.
- User confirmed 2026-07-20: deployed Harness invocation succeeds with
  `moonshotai.kimi-k2.5` using Mantle `chat_completions`.
- Checked 2026-07-22: the GitHub OAuth credential-provider unit initialized
  against hashicorp/aws 6.55.0 and `terragrunt validate` passed. No Parameter
  Store values were read and no AWS resources were created.
- Checked 2026-07-22: GitHub OAuth was merged into the existing Harness
  Terragrunt unit and local state. A read-only plan refreshed the deployed
  Harness without resource replacement.
- Checked 2026-07-22: migrated `github-assistant` state to encrypted, versioned
  S3 key `dev/us-east-1/github-assistant/terraform.tfstate` with S3-native
  locking. Remote-state plan loaded the existing Harness and staged only the
  GitHub OAuth credential provider; write-only credential values were not shown.
- Checked 2026-07-22: `extensions/mise-aws-ssm` was tested with a local mocked
  AWS CLI. It maps configured SecureString names to environment values without
  printing or caching them. Terraform receives its inputs through the repository
  `mise.toml`.
- Checked 2026-07-22: the linked `aws-ssm` mise plugin read both configured
  SecureStrings from Parameter Store in a non-printing test; both Terraform
  environment variables were non-empty. Values were not logged.
- Checked 2026-07-22: `scripts/bootstrap_mise_plugins.sh` links the checked-out
  `aws-ssm` extension from `/private/tmp` before mise parses project
  configuration. `mise plugins ls` reported `aws-ssm`.
- Checked 2026-07-22: the root README was updated with current tool, AWS
  access, mise bootstrap, dynamic-SSM, validation, deployment, and invocation
  requirements.
- Checked 2026-07-22: replaced all deprecated `data.aws_region.current.name`
  references in the Harness module with `.region`; Terraform formatting and a
  source scan passed. `terragrunt validate` was blocked by unavailable DNS for
  `sts.us-east-1.amazonaws.com`, so warning removal is not runtime-validated.

## Not yet verified

- Whether the unmatched `allowed_tools` sentinel is accepted by the live Harness
  API and suppresses built-in tools as intended.
- Bedrock model availability in the target AWS account and region.
- Successful streamed Harness response and cleanup are verified for the Harness;
  Telegram forwarding remains unverified.
- Live Telegram authentication, long polling, and Harness response forwarding.
- GitHub OAuth/Gateway behavior; the credential provider is staged but not
  created, and no user has authorized it.

## Current blockers

- `TOOL-001` is complete: mise provides Terraform 1.15.8; Terragrunt 1.1.1 and
  AWS CLI 2.36.2 are installed.
- The local Terraform principal needs the AgentCore control-plane permission
  required by the `update-harness` post-create step when changing model config.
- GitHub M2 requires an explicit choice between the repository's GitHub App
  user-token target and AgentCore's native `GithubOauth2` provider, which uses
  a GitHub OAuth App. The native OAuth path is safe for the planned `GET /user`
  and public-resource spike, but GitHub cannot scope private source-code access
  to read-only; its `repo` scope includes write access. No external GitHub or
  AWS identity resource has been changed.

## Immediate next task

Next: explicitly authorize creation of the staged credential provider, register
its generated callback URL, then complete `GH-001` with the documented
two-user, `read:user` experiment.
