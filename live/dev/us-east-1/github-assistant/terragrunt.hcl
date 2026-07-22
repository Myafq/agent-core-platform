include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../../../modules/agentcore-harness"
}

locals {
  agent_directory = "${get_terragrunt_dir()}/../../../../agents/github-assistant"
  agent_spec      = yamldecode(file("${local.agent_directory}/agent.yaml"))
  prompt_file     = local.agent_spec.spec.instructions.system.file
}

inputs = {
  name                       = local.agent_spec.metadata.name
  description                = try(local.agent_spec.metadata.description, "")
  tags                       = try(local.agent_spec.metadata.tags, {})
  model_id                   = local.agent_spec.spec.model.id
  api_format                 = try(local.agent_spec.spec.model.apiFormat, "converse_stream")
  temperature                = try(local.agent_spec.spec.model.temperature, 0.2)
  top_p                      = try(local.agent_spec.spec.model.topP, 0.9)
  system_prompt              = file("${local.agent_directory}/${local.prompt_file}")
  max_iterations             = local.agent_spec.spec.limits.maxIterations
  max_tokens                 = local.agent_spec.spec.limits.maxTokens
  timeout_seconds            = local.agent_spec.spec.limits.timeoutSeconds
  github_oauth_provider_name = "github-assistant-oauth"
}
