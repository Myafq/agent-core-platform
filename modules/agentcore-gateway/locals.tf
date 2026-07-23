locals {
  gateway_workload_identity_arn   = "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default/workload-identity/${var.name}-*"
  workload_identity_directory_arn = "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default"

  common_tags = merge(var.tags, {
    Name        = var.name
    Description = var.description
  })
}
