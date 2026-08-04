include "root" { path = find_in_parent_folders("root.hcl") }

terraform { source = "../../../../../modules/slack-oauth-callback" }

inputs = {
  name                = "slack-oauth-callback"
  slack_workspace_id  = get_env("SLACK_WORKSPACE_ID", "T0BKR092ATB")
  lambda_package_path = "${get_terragrunt_dir()}/../../../../../.build/slack-oauth-callback.zip"
  tags                = { Component = "slack-oauth-callback" }
}
