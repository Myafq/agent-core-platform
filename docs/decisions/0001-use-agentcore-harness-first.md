# ADR 0001: Use AgentCore Harness as the default engine

- Status: Accepted
- Date: 2026-07-18

## Context

The desired agent contract is primarily declarative: model, prompt, tools, memory,
and limits. AgentCore Runtime would require an orchestration implementation and a
container before those concepts can be exercised.

## Decision

Use AgentCore Harness for the first implementation. Add a custom Runtime engine
only when a concrete requirement cannot be represented by Harness.

## Consequences

- The M0 slice has no container build pipeline.
- The YAML contract should not expose Harness provider fields directly.
- Harness/API limitations are validated early.
- Custom middleware and orchestration remain deferred escape-hatch work.

