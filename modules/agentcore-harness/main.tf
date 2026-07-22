locals {
  harness_name       = replace(var.name, "-", "_")
  harness_memory_arn = "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:memory/harness_${local.harness_name}_*"
  common_tags = merge(var.tags, {
    Agent       = var.name
    Description = var.description
  })
}

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
  }
}

data "aws_iam_policy_document" "execution" {
  # Mantle model IDs are authorized through the service action and model
  # condition key rather than a foundation-model ARN resource.
  statement {
    sid       = "ReadBedrockMantleModelMetadata"
    actions   = ["bedrock-mantle:GetModel", "bedrock-mantle:GetProject"]
    resources = ["*"]
  }

  statement {
    sid       = "InvokeConfiguredBedrockMantleModel"
    actions   = ["bedrock-mantle:CreateInference"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "bedrock-mantle:Model"
      values   = [var.model_id]
    }
  }

  statement {
    sid       = "CallBedrockMantleWithBearerToken"
    actions   = ["bedrock-mantle:CallWithBearerToken"]
    resources = ["*"]
  }

  # Harness uses a managed public runtime image for every session.
  statement {
    sid       = "EcrPublicTokenAccess"
    actions   = ["ecr-public:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid       = "StsForEcrPublicPull"
    actions   = ["sts:GetServiceBearerToken"]
    resources = ["*"]
  }

  statement {
    sid = "XRayTracingAccess"
    actions = [
      "xray:PutTraceSegments",
      "xray:PutTelemetryRecords",
      "xray:GetSamplingRules",
      "xray:GetSamplingTargets",
    ]
    resources = ["*"]
  }

  statement {
    sid = "CloudWatchLogsGroup"
    actions = [
      "logs:CreateLogGroup",
      "logs:DescribeLogStreams",
    ]
    resources = ["arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*"]
  }

  statement {
    sid       = "CloudWatchLogsDescribeGroups"
    actions   = ["logs:DescribeLogGroups"]
    resources = ["arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:*"]
  }

  statement {
    sid = "CloudWatchLogsStream"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*"]
  }

  statement {
    sid       = "CloudWatchMetricsPublish"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["bedrock-agentcore"]
    }
  }

  # Every Harness owns a managed memory resource for session history.
  statement {
    sid = "HarnessManagedMemory"
    actions = [
      "bedrock-agentcore:CreateEvent",
      "bedrock-agentcore:DeleteEvent",
      "bedrock-agentcore:GetEvent",
      "bedrock-agentcore:ListEvents",
      "bedrock-agentcore:RetrieveMemoryRecords",
    ]
    resources = [local.harness_memory_arn]
  }

  # Default AgentCore tools and workload identity are available for future YAML
  # tool declarations. Gateway, OAuth, S3, and Git access remain opt-in.
  statement {
    sid = "AgentCoreWorkloadIdentity"
    actions = [
      "bedrock-agentcore:GetWorkloadAccessToken",
      "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
    ]
    resources = [
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default",
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default/workload-identity/harness_${local.harness_name}-*",
    ]
  }

  statement {
    sid = "AgentCoreBrowserDefault"
    actions = [
      "bedrock-agentcore:StartBrowserSession",
      "bedrock-agentcore:StopBrowserSession",
      "bedrock-agentcore:GetBrowserSession",
      "bedrock-agentcore:ListBrowserSessions",
      "bedrock-agentcore:UpdateBrowserStream",
      "bedrock-agentcore:ConnectBrowserAutomationStream",
      "bedrock-agentcore:ConnectBrowserLiveViewStream",
    ]
    resources = ["arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:aws:browser/*"]
  }

  statement {
    sid = "AgentCoreCodeInterpreterDefault"
    actions = [
      "bedrock-agentcore:StartCodeInterpreterSession",
      "bedrock-agentcore:StopCodeInterpreterSession",
      "bedrock-agentcore:GetCodeInterpreterSession",
      "bedrock-agentcore:ListCodeInterpreterSessions",
      "bedrock-agentcore:InvokeCodeInterpreter",
    ]
    resources = ["arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:aws:code-interpreter/*"]
  }
}

resource "aws_iam_role" "this" {
  name               = "${var.name}-agentcore-harness"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
  tags               = local.common_tags
}

resource "aws_iam_role_policy" "execution" {
  name   = "bedrock-model-invocation"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.execution.json
}

resource "aws_bedrockagentcore_harness" "this" {
  harness_name       = local.harness_name
  execution_role_arn = aws_iam_role.this.arn

  model {
    bedrock_model_config {
      model_id    = var.model_id
      temperature = var.temperature
      top_p       = var.top_p
    }
  }

  system_prompt {
    text = var.system_prompt
  }

  # InvokeHarness requires a non-empty allow-list when the field is supplied.
  # This unmatched sentinel prevents the default shell and filesystem tools from
  # becoming available before this lab explicitly adds governed tools.
  allowed_tools   = ["__no_tools_configured__"]
  max_iterations  = var.max_iterations
  max_tokens      = var.max_tokens
  timeout_seconds = var.timeout_seconds
  tags            = local.common_tags

  depends_on = [aws_iam_role_policy.execution]

  # The post-create control-plane update owns this field with apiFormat.
  lifecycle {
    ignore_changes = [model[0].bedrock_model_config[0].max_tokens]
  }
}

resource "aws_bedrockagentcore_oauth2_credential_provider" "github" {
  name                       = var.github_oauth_provider_name
  credential_provider_vendor = "GithubOauth2"
  tags                       = local.common_tags

  oauth2_provider_config {
    github_oauth2_provider_config {
      client_id_wo                  = var.github_client_id
      client_secret_wo              = var.github_client_secret
      client_credentials_wo_version = var.github_credentials_version
    }
  }
}

# AWS provider 6.55 does not yet expose BedrockModelConfig.apiFormat. Apply the
# supported control-plane field after Terraform creates or changes the Harness.
resource "terraform_data" "model_api_format" {
  triggers_replace = {
    harness_arn = aws_bedrockagentcore_harness.this.arn
    model_id    = var.model_id
    api_format  = var.api_format
  }

  provisioner "local-exec" {
    command = "aws bedrock-agentcore-control update-harness --region '${data.aws_region.current.region}' --harness-id '${split("/", aws_bedrockagentcore_harness.this.arn)[1]}' --model '${jsonencode({ bedrockModelConfig = { modelId = var.model_id, apiFormat = var.api_format, maxTokens = var.max_tokens, temperature = var.temperature, topP = var.top_p } })}'"
  }
}
