include "root" { path = find_in_parent_folders("root.hcl") }

terraform { source = "../../../../../modules/github-app-tool" }

inputs = {
  name                              = "github-app-tool"
  github_app_id                     = get_env("GITHUB_APP_ID")
  github_app_installation_id        = get_env("GITHUB_APP_INSTALLATION_ID")
  github_app_private_key_secret_arn = get_env("GITHUB_APP_PRIVATE_KEY_SECRET_ARN")
  github_app_private_key_secret_key = get_env("GITHUB_APP_PRIVATE_KEY_SECRET_KEY", "agent.pem")
  # Digest-pinned like agents/github-assistant's container_uri: an explicit,
  # git-reviewable string, not a dependency on platform/container-registry's
  # repository_urls output (that output only has the mutable repository
  # name, never the digest). Produced by `scripts/containers.py digests
  # github-tool --json` from source tag src-074cfeeba8bd, pushed 2026-08-04.
  # Re-pin from that command's output after any rebuild; never hand-write a
  # digest that was not produced by an actual push.
  image_uri = "803629127460.dkr.ecr.us-east-1.amazonaws.com/github-tool@sha256:35d66e94adcd255a044a3bea3d5bbae072828d87f5bec478b0055e6f36e6de27"
  tags      = { Component = "github-app-tool" }
}
