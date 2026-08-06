# Public HTTPS ingress for Slack installation and events. The OAuth callback
# remains isolated in its own Lambda. Events are verified and acknowledged by
# a short-lived ingress Lambda, then durably queued for the worker.

locals {
  common_tags                = merge(var.tags, { Component = "slack-oauth-callback" })
  agent_parameter_arn_prefix = "arn:aws:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:parameter${var.agent_parameter_prefix}"
  event_agent_parameter_arns = flatten([for agent_name in keys(var.slack_agents) : ["${local.agent_parameter_arn_prefix}/${agent_name}/binding", "${local.agent_parameter_arn_prefix}/${agent_name}/credentials"]])
  events_enabled             = var.events_image_uri != null && length(var.slack_agents) > 0
  events                     = local.events_enabled ? { enabled = true } : {}
  redirect_uri               = "${trimsuffix(aws_apigatewayv2_stage.default.invoke_url, "/")}/slack/oauth/callback"
  events_url                 = { for agent_name in keys(var.slack_agents) : agent_name => "${trimsuffix(aws_apigatewayv2_stage.default.invoke_url, "/")}/slack/events/${agent_name}" }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

data "aws_kms_alias" "ssm" {
  name = "alias/aws/ssm"
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.name}"
  retention_in_days = var.log_retention_days
  tags              = local.common_tags
}

resource "aws_cloudwatch_log_group" "access" {
  name              = "/aws/apigateway/${var.name}"
  retention_in_days = var.log_retention_days
  tags              = local.common_tags
}

resource "aws_cloudwatch_log_group" "events_ingress" {
  for_each          = local.events
  name              = "/aws/lambda/${var.events_name}-ingress"
  retention_in_days = var.log_retention_days
  tags              = merge(var.tags, { Component = "slack-events-ingress" })
}

resource "aws_cloudwatch_log_group" "events_worker" {
  for_each          = local.events
  name              = "/aws/lambda/${var.events_name}-worker"
  retention_in_days = var.log_retention_days
  tags              = merge(var.tags, { Component = "slack-events-worker" })
}

resource "aws_iam_role" "lambda" {
  name               = "${var.name}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  tags               = local.common_tags
}

resource "aws_iam_role" "events_ingress" {
  for_each           = local.events
  name               = "${var.events_name}-ingress"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  tags               = merge(var.tags, { Component = "slack-events-ingress" })
}

resource "aws_iam_role" "events_worker" {
  for_each           = local.events
  name               = "${var.events_name}-worker"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  tags               = merge(var.tags, { Component = "slack-events-worker" })
}

# Narrowly scoped: reads and writes only the per-agent binding/credentials
# pair under the agents hierarchy. It cannot read the Slack provisioner
# configuration token (`/agent-core/slack/provisioner/config`) or any other
# SSM parameter outside this prefix.
resource "aws_iam_role_policy" "lambda" {
  name = "slack-oauth-callback"
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.lambda.arn}:*"
      },
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = ["${local.agent_parameter_arn_prefix}/*/binding", "${local.agent_parameter_arn_prefix}/*/credentials"]
      },
      {
        Effect   = "Allow"
        Action   = ["ssm:PutParameter"]
        Resource = ["${local.agent_parameter_arn_prefix}/*/binding", "${local.agent_parameter_arn_prefix}/*/credentials"]
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"]
        Resource = data.aws_kms_alias.ssm.target_key_arn
      },
    ]
  })
}

# The ingress decrypts the per-agent credentials parameter to read only its
# signing secret, verifies the Slack request, and sends accepted work to the
# queue. The combined parameter also contains bot/client secrets, an existing
# SSM schema limitation; ingress code must never read or log those fields.
# It gets no Harness or DynamoDB access.
resource "aws_iam_role_policy" "events_ingress" {
  for_each = local.events
  name     = "slack-events-ingress"
  role     = aws_iam_role.events_ingress[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.events_ingress[each.key].arn}:*"
      },
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = local.event_agent_parameter_arns
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = data.aws_kms_alias.ssm.target_key_arn
      },
      {
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = aws_sqs_queue.events[each.key].arn
      },
    ]
  })
}

