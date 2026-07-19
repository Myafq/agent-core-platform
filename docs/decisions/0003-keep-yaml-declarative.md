# ADR 0003: Keep YAML declarative and versioned

- Status: Accepted
- Date: 2026-07-18

## Context

Embedding arbitrary business logic in YAML would create a bespoke programming
language with unclear testing, security, and compatibility semantics.

## Decision

YAML describes agent intent. Terragrunt resolves references and environment
context. Terraform provisions resources. Deterministic business logic belongs in
tested clients, adapters, Lambda functions, MCP servers, or Runtime code.

## Consequences

- The schema can be validated before infrastructure operations.
- Provider changes are isolated behind normalization and modules.
- Prompts and skills remain assets rather than inline Terraform implementation.
- New executable behavior requires a named, testable component.

