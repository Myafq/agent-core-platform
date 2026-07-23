include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../../../../modules/agentcore-harness"
}

dependency "github_gateway" {
  config_path = "../../platform/github-gateway"

  # The Gateway is a prerequisite for apply. These shape-valid placeholders
  # allow plan/validate before its first deployment, but are never usable for
  # apply. Once Gateway state has outputs, Terragrunt uses those real values.
  mock_outputs_allowed_terraform_commands = ["validate", "plan"]
  mock_outputs = {
    gateway_arn                    = "arn:aws:bedrock-agentcore:us-east-1:000000000000:gateway/github-assistant-gateway-mock"
    github_oauth_provider_arn      = "arn:aws:bedrock-agentcore:us-east-1:000000000000:token-vault/default/oauth2credentialprovider/github-assistant-oauth-mock"
    github_oauth_client_secret_arn = "arn:aws:secretsmanager:us-east-1:000000000000:secret:bedrock-agentcore-identity!default/oauth2/github-assistant-oauth-mock"
  }
}

locals {
  agent_directory = "${get_terragrunt_dir()}/../../../../../agents/github-assistant"
  agent_spec      = yamldecode(file("${local.agent_directory}/agent.yaml"))
  prompt_file     = local.agent_spec.spec.instructions.system.file
}

inputs = {
  name                           = local.agent_spec.metadata.name
  description                    = try(local.agent_spec.metadata.description, "")
  tags                           = try(local.agent_spec.metadata.tags, {})
  model_id                       = local.agent_spec.spec.model.id
  api_format                     = try(local.agent_spec.spec.model.apiFormat, "converse_stream")
  temperature                    = try(local.agent_spec.spec.model.temperature, 0.2)
  top_p                          = try(local.agent_spec.spec.model.topP, 0.9)
  system_prompt                  = file("${local.agent_directory}/${local.prompt_file}")
  max_iterations                 = local.agent_spec.spec.limits.maxIterations
  max_tokens                     = local.agent_spec.spec.limits.maxTokens
  timeout_seconds                = local.agent_spec.spec.limits.timeoutSeconds
  github_gateway_arn             = dependency.github_gateway.outputs.gateway_arn
  github_oauth_provider_arn      = dependency.github_gateway.outputs.github_oauth_provider_arn
  github_client_secret_arn       = dependency.github_gateway.outputs.github_oauth_client_secret_arn
  github_post_consent_return_url = get_env("GITHUB_POST_CONSENT_RETURN_URL")
}
