output "gateway_arn" { value = aws_bedrockagentcore_gateway.this.gateway_arn }
output "gateway_id" { value = aws_bedrockagentcore_gateway.this.gateway_id }
output "lambda_arn" { value = aws_lambda_function.broker.arn }
