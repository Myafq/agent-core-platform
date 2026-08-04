output "callback_url" {
  description = "Stable public HTTPS URL for GET /slack/oauth/callback. Pass as --redirect-uri to scripts/render_slack_manifest.py and clients/slack/reconcile.py."
  value       = local.redirect_uri
}

output "lambda_arn" {
  value = aws_lambda_function.callback.arn
}

output "lambda_function_name" {
  value = aws_lambda_function.callback.function_name
}

output "api_id" {
  value = aws_apigatewayv2_api.this.id
}
