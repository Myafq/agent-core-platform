data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

data "aws_region" "current" {}

data "aws_iam_policy_document" "assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values = [
        "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:gateway/${var.name}-*",
      ]
    }
  }
}

data "aws_iam_policy_document" "github_current_user" {
  statement {
    sid       = "GetGatewayWorkloadAccessToken"
    actions   = ["bedrock-agentcore:GetWorkloadAccessToken"]
    resources = [local.workload_identity_directory_arn, local.gateway_workload_identity_arn]
  }

  statement {
    sid       = "GetGitHubUserOauthToken"
    actions   = ["bedrock-agentcore:GetResourceOauth2Token"]
    resources = [var.github_oauth_provider_arn]
  }

  statement {
    sid       = "ReadGitHubOauthClientSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.github_oauth_client_secret_arn]
  }
}

resource "aws_iam_role" "this" {
  name               = "${var.name}-agentcore-gateway"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
  tags               = local.common_tags
}

resource "aws_bedrockagentcore_gateway" "this" {
  name            = var.name
  description     = var.description
  protocol_type   = "MCP"
  authorizer_type = "AWS_IAM"
  role_arn        = aws_iam_role.this.arn
  tags            = local.common_tags
}

resource "aws_iam_role_policy" "github_current_user" {
  name   = "github-current-user-oauth"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.github_current_user.json
}

resource "aws_bedrockagentcore_gateway_target" "github_current_user" {
  name               = "github-current-user"
  description        = "Read the authorizing GitHub user's public profile through GET /user only."
  gateway_identifier = aws_bedrockagentcore_gateway.this.gateway_id

  credential_provider_configuration {
    oauth {
      provider_arn       = var.github_oauth_provider_arn
      grant_type         = "AUTHORIZATION_CODE"
      default_return_url = var.github_post_consent_return_url
      scopes             = ["read:user"]
    }
  }

  target_configuration {
    mcp {
      open_api_schema {
        inline_payload {
          payload = var.github_openapi_payload
        }
      }
    }
  }

  depends_on = [aws_iam_role_policy.github_current_user]
}
