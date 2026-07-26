locals {
  common_tags = merge(var.tags, { Component = "github-app-tool" })
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

data "aws_iam_policy_document" "gateway_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }
  }
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.name}"
  retention_in_days = 30
  tags              = local.common_tags
}

resource "aws_iam_role" "lambda" {
  name               = "${var.name}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  tags               = local.common_tags
}

resource "aws_iam_role_policy" "lambda" {
  name = "github-app-read"
  role = aws_iam_role.lambda.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.lambda.arn}:*" },
    { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = var.github_app_private_key_secret_arn },
  ] })
}

resource "aws_lambda_function" "broker" {
  function_name    = var.name
  role             = aws_iam_role.lambda.arn
  handler          = "services.github_tool.handler.lambda_handler"
  runtime          = "python3.11"
  architectures    = ["x86_64"]
  timeout          = 15
  memory_size      = 256
  filename         = var.lambda_package_path
  source_code_hash = filebase64sha256(var.lambda_package_path)
  environment { variables = {
    GITHUB_APP_ID                     = var.github_app_id
    GITHUB_APP_INSTALLATION_ID        = var.github_app_installation_id
    GITHUB_APP_PRIVATE_KEY_SECRET_ARN = var.github_app_private_key_secret_arn
    GITHUB_APP_PRIVATE_KEY_SECRET_KEY = var.github_app_private_key_secret_key
  } }
  depends_on = [aws_iam_role_policy.lambda, aws_cloudwatch_log_group.lambda]
  tags       = local.common_tags
}

resource "aws_iam_role" "gateway" {
  name               = "${var.name}-gateway"
  assume_role_policy = data.aws_iam_policy_document.gateway_assume.json
  tags               = local.common_tags
}

resource "aws_iam_role_policy" "gateway" {
  name   = "invoke-github-read-lambda"
  role   = aws_iam_role.gateway.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = aws_lambda_function.broker.arn }] })
}

resource "aws_bedrockagentcore_gateway" "this" {
  name            = var.name
  protocol_type   = "MCP"
  authorizer_type = "AWS_IAM"
  role_arn        = aws_iam_role.gateway.arn
  tags            = local.common_tags
}

resource "aws_lambda_permission" "gateway" {
  statement_id  = "AgentCoreGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.broker.function_name
  principal     = "bedrock-agentcore.amazonaws.com"
  source_arn    = aws_bedrockagentcore_gateway.this.gateway_arn
}

resource "aws_bedrockagentcore_gateway_target" "get_repository" {
  name               = "github-get-repository"
  gateway_identifier = aws_bedrockagentcore_gateway.this.gateway_id
  credential_provider_configuration {
    gateway_iam_role {}
  }
  target_configuration {
    mcp {
      lambda {
        lambda_arn = aws_lambda_function.broker.arn
        tool_schema {
          inline_payload {
            name        = "getRepository"
            description = "Read one configured GitHub repository."
            input_schema {
              type = "object"
              property {
                name     = "owner"
                type     = "string"
                required = true
              }
              property {
                name     = "repo"
                type     = "string"
                required = true
              }
            }
          }
        }
      }
    }
  }
  depends_on = [aws_iam_role_policy.gateway, aws_lambda_permission.gateway]
}

resource "aws_bedrockagentcore_gateway_target" "list_repositories" {
  name               = "github-list-repositories"
  gateway_identifier = aws_bedrockagentcore_gateway.this.gateway_id
  credential_provider_configuration {
    gateway_iam_role {}
  }
  target_configuration {
    mcp {
      lambda {
        lambda_arn = aws_lambda_function.broker.arn
        tool_schema {
          inline_payload {
            name        = "listRepositories"
            description = "List the repositories configured for this GitHub App installation."
            input_schema {
              type = "object"
              property {
                name = "page"
                type = "integer"
              }
            }
          }
        }
      }
    }
  }
  depends_on = [aws_iam_role_policy.gateway, aws_lambda_permission.gateway]
}

resource "aws_bedrockagentcore_gateway_target" "get_file" {
  name               = "github-get-file"
  gateway_identifier = aws_bedrockagentcore_gateway.this.gateway_id
  credential_provider_configuration {
    gateway_iam_role {}
  }
  target_configuration {
    mcp {
      lambda {
        lambda_arn = aws_lambda_function.broker.arn
        tool_schema {
          inline_payload {
            name        = "getFile"
            description = "Read one small text file from a configured GitHub repository."
            input_schema {
              type = "object"
              property {
                name     = "owner"
                type     = "string"
                required = true
              }
              property {
                name     = "repo"
                type     = "string"
                required = true
              }
              property {
                name     = "path"
                type     = "string"
                required = true
              }
              property {
                name = "ref"
                type = "string"
              }
            }
          }
        }
      }
    }
  }
  depends_on = [aws_iam_role_policy.gateway, aws_lambda_permission.gateway]
}
