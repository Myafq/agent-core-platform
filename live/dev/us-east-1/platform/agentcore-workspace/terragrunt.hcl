include "root" { path = find_in_parent_folders("root.hcl") }

terraform { source = "../../../../../modules/agentcore-workspace" }

inputs = {
  name = "github-assistant-workspace"
  tags = {
    Component = "github-assistant"
  }
}
