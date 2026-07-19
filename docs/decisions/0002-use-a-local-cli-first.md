# ADR 0002: Use a local CLI as the first interface

- Status: Accepted
- Date: 2026-07-18

## Context

Telegram introduced webhook verification, public ingress, asynchronous delivery,
deduplication, and protocol-specific identity before the core agent path was proven.

## Decision

Use a local IAM-authenticated streaming CLI for M0. Add browser or messaging
interfaces only after Harness invocation and GitHub OAuth work end to end.

## Consequences

- No public endpoint or channel adapter is required for M0.
- AWS developer credentials are required locally.
- OAuth URLs can initially be opened from the terminal.
- The CLI is a thin client and must not absorb agent or infrastructure behavior.

