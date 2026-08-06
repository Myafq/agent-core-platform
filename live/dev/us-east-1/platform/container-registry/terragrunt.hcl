include "root" { path = find_in_parent_folders("root.hcl") }

terraform { source = "../../../../../modules/container-registry" }

inputs = {
  # github-app-tool-coding remains owned by modules/github-app-tool because
  # the deployed Harness pins an image from that repository.
  repositories = toset(["github-tool", "slack-events", "slack-oauth-callback"])
  tags         = { Component = "container-registry" }
}
