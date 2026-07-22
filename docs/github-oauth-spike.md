# GitHub OAuth identity-propagation spike

Status: ready to create the credential provider; live identity proof awaits user
consent.
Date: 2026-07-22

## Finding

The current AgentCore Harness API supports an `agentcore_gateway` tool with an
OAuth credential provider. AgentCore Identity's built-in GitHub provider is
`GithubOauth2`, which takes a GitHub OAuth App client ID and secret.

This differs from the repository's earlier target of a GitHub App user access
token. The staged provider uses the native GitHub OAuth App path.

For this spike, request only `read:user` and call `GET /user`; public repository
operations need no repository OAuth scope. GitHub OAuth Apps cannot grant
read-only access to private source code: their `repo` scope includes write
access. Private repository tools remain out of scope until a GitHub App or
custom identity path is selected.

## Required live experiment

1. A development-only GitHub OAuth App is registered. Do not grant write scopes.
2. The client ID and secret are stored as SecureString parameters at
   `/gh-agent/gh-oauth-client-id` and `/gh-agent/gh-oauth-client-secret`.
   Mise passes them as ephemeral, write-only Terraform values for each
   `mise exec -- terragrunt` command. Capture the generated callback URL.
3. Add that generated callback URL to the OAuth App.
4. Deploy a read-only Gateway target and attach it to the deployed Harness with
   OAuth outbound authentication.
5. Invoke the Harness twice with different `runtimeUserId` values. Complete
   GitHub consent only for the first identity.
6. Verify that the first identity can call `GET /user` through the tool and the
   second receives a new authorization requirement rather than the first
   identity's credential. Record CloudTrail request IDs and non-secret resource
   ARNs only.

## Decision required

Choose one:

- GitHub OAuth App: native AgentCore `GithubOauth2` path; implement M2 with
  authorization-code OAuth and the generated per-provider callback URL.
- GitHub App: retains the original user-token design, but needs a custom OAuth
  provider/adapter validation instead of AgentCore's built-in GitHub provider.

## Sources

- https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-tools.html
- https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/identity-idp-github.html
- https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/get-workload-access-token.html
- https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps
- https://docs.github.com/en/apps/oauth-apps/using-oauth-apps/authorizing-oauth-apps
