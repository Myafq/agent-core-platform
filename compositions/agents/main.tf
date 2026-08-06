module "harness" {
  source = "../../modules/agentcore-harness"

  name                                  = var.name
  description                           = var.description
  tags                                  = var.tags
  model_id                              = var.model_id
  api_format                            = var.api_format
  temperature                           = var.temperature
  top_p                                 = var.top_p
  system_prompt                         = var.system_prompt
  max_iterations                        = var.max_iterations
  max_tokens                            = var.max_tokens
  timeout_seconds                       = var.timeout_seconds
  gateway_arn                           = var.gateway_arn
  github_credential_broker_function_arn = var.github_credential_broker_function_arn
  container_uri                         = var.container_uri
  container_repository_arn              = var.container_repository_arn
  session_storage_mount_path            = var.session_storage_mount_path
}

# The deployed github-assistant state predates this composition: its resources
# live at root addresses because the old object-specific entrypoint sourced
# modules/agentcore-harness directly. These moved blocks re-home every resource
# declared in modules/agentcore-harness/main.tf under module.harness so the
# migrated state plans clean with no resource recreation.

moved {
  from = aws_iam_role.this
  to   = module.harness.aws_iam_role.this
}

moved {
  from = aws_iam_role_policy.execution
  to   = module.harness.aws_iam_role_policy.execution
}

moved {
  from = aws_bedrockagentcore_harness.this
  to   = module.harness.aws_bedrockagentcore_harness.this
}

moved {
  from = terraform_data.model_api_format
  to   = module.harness.terraform_data.model_api_format
}

moved {
  from = terraform_data.session_storage_environment
  to   = module.harness.terraform_data.session_storage_environment
}
