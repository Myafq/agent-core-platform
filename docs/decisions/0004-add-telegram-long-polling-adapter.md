# ADR 0004: Add a Telegram long-polling adapter before runtime availability

- Status: Accepted
- Date: 2026-07-19

## Context

ADR 0002 chose a local CLI first to avoid public ingress and messaging-specific
complexity before the Harness path was proven. Bedrock quota prevents continued
runtime testing, while the Telegram protocol adapter can be designed and tested
without AWS or a live bot token.

## Decision

Add an optional local long-polling Telegram adapter. It processes private text
messages only, keeps a stable session per chat, supports `/start`, `/help`, and
`/new`, and invokes the same deployed Harness as the local CLI.

The adapter must refuse to run while a Telegram webhook is configured. It does
not create a webhook, public endpoint, AWS resource, or secret. The bot token is
read only from an environment variable.

## Consequences

- The local CLI remains the first and simplest interface.
- A developer can test the Telegram user experience while running the local
  process and after the Harness becomes invokable.
- Webhook deployment, persistent session state, group support, and inbound JWT
  identity remain separate work.
