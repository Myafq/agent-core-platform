include "root" { path = find_in_parent_folders("root.hcl") }

terraform { source = "../../../../../modules/agentcore-harness" }

dependency "github_app_tool" {
  config_path = "../../platform/github-app-tool"

  mock_outputs_allowed_terraform_commands = ["validate"]
  mock_outputs = {
    gateway_arn = "arn:aws:bedrock-agentcore:us-east-1:000000000000:gateway/github-app-tool"
  }
}

locals {
  agent_directory = "${get_terragrunt_dir()}/../../../../../agents/github-assistant"
  agent_spec      = yamldecode(file("${local.agent_directory}/agent.yaml"))
}

inputs = {
  name            = local.agent_spec.metadata.name
  description     = local.agent_spec.metadata.description
  tags            = merge(try(local.agent_spec.metadata.tags, {}), { Component = "github-assistant" })
  model_id        = local.agent_spec.spec.model.id
  api_format      = try(local.agent_spec.spec.model.apiFormat, "converse_stream")
  temperature     = try(local.agent_spec.spec.model.temperature, 0.2)
  top_p           = try(local.agent_spec.spec.model.topP, null)
  system_prompt   = file("${local.agent_directory}/${local.agent_spec.spec.instructions.system.file}")
  max_iterations  = local.agent_spec.spec.limits.maxIterations
  max_tokens      = local.agent_spec.spec.limits.maxTokens
  timeout_seconds = local.agent_spec.spec.limits.timeoutSeconds
  gateway_arn     = dependency.github_app_tool.outputs.gateway_arn
}
