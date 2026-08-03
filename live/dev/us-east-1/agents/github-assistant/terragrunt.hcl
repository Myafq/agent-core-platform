include "root" { path = find_in_parent_folders("root.hcl") }

terraform { source = "../../../../../modules/agentcore-harness" }

dependency "github_app_tool" {
  config_path = "../../platform/github-app-tool"

  # Supports graph-wide validation and planning before the platform state has
  # the newly added broker outputs. Apply always reads real dependency state.
  mock_outputs_allowed_terraform_commands = ["validate", "plan"]
  mock_outputs_merge_strategy_with_state  = "shallow"
  mock_outputs = {
    gateway_arn                     = "arn:aws:bedrock-agentcore:us-east-1:803629127460:gateway/github-app-tool-nckdlx01xy"
    credential_broker_function_arn  = "arn:aws:lambda:us-east-1:803629127460:function:github-app-tool"
    credential_broker_function_name = "github-app-tool"
  }
}

locals {
  agent_directory = "${get_terragrunt_dir()}/../../../../../agents/github-assistant"
  agent_spec      = yamldecode(file("${local.agent_directory}/agent.yaml"))
}

inputs = {
  name                                   = local.agent_spec.metadata.name
  description                            = local.agent_spec.metadata.description
  tags                                   = merge(try(local.agent_spec.metadata.tags, {}), { Component = "github-assistant" })
  model_id                               = local.agent_spec.spec.model.id
  api_format                             = try(local.agent_spec.spec.model.apiFormat, "converse_stream")
  temperature                            = try(local.agent_spec.spec.model.temperature, 0.2)
  top_p                                  = try(local.agent_spec.spec.model.topP, null)
  system_prompt                          = file("${local.agent_directory}/${local.agent_spec.spec.instructions.system.file}")
  max_iterations                         = local.agent_spec.spec.limits.maxIterations
  max_tokens                             = local.agent_spec.spec.limits.maxTokens
  timeout_seconds                        = local.agent_spec.spec.limits.timeoutSeconds
  gateway_arn                            = dependency.github_app_tool.outputs.gateway_arn
  github_credential_broker_function_arn  = dependency.github_app_tool.outputs.credential_broker_function_arn
  github_credential_broker_function_name = dependency.github_app_tool.outputs.credential_broker_function_name
  container_uri                          = "803629127460.dkr.ecr.us-east-1.amazonaws.com/github-app-tool-coding@sha256:54450f0aeb93ae43d92f184802fbe12c271e7254eb5c73ae438b62a734b11686"
  container_repository_arn               = "arn:aws:ecr:us-east-1:803629127460:repository/github-app-tool-coding"
  session_storage_mount_path             = "/mnt/workspace"
}