# The worker is the only asynchronous consumer. It may decrypt the same
# app's bot/signing credentials, persist pseudonymous event/thread/session
# state, and invoke the one configured Harness.
resource "aws_iam_role_policy" "events_worker" {
  for_each = local.events
  name     = "slack-events-worker"
  role     = aws_iam_role.events_worker[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.events_worker[each.key].arn}:*"
      },
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = local.event_agent_parameter_arns
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = data.aws_kms_alias.ssm.target_key_arn
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:DeleteItem",
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
        ]
        Resource = aws_dynamodb_table.events_state[each.key].arn
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:ChangeMessageVisibility",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:ReceiveMessage",
        ]
        Resource = aws_sqs_queue.events[each.key].arn
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:InvokeAgentRuntime",
          "bedrock-agentcore:InvokeHarness",
        ]
        Resource = [for agent in values(var.slack_agents) : agent.harness_arn]
      },
    ]
  })
}

resource "aws_lambda_function" "callback" {
  function_name = var.name
  role          = aws_iam_role.lambda.arn
  package_type  = "Image"
  image_uri     = var.image_uri
  architectures = ["arm64"]
  timeout       = 10
  memory_size   = 128
  environment {
    variables = {
      SLACK_WORKSPACE_ID           = var.slack_workspace_id
      SLACK_OAUTH_REDIRECT_URI     = local.redirect_uri
      SLACK_AGENT_PARAMETER_PREFIX = var.agent_parameter_prefix
      LOG_LEVEL                    = "INFO"
    }
  }
  depends_on = [aws_iam_role_policy.lambda, aws_cloudwatch_log_group.lambda]
  tags       = local.common_tags
}

resource "aws_lambda_function" "events_ingress" {
  for_each      = local.events
  function_name = "${var.events_name}-ingress"
  role          = aws_iam_role.events_ingress[each.key].arn
  package_type  = "Image"
  image_uri     = var.events_image_uri
  architectures = ["arm64"]
  timeout       = 10
  memory_size   = 256

  image_config {
    command = ["slack_events.ingress.lambda_handler"]
  }

  environment {
    variables = {
      LOG_LEVEL                    = "INFO"
      SLACK_AGENT_PARAMETER_PREFIX = var.agent_parameter_prefix
      SLACK_EVENT_QUEUE_URL        = aws_sqs_queue.events[each.key].url
    }
  }

  depends_on = [aws_iam_role_policy.events_ingress, aws_cloudwatch_log_group.events_ingress]
  tags       = merge(var.tags, { Component = "slack-events-ingress" })
}

resource "aws_lambda_function" "events_worker" {
  for_each      = local.events
  function_name = "${var.events_name}-worker"
  role          = aws_iam_role.events_worker[each.key].arn
  package_type  = "Image"
  image_uri     = var.events_image_uri
  architectures = ["arm64"]
  timeout       = var.events_worker_timeout_seconds
  memory_size   = 512

  image_config {
    command = ["slack_events.worker.lambda_handler"]
  }

  environment {
    variables = {
      LOG_LEVEL                    = "INFO"
      SLACK_AGENT_HARNESSES        = jsonencode({ for agent_name, agent in var.slack_agents : agent_name => agent.harness_arn })
      SLACK_AGENT_PARAMETER_PREFIX = var.agent_parameter_prefix
      SLACK_EVENT_STATE_TABLE      = aws_dynamodb_table.events_state[each.key].name
    }
  }

  depends_on = [aws_iam_role_policy.events_worker, aws_cloudwatch_log_group.events_worker]
  tags       = merge(var.tags, { Component = "slack-events-worker" })
}

