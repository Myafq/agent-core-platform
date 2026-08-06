# Generic entrypoint for the "agent" kind. The target manifest arrives at
# runtime via MANIFEST_TARGET (e.g. agents/github-assistant/agent.yaml,
# relative to the repo root). This layer alone reads the manifest, derives the
# backend key from the manifest's identity, configures providers, and
# translates domain vocabulary into plain typed composition inputs.

locals {
  repo_root = get_repo_root()

  # This entrypoint currently binds the dev/us-east-1 platform. Reject an
  # override instead of opening the same agent state with a different provider
  # region or environment tag. Supporting another environment/region requires
  # an explicit binding and a distinct state identity.
  supported_environment = "dev"
  supported_aws_region  = "us-east-1"
  requested_environment = get_env("ENVIRONMENT", local.supported_environment)
  requested_aws_region  = get_env("AWS_REGION", local.supported_aws_region)

  guard_environment = local.requested_environment == local.supported_environment ? "ok" : file("ERROR: ENVIRONMENT '${local.requested_environment}' is unsupported by entrypoints/agents. This binding is fixed to '${local.supported_environment}'; add an explicit environment binding and distinct state identity before provisioning elsewhere.")
  guard_aws_region  = local.requested_aws_region == local.supported_aws_region ? "ok" : file("ERROR: AWS_REGION '${local.requested_aws_region}' is unsupported by entrypoints/agents. This binding is fixed to '${local.supported_aws_region}'; add an explicit regional binding and distinct state identity before provisioning elsewhere.")

  environment = local.guard_environment == "ok" ? local.supported_environment : ""
  aws_region  = local.guard_aws_region == "ok" ? local.supported_aws_region : ""

  manifest_target = get_env("MANIFEST_TARGET", "")

  # Guard chain. Each guard evaluates to "ok" or aborts with a clear message
  # via the conditional-file() idiom. Everything downstream (backend key,
  # manifest reads, inputs) depends on the guards, so a bad target fails
  # before any backend or provider is touched.
  guard_target_set = local.manifest_target != "" ? "ok" : file("ERROR: MANIFEST_TARGET is unset or empty. Set it to a manifest path relative to the repo root, e.g. MANIFEST_TARGET=agents/github-assistant/agent.yaml")

  # Anchored pattern confines the target to the repo agents/ tree: the <name>
  # segment allows only [a-z0-9-], which rejects "..", absolute paths, extra
  # path segments, and anything outside agents/.
  agent_path_pattern = "^agents/([a-z][a-z0-9-]{0,38}[a-z0-9])/agent\\.yaml$"

  guard_target_shape = local.guard_target_set == "ok" && can(regex(local.agent_path_pattern, local.manifest_target)) ? "ok" : file("ERROR: MANIFEST_TARGET '${local.manifest_target}' is invalid. It must match agents/<name>/agent.yaml inside the repo agents/ tree; absolute paths, '..', and paths outside agents/ are rejected.")

  agent_dir_name = local.guard_target_shape == "ok" ? regex(local.agent_path_pattern, local.manifest_target)[0] : ""

  manifest_directory = "${local.repo_root}/agents/${local.agent_dir_name}"
  manifest_path      = "${local.manifest_directory}/agent.yaml"

  # Path-shape checks are lexical. Resolve the manifest before reading it so a
  # symlinked agent directory cannot escape the canonical agents/<name> tree.
  # The repository validator then enforces the complete schema, including the
  # required inline prompt, during every Terragrunt configuration evaluation
  # before backend/provider initialization.
  guard_manifest_realpath = local.guard_target_shape == "ok" ? run_cmd(
    "--terragrunt-quiet",
    "${local.repo_root}/.venv/bin/python",
    "-c",
    "from pathlib import Path; import sys; actual = Path(sys.argv[1]).resolve(strict=True); expected = Path(sys.argv[2]).resolve() / 'agents' / sys.argv[3] / 'agent.yaml'; sys.exit(0 if actual == expected else 'ERROR: manifest path resolves outside its canonical agents/<name>/agent.yaml location')",
    local.manifest_path,
    local.repo_root,
    local.agent_dir_name,
  ) : ""

  manifest_validation = local.guard_manifest_realpath == "" ? run_cmd(
    "--terragrunt-quiet",
    "${local.repo_root}/.venv/bin/python",
    "${local.repo_root}/scripts/validate_spec.py",
    local.manifest_path,
  ) : ""

  manifest = yamldecode(file(local.manifest_validation != "" ? local.manifest_path : local.manifest_validation))

  guard_name_matches = local.manifest.metadata.name == local.agent_dir_name ? "ok" : file("ERROR: manifest metadata.name '${local.manifest.metadata.name}' does not match its directory name '${local.agent_dir_name}' (MANIFEST_TARGET '${local.manifest_target}'). Canonical agent identity is the manifest directory name; fix the manifest or move it.")

  agent_name = local.guard_name_matches == "ok" ? local.agent_dir_name : ""

  # spec.engine.container.image: optional digest-pinned private ECR URI.
  container_uri = try(local.manifest.spec.engine.container.image, null)

  container_uri_pattern = "^([0-9]{12})\\.dkr\\.ecr\\.([a-z0-9-]+)\\.amazonaws\\.com/([a-z0-9._/-]+)@(sha256:[0-9a-f]{64})$"

  guard_container_uri = local.container_uri == null ? "ok" : (can(regex(local.container_uri_pattern, local.container_uri)) ? "ok" : file("ERROR: spec.engine.container.image '${local.container_uri}' in ${local.manifest_path} must be a digest-pinned private ECR URI of the form <account>.dkr.ecr.<region>.amazonaws.com/<repository>@sha256:<digest>."))

  container_uri_parts      = local.guard_container_uri == "ok" && local.container_uri != null ? regex(local.container_uri_pattern, local.container_uri) : null
  container_repository_arn = local.container_uri_parts == null ? null : "arn:aws:ecr:${local.container_uri_parts[1]}:${local.container_uri_parts[0]}:repository/${local.container_uri_parts[2]}"

  # spec.tools.gateways: optional list of gateway names. Only github-app-tool
  # is known; anything else is a manifest error, not a silent no-op.
  requested_gateways = try(local.manifest.spec.tools.gateways, [])
  known_gateways     = ["github-app-tool"]
  unknown_gateways   = [for gateway in local.requested_gateways : gateway if !contains(local.known_gateways, gateway)]

  guard_gateways = length(local.unknown_gateways) == 0 ? "ok" : file("ERROR: spec.tools.gateways in ${local.manifest_path} names unknown gateway(s): ${join(", ", local.unknown_gateways)}. Known gateways: ${join(", ", local.known_gateways)}.")

  use_github_app_tool = local.guard_gateways == "ok" && contains(local.requested_gateways, "github-app-tool")
}

