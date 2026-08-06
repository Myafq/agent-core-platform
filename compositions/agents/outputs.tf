output "harness_arn" {
  description = "ARN used by InvokeHarness clients."
  value       = module.harness.harness_arn
}

output "harness_id" {
  value = module.harness.harness_id
}

output "execution_role_arn" {
  value = module.harness.execution_role_arn
}
