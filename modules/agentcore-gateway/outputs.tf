output "gateway_arn" {
  description = "Non-secret ARN used by a future Harness Gateway tool."
  value       = aws_bedrockagentcore_gateway.this.gateway_arn
}

output "gateway_id" {
  description = "Non-secret AgentCore Gateway identifier."
  value       = aws_bedrockagentcore_gateway.this.gateway_id
}

output "gateway_url" {
  description = "Non-secret MCP endpoint URL."
  value       = aws_bedrockagentcore_gateway.this.gateway_url
}

output "service_role_arn" {
  description = "Non-secret service role ARN scoped to the GitHub current-user target."
  value       = aws_iam_role.this.arn
}

output "github_current_user_target_id" {
  description = "Non-secret identifier of the single GitHub GET /user target."
  value       = aws_bedrockagentcore_gateway_target.github_current_user.target_id
}

output "github_oauth_provider_arn" {
  description = "Non-secret shared OAuth provider ARN passed to consuming agents."
  value       = var.github_oauth_provider_arn
}

output "github_oauth_client_secret_arn" {
  description = "Non-secret managed client-secret ARN passed to consuming agents."
  value       = var.github_oauth_client_secret_arn
}
