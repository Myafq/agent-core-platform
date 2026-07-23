locals {
  common_tags = merge(var.tags, {
    Description = var.description
  })
}

resource "aws_bedrockagentcore_oauth2_credential_provider" "github" {
  name                       = var.name
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
