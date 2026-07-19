locals {
  harness_name       = replace(var.name, "-", "_")
  foundation_model   = "arn:${data.aws_partition.current.partition}:bedrock:${data.aws_region.current.name}::foundation-model/${var.model_id}"
  harness_memory_arn = "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:memory/harness_${local.harness_name}_*"
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
  statement {
    sid = "InvokeConfiguredBedrockModel"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
    ]
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
    resources = ["arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*"]
  }

  statement {
    sid       = "CloudWatchLogsDescribeGroups"
    actions   = ["logs:DescribeLogGroups"]
    resources = ["arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:*"]
  }

  statement {
    sid = "CloudWatchLogsStream"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*"]
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
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default",
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default/workload-identity/harness_${local.harness_name}-*",
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
    resources = ["arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.name}:aws:browser/*"]
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
    resources = ["arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.name}:aws:code-interpreter/*"]
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
}
