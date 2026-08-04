# Public HTTPS ingress for GET /slack/oauth/callback only. Socket Mode still
# owns every runtime Slack event; this Lambda exists solely to complete an
# app installation after a human approves it and to persist the result into
# the same per-agent SSM hierarchy `clients/slack/reconciliation.py` and
# `clients/slack/launcher.py` already own. No other public route is created.

locals {
  common_tags                = merge(var.tags, { Component = "slack-oauth-callback" })
  agent_parameter_arn_prefix = "arn:aws:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:parameter${var.agent_parameter_prefix}"
  redirect_uri               = "${trimsuffix(aws_apigatewayv2_stage.default.invoke_url, "/")}/slack/oauth/callback"
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

resource "aws_iam_role" "lambda" {
  name               = "${var.name}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  tags               = local.common_tags
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

resource "aws_lambda_function" "callback" {
  function_name    = var.name
  role             = aws_iam_role.lambda.arn
  handler          = "services.slack_oauth_callback.handler.lambda_handler"
  runtime          = "python3.11"
  architectures    = ["x86_64"]
  timeout          = 10
  memory_size      = 128
  filename         = var.lambda_package_path
  source_code_hash = filebase64sha256(var.lambda_package_path)
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

resource "aws_apigatewayv2_route" "callback" {
  api_id    = aws_apigatewayv2_api.this.id
  route_key = "GET /slack/oauth/callback"
  target    = "integrations/${aws_apigatewayv2_integration.callback.id}"
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
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/*"
}
