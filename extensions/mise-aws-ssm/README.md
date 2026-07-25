# mise AWS SSM environment plugin

Loads selected AWS Systems Manager Parameter Store `SecureString` values into a
mise environment. The mapping contains parameter names only; it does not contain
secret values.

## Install locally

```shell
scripts/bootstrap_mise_plugins.sh
```

The script is idempotent and links the checked-out extension before mise parses
the repository environment directive.

This repository currently has no SSM parameter mapping. For a repository that
needs one, add parameter names (never values) to `mise.toml`:

```toml
[env]
_.aws-ssm = { tools = true, parameters = { EXAMPLE_TOKEN = "/service/example-token" } }
```

`tools = true` makes a mise-managed AWS CLI available to the plugin. The plugin
inherits `AWS_PROFILE` and `AWS_REGION` from the current shell; `profile` and
`region` options may override either when a repository needs a fixed default.

Verify without printing a secret:

```shell
mise exec -- sh -c 'test -n "$EXAMPLE_TOKEN"'
```

The plugin requests each value with `aws ssm get-parameter --with-decryption` on
every mise environment activation. It deliberately does not use mise environment
caching, so Parameter Store rotation is observed on the next activation. Do not
use `mise env` or `env` to inspect the result because either command prints the
secret values.

The caller needs only `ssm:GetParameter` for each configured parameter and, for
customer-managed KMS keys, the matching `kms:Decrypt` permission.
