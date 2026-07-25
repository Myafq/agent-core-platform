terraform {
  required_version = "~> 1.15.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.55.0"
    }
  }
}

provider "aws" {
  region                      = "us-east-1"
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
}

resource "aws_bedrockagentcore_gateway" "fixture" {
  name            = "lambda-target-fixture"
  protocol_type   = "MCP"
  authorizer_type = "AWS_IAM"
  role_arn        = "arn:aws:iam::123456789012:role/gateway-fixture"
}

resource "aws_bedrockagentcore_gateway_target" "fixture" {
  name               = "github-read"
  gateway_identifier = aws_bedrockagentcore_gateway.fixture.gateway_id

  credential_provider_configuration {
    gateway_iam_role {}
  }

  target_configuration {
    mcp {
      lambda {
        lambda_arn = "arn:aws:lambda:us-east-1:123456789012:function:github-read"

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
}
