output "credential_provider_arn" {
  description = "Non-secret ARN consumed by shared Gateways and agent tools."
  value       = aws_bedrockagentcore_oauth2_credential_provider.github.credential_provider_arn
}

output "client_secret_arn" {
  description = "Non-secret ARN of the AgentCore-managed OAuth client secret."
  value       = one(aws_bedrockagentcore_oauth2_credential_provider.github.client_secret_arn).secret_arn
}
