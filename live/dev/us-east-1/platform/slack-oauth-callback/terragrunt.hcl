include "root" { path = find_in_parent_folders("root.hcl") }

terraform { source = "../../../../../modules/slack-oauth-callback" }

locals {
  repo_root = get_repo_root()

  # Manifests own portable Slack intent. This shared platform unit owns the
  # cross-agent routes and discovers every Slack-enabled agent without an
  # object-specific Terragrunt map.
  agent_manifest_paths = fileset(local.repo_root, "agents/*/agent.yaml")
  slack_manifests = {
    for manifest_path in local.agent_manifest_paths :
    regex("^agents/([^/]+)/agent\\.yaml$", manifest_path)[0] => yamldecode(file("${local.repo_root}/${manifest_path}"))
    if try(yamldecode(file("${local.repo_root}/${manifest_path}")).spec.interfaces.slack.name, null) != null
  }

  guard_slack_manifest_names = alltrue([
    for agent_name, manifest in local.slack_manifests : manifest.metadata.name == agent_name
  ]) ? "ok" : file("ERROR: every Slack-enabled agent manifest metadata.name must match its agents/<name> directory before shared Slack resources can be planned.")

  slack_agent_names = local.guard_slack_manifest_names == "ok" ? sort(keys(local.slack_manifests)) : []
}

inputs = {
  name               = "slack-oauth-callback"
  slack_workspace_id = get_env("SLACK_WORKSPACE_ID", "T0BKR092ATB")
  # Re-pin from `TARGET=slack-oauth-callback mise run container:push` output
  # after rebuilding a clean committed revision; never hand-write a digest.
  image_uri         = "803629127460.dkr.ecr.us-east-1.amazonaws.com/slack-oauth-callback@sha256:80d4fc9962a491300005855a8d7a5ad5467a9f09c1129f3edb5d72e1119027e7"
  events_image_uri  = "803629127460.dkr.ecr.us-east-1.amazonaws.com/slack-events@sha256:6c4ad76ccf32cc656f086ee202e6c1a4c8dae1dd2ec63f6dad4483c1de704a96"
  slack_agent_names = local.slack_agent_names
  agent_state = {
    bucket = "tf-state-803629127460-us-east-1-an"
    region = "us-east-1"
  }
  tags = { Component = "slack-oauth-callback" }
}
