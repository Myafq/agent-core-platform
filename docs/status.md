# Current status

Last updated: 2026-07-18

## Summary

The repository contains an un-deployed M0 scaffold for a YAML-defined AgentCore
Harness and a local streaming CLI. No AWS resources have been created by this
repository.

## Implemented

- `v1alpha1` JSON Schema and sample `github-assistant` YAML.
- External system prompt with directory-bound reference validation.
- Terragrunt dev unit that decodes YAML and resolves the prompt.
- Terraform module for Harness, execution role/policy, model settings, limits,
  tags, and outputs.
- Streaming Python CLI with stable local user ID and replaceable session ID.
- Current release pins: Terraform 1.15.7 and Terragrunt 1.1.1.
- Repository handoff documentation and task tracker.

## Verification evidence

- Python source compiled with Python 3.13.1.
- JSON Schema parsed with Python's standard JSON parser.
- Agent YAML parsed with Ruby Psych.
- HCL files were formatted by the previously installed Terragrunt 0.31.0 parser.
- CLI argument parser was exercised.

## Not yet verified

- Full JSON Schema validation: `jsonschema` and `PyYAML` were not installed.
- Terraform formatting, initialization, provider schema validation, or plan.
- Whether the unmatched `allowed_tools` sentinel is accepted by the live Harness
  API and suppresses built-in tools as intended.
- Bedrock model availability in the target AWS account and region.
- AWS IAM permissions, Harness creation, invocation, or cleanup.
- GitHub OAuth/Gateway behavior; those resources do not exist yet.

## Current blockers

- The user is upgrading local Terraform, Terragrunt, and AWS CLI. `TOOL-001` stays
  blocked until the new versions are visible in this environment.
- AWS validation requires a configured account/profile and model access.
- Applying infrastructure requires explicit user authorization.

## Immediate next task

After tool upgrades, complete `TEST-001`, then `TF-001`. Do not begin GitHub
infrastructure until the basic Harness validates, plans, deploys, and responds to
the CLI.

