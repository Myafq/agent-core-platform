locals {
  aws_region = get_env("AWS_REGION", "us-east-1")
}

remote_state {
  backend = "s3"

  config = {
    bucket       = "tf-state-803629127460-us-east-1-an"
    key          = "${path_relative_to_include()}/terraform.tfstate"
    region       = local.aws_region
    encrypt      = true
    use_lockfile = true
  }
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
