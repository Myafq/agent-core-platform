locals {
  harness_name                = replace(var.name, "-", "_")
  harness_memory_arn          = "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:memory/harness_${local.harness_name}_*"
  is_us_inference_profile     = startswith(var.model_id, "us.")
  is_global_inference_profile = startswith(var.model_id, "global.")
  is_inference_profile        = local.is_us_inference_profile || local.is_global_inference_profile
  foundation_model_id         = local.is_inference_profile ? join(".", slice(split(".", var.model_id), 1, length(split(".", var.model_id)))) : var.model_id
  bedrock_model_arns = local.is_us_inference_profile ? [
    for region in ["us-east-1", "us-east-2", "us-west-2"] :
    "arn:${data.aws_partition.current.partition}:bedrock:${region}::foundation-model/${local.foundation_model_id}"
    ] : local.is_global_inference_profile ? [
    "arn:${data.aws_partition.current.partition}:bedrock:*::foundation-model/${local.foundation_model_id}",
    "arn:${data.aws_partition.current.partition}:bedrock:${data.aws_region.current.region}::foundation-model/${local.foundation_model_id}",
  ] : ["arn:${data.aws_partition.current.partition}:bedrock:${data.aws_region.current.region}::foundation-model/${var.model_id}"]
  bedrock_inference_profile_arn = local.is_inference_profile ? "arn:${data.aws_partition.current.partition}:bedrock:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:inference-profile/${var.model_id}" : null
  bedrock_invocation_resources  = concat(local.bedrock_model_arns, local.bedrock_inference_profile_arn == null ? [] : [local.bedrock_inference_profile_arn])
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
    sid       = "InvokeConfiguredBedrockModelStream"
    actions   = ["bedrock:InvokeModelWithResponseStream"]
    resources = local.bedrock_invocation_resources
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

  dynamic "statement" {
    for_each = var.gateway_arn == null ? [] : [var.gateway_arn]

    content {
      sid       = "InvokeGitHubReadGateway"
      actions   = ["bedrock-agentcore:InvokeGateway"]
      resources = [statement.value]
    }
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

  # AgentCore requires a non-empty allow-list. Without the reviewed Gateway,
  # default shell and file tools remain disabled.
  allowed_tools = var.gateway_arn == null ? ["@disabled"] : [
    "@github-read/listRepositories",
    "@github-read/getRepository",
    "@github-read/getFile",
  ]

  dynamic "tool" {
    for_each = var.gateway_arn == null ? [] : [var.gateway_arn]

    content {
      type = "agentcore_gateway"
      name = "github-read"

      config {
        agentcore_gateway {
          gateway_arn = tool.value

          outbound_auth {
            aws_iam = true
          }
        }
      }
    }
  }

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

# AWS provider 6.55 does not yet expose BedrockModelConfig.apiFormat. Apply the
# supported control-plane field after Terraform creates or changes the Harness.
resource "terraform_data" "model_api_format" {
  triggers_replace = {
    harness_arn = aws_bedrockagentcore_harness.this.arn
    model_id    = var.model_id
    api_format  = var.api_format
  }

  provisioner "local-exec" {
    command = "aws bedrock-agentcore-control update-harness --region '${data.aws_region.current.region}' --harness-id '${split("/", aws_bedrockagentcore_harness.this.arn)[1]}' --model '${jsonencode({ bedrockModelConfig = merge({ modelId = var.model_id, apiFormat = var.api_format, maxTokens = var.max_tokens, temperature = var.temperature }, var.top_p == null ? {} : { topP = var.top_p }) })}'"
  }
}
