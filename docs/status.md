# Current status

Last updated: 2026-07-19

## Summary

The repository contains a deployed M0 YAML-defined AgentCore Harness and a local
streaming CLI. Runtime testing is paused because Bedrock quotas are reported at
zero; an execution-role update is staged locally for when testing resumes.

## Implemented

- `v1alpha1` JSON Schema and sample `github-assistant` YAML.
- External system prompt with directory-bound reference validation.
- Terragrunt dev unit that decodes YAML and resolves the prompt.
- Terraform module for Harness, execution role/policy, model settings, limits,
  tags, and outputs.
- Streaming Python CLI with stable local user ID and replaceable session ID.
- Optional local Telegram long-polling adapter for private text chats, with no
  public ingress or checked-in bot token.
- Current release pins: Terraform 1.15.8 and Terragrunt 1.1.1.
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

## Not yet verified

- Whether the unmatched `allowed_tools` sentinel is accepted by the live Harness
  API and suppresses built-in tools as intended.
- Bedrock model availability in the target AWS account and region.
- Successful streamed Harness response and cleanup.
- Live Telegram authentication, long polling, and Harness response forwarding.
- GitHub OAuth/Gateway behavior; those resources do not exist yet.

## Current blockers

- `TOOL-001` is complete: mise provides Terraform 1.15.8; Terragrunt 1.1.1 and
  AWS CLI 2.36.2 are installed.
- Bedrock quotas are reported at zero. This blocks model invocation and the
  re-plan/re-apply needed for the staged execution-role update.

## Immediate next task

Next: resume `AWS-001` after Bedrock quota is available. Offline-safe M1 work
can continue on normalized compiler output, remote-state design, and a unified
local/CI quality entry point.
