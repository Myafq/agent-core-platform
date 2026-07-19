locals {
  aws_region = get_env("AWS_REGION", "us-east-1")
}

generate "provider" {
  path      = "provider.generated.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<-EOF
    provider "aws" {
      region = "${local.aws_region}"

      default_tags {
        tags = {
          Environment = "${get_env("ENVIRONMENT", "dev")}"
          ManagedBy   = "Terraform"
          Project     = "agentcore-yaml-lab"
        }
      }
    }
  EOF
}

