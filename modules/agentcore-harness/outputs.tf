output "harness_arn" {
  description = "ARN used by InvokeHarness clients."
  value       = aws_bedrockagentcore_harness.this.arn
}

output "harness_id" {
  value = aws_bedrockagentcore_harness.this.harness_id
}

output "execution_role_arn" {
  value = aws_iam_role.this.arn
}
