include "root" { path = find_in_parent_folders("root.hcl") }

terraform { source = "../../../../../modules/github-app-tool" }

inputs = {
  name                              = "github-app-tool"
  github_app_id                     = get_env("GITHUB_APP_ID")
  github_app_installation_id        = get_env("GITHUB_APP_INSTALLATION_ID")
  github_app_private_key_secret_arn = get_env("GITHUB_APP_PRIVATE_KEY_SECRET_ARN")
  github_app_private_key_secret_key = get_env("GITHUB_APP_PRIVATE_KEY_SECRET_KEY", "agent.pem")
  lambda_package_path               = "${get_terragrunt_dir()}/../../../../../.build/github-tool-python311-manylinux.zip"
  tags                              = { Component = "github-app-tool" }
}