terraform {
  # The double slash vendors the repo tree into the per-target cache so the
  # composition's relative ../../modules references keep resolving there.
  source = "${get_repo_root()}//compositions/agents"
}

# One state per manifest, addressed by the manifest's own identity:
# agents/<name>/terraform.tfstate.
remote_state {
  backend = "s3"

  config = {
    bucket       = "tf-state-803629127460-us-east-1-an"
    key          = "agents/${local.agent_name}/terraform.tfstate"
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
          Environment = "${local.environment}"
          ManagedBy   = "Terraform"
          Project     = "agentcore-yaml-lab"
        }
      }
    }
  EOF
}

# Per-target cache isolation: one target must never reuse another target's
# initialized backend or provider artifacts.
download_dir = "${get_repo_root()}/.terragrunt-cache/agents/${local.agent_name}"

dependency "github_app_tool" {
  config_path = "${get_repo_root()}/live/${local.environment}/${local.aws_region}/platform/github-app-tool"
  enabled     = local.use_github_app_tool

  # Supports graph-wide validation and planning before the platform state has
  # the newly added broker outputs. Apply always reads real dependency state.
  mock_outputs_allowed_terraform_commands = ["validate", "plan"]
  mock_outputs_merge_strategy_with_state  = "shallow"
  mock_outputs = {
    gateway_arn                     = "arn:aws:bedrock-agentcore:us-east-1:803629127460:gateway/github-app-tool-nckdlx01xy"
    credential_broker_function_arn  = "arn:aws:lambda:us-east-1:803629127460:function:github-app-tool"
    credential_broker_function_name = "github-app-tool"
  }
}

inputs = {
  name                                  = local.manifest.metadata.name
  description                           = local.manifest.metadata.description
  tags                                  = merge(try(local.manifest.metadata.tags, {}), { Component = local.agent_name })
  model_id                              = local.manifest.spec.model.id
  api_format                            = try(local.manifest.spec.model.apiFormat, "converse_stream")
  temperature                           = try(local.manifest.spec.model.temperature, 0.2)
  top_p                                 = try(local.manifest.spec.model.topP, null)
  system_prompt                         = local.manifest.spec.instructions.system.text
  max_iterations                        = local.manifest.spec.limits.maxIterations
  max_tokens                            = local.manifest.spec.limits.maxTokens
  timeout_seconds                       = local.manifest.spec.limits.timeoutSeconds
  gateway_arn                           = local.use_github_app_tool ? dependency.github_app_tool.outputs.gateway_arn : null
  github_credential_broker_function_arn = local.use_github_app_tool ? dependency.github_app_tool.outputs.credential_broker_function_arn : null
  container_uri                         = local.container_uri
  container_repository_arn              = local.container_repository_arn
  session_storage_mount_path            = "/mnt/workspace"
}
