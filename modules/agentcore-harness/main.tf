locals {
  harness_name = replace(var.name, "-", "_")
  common_tags = merge(var.tags, {
    Agent       = var.name
    Description = var.description
  })
}

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
