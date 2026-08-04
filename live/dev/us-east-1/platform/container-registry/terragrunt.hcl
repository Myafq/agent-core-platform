include "root" { path = find_in_parent_folders("root.hcl") }

terraform { source = "../../../../../modules/container-registry" }

locals {
  # containers/manifest.json is the single source of truth for buildable
  # images. Exclude harness-coding's repository: modules/github-app-tool
  # already owns aws_ecr_repository.harness_coding (github-app-tool-coding)
  # and migrating it here is deliberately deferred (constraint: do not
  # move/rename/destroy that repository; Harness v20 pins an immutable digest
  # inside it). Filter by repository name so adding unrelated manifest
  # entries never accidentally reintroduces that repository here.
  manifest               = jsondecode(file("${get_terragrunt_dir()}/../../../../../containers/manifest.json"))
  harness_coding_managed = "github-app-tool-coding"
  repositories           = toset([for c in local.manifest.containers : c.repository if c.repository != local.harness_coding_managed])
}

inputs = {
  repositories = local.repositories
  tags         = { Component = "container-registry" }
}
