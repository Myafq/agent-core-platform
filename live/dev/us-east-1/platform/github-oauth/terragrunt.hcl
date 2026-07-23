include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../../../../modules/agentcore-oauth-provider"
}

inputs = {
  # Preserve the applied provider exactly during the state-only ownership move.
  name        = "github-assistant-oauth"
  description = "A terminal assistant that will gain read-only GitHub tools."
  tags = {
    Agent   = "github-assistant"
    Project = "agentcore-yaml-lab"
  }
}
