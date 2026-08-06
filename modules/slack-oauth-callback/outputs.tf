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

output "events_url" {
  description = "Per-agent Slack Events request URLs. Empty until the image and at least one exact agent binding are supplied."
  value       = local.events_enabled ? local.events_url : {}
}

output "events_ingress_function_name" {
  value = try(aws_lambda_function.events_ingress["enabled"].function_name, null)
}

output "events_worker_function_name" {
  value = try(aws_lambda_function.events_worker["enabled"].function_name, null)
}

output "events_dead_letter_queue_url" {
  value = try(aws_sqs_queue.events_dead_letter["enabled"].url, null)
}
