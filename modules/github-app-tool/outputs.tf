output "gateway_arn" { value = aws_bedrockagentcore_gateway.this.gateway_arn }
output "gateway_id" { value = aws_bedrockagentcore_gateway.this.gateway_id }
output "lambda_arn" { value = aws_lambda_function.broker.arn }
output "harness_coding_repository_url" { value = aws_ecr_repository.harness_coding.repository_url }
output "harness_coding_repository_arn" { value = aws_ecr_repository.harness_coding.arn }
