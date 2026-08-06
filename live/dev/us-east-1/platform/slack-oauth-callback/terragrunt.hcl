include "root" { path = find_in_parent_folders("root.hcl") }

terraform { source = "../../../../../modules/slack-oauth-callback" }

inputs = {
  name               = "slack-oauth-callback"
  slack_workspace_id = get_env("SLACK_WORKSPACE_ID", "T0BKR092ATB")
  # Re-pin from `TARGET=slack-oauth-callback mise run container:push` output
  # after rebuilding a clean committed revision; never hand-write a digest.
  image_uri        = "803629127460.dkr.ecr.us-east-1.amazonaws.com/slack-oauth-callback@sha256:80d4fc9962a491300005855a8d7a5ad5467a9f09c1129f3edb5d72e1119027e7"
  events_image_uri = "803629127460.dkr.ecr.us-east-1.amazonaws.com/slack-events@sha256:6c4ad76ccf32cc656f086ee202e6c1a4c8dae1dd2ec63f6dad4483c1de704a96"
  slack_agents = {
    github-assistant = {
      app_id       = "A0BMSFX33T5"
      workspace_id = "T0BKR092ATB"
      harness_arn  = "arn:aws:bedrock-agentcore:us-east-1:803629127460:harness/github_assistant-wvVPPquaRI"
    }
  }
  tags = { Component = "slack-oauth-callback" }
}
