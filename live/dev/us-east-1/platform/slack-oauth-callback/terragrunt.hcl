include "root" { path = find_in_parent_folders("root.hcl") }

terraform { source = "../../../../../modules/slack-oauth-callback" }

inputs = {
  name               = "slack-oauth-callback"
  slack_workspace_id = get_env("SLACK_WORKSPACE_ID", "T0BKR092ATB")
  # Produced by `scripts/containers.py digests slack-oauth-callback --json`
  # from source tag src-1ddf55fe0e03, pushed 2026-08-04. Re-pin from that
  # command's output after any rebuild; never hand-write a digest.
  image_uri = "803629127460.dkr.ecr.us-east-1.amazonaws.com/slack-oauth-callback@sha256:80d4fc9962a491300005855a8d7a5ad5467a9f09c1129f3edb5d72e1119027e7"
  tags      = { Component = "slack-oauth-callback" }
}
