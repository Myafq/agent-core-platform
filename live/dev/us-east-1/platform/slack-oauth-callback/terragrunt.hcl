include "root" { path = find_in_parent_folders("root.hcl") }

terraform { source = "../../../../../modules/slack-oauth-callback" }

inputs = {
  name               = "slack-oauth-callback"
  slack_workspace_id = get_env("SLACK_WORKSPACE_ID", "T0BKR092ATB")
  # Re-pin from `TARGET=slack-oauth-callback mise run container:push` output
  # after rebuilding a clean committed revision; never hand-write a digest.
  image_uri        = "803629127460.dkr.ecr.us-east-1.amazonaws.com/slack-oauth-callback@sha256:80d4fc9962a491300005855a8d7a5ad5467a9f09c1129f3edb5d72e1119027e7"
  events_image_uri = "803629127460.dkr.ecr.us-east-1.amazonaws.com/slack-events@sha256:f0dacf3770524d466daa480358165cb72d6a8dfaca780a846462f945305a56ee"
  slack_agents = {
    github-assistant = {
      app_id       = "A0BMSFX33T5"
      workspace_id = "T0BKR092ATB"
      harness_arn  = "arn:aws:bedrock-agentcore:us-east-1:803629127460:harness/github_assistant-wvVPPquaRI"
    }
  }
  tags = { Component = "slack-oauth-callback" }
}