resource "aws_sqs_queue" "events_dead_letter" {
  for_each                  = local.events
  name                      = "${var.events_name}-dead-letter.fifo"
  message_retention_seconds = 1209600
  fifo_queue                = true
  sqs_managed_sse_enabled   = true
  tags                      = merge(var.tags, { Component = "slack-events-dead-letter" })
}

resource "aws_sqs_queue" "events" {
  for_each                    = local.events
  name                        = "${var.events_name}.fifo"
  fifo_queue                  = true
  content_based_deduplication = false
  receive_wait_time_seconds   = 20
  visibility_timeout_seconds  = var.events_worker_timeout_seconds * 6
  sqs_managed_sse_enabled     = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.events_dead_letter[each.key].arn
    maxReceiveCount     = 3
  })
  tags = merge(var.tags, { Component = "slack-events" })
}

# The service stores only pseudonymous event/thread/session keys. Completed and
# abandoned event claims expire by TTL; thread and active-session records are
# durable until an explicit lifecycle policy is added.
resource "aws_dynamodb_table" "events_state" {
  for_each     = local.events
  name         = "${var.events_name}-state"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  tags = merge(var.tags, { Component = "slack-events-state" })
}

resource "aws_lambda_event_source_mapping" "events_worker" {
  for_each         = local.events
  event_source_arn = aws_sqs_queue.events[each.key].arn
  function_name    = aws_lambda_function.events_worker[each.key].arn
  batch_size       = 1
  enabled          = true
}

resource "aws_apigatewayv2_api" "this" {
  name          = var.name
  protocol_type = "HTTP"
  tags          = local.common_tags
}

resource "aws_apigatewayv2_integration" "callback" {
  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.callback.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_integration" "events_ingress" {
  for_each               = local.events
  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.events_ingress[each.key].invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "callback" {
  api_id    = aws_apigatewayv2_api.this.id
  route_key = "GET /slack/oauth/callback"
  target    = "integrations/${aws_apigatewayv2_integration.callback.id}"
}

resource "aws_apigatewayv2_route" "events" {
  for_each  = local.events_enabled ? var.slack_agents : {}
  api_id    = aws_apigatewayv2_api.this.id
  route_key = "POST /slack/events/${each.key}"
  target    = "integrations/${aws_apigatewayv2_integration.events_ingress["enabled"].id}"
}

# $default with auto_deploy publishes whenever the route/integration change;
# this must not depend_on the route/integration, or it would form a cycle
# with the Lambda -> stage.invoke_url -> redirect_uri env-var dependency
# above.
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.access.arn
    # No query string or body field: the authorization code and state token
    # never reach CloudWatch through access logging.
    format = jsonencode({
      requestId        = "$context.requestId"
      ip               = "$context.identity.sourceIp"
      requestTime      = "$context.requestTime"
      httpMethod       = "$context.httpMethod"
      routeKey         = "$context.routeKey"
      status           = "$context.status"
      protocol         = "$context.protocol"
      responseLength   = "$context.responseLength"
      integrationError = "$context.integrationErrorMessage"
    })
  }

  tags = local.common_tags
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "ApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.callback.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/GET/slack/oauth/callback"

  # Deleting a function deletes its resource-based policy, but function_name
  # is unchanged by a replacement, so Terraform would otherwise see no diff
  # and leave API Gateway unable to invoke the new function.
  lifecycle {
    replace_triggered_by = [aws_lambda_function.callback]
  }
}

resource "aws_lambda_permission" "events_ingress" {
  for_each      = local.events_enabled ? var.slack_agents : {}
  statement_id  = "ApiGatewayInvokeSlackEvents${replace(title(each.key), "-", "")}"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.events_ingress["enabled"].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/POST/slack/events/${each.key}"

  lifecycle {
    replace_triggered_by = [aws_lambda_function.events_ingress["enabled"]]
  }
}
