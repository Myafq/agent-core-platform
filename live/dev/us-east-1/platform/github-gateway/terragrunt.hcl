include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../../../../modules/agentcore-gateway"
}

dependency "github_oauth" {
  config_path = "../github-oauth"
}

inputs = {
  name        = "github-assistant-gateway"
  description = "Shared MCP Gateway for the GitHub current-user integration."
  tags = {
    Component = "github-gateway"
  }
  github_oauth_provider_arn      = dependency.github_oauth.outputs.credential_provider_arn
  github_oauth_client_secret_arn = dependency.github_oauth.outputs.client_secret_arn
  github_post_consent_return_url = get_env("GITHUB_POST_CONSENT_RETURN_URL")
  github_openapi_payload         = file("${get_terragrunt_dir()}/../../../../../contracts/github/openapi.yaml")
}
