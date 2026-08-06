variable "name" {
  description = "Logical Lambda/API Gateway name."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,38}[a-z0-9]$", var.name))
    error_message = "name must be a lowercase DNS-style name between 2 and 40 characters."
  }
}

variable "slack_workspace_id" {
  description = "The single Slack workspace this callback accepts installations for."
  type        = string

  validation {
    condition     = can(regex("^T[A-Z0-9]+$", var.slack_workspace_id))
    error_message = "slack_workspace_id must be a Slack Team ID starting with T."
  }
}

variable "slack_agents" {
  description = "Exact per-agent route, Slack App/workspace, and Harness bindings. Empty keeps Events resources disabled until digest-pinned images are available."
  type = map(object({
    app_id       = string
    workspace_id = string
    harness_arn  = string
  }))
  default = {}

  validation {
    condition = alltrue([
      for agent_name, agent in var.slack_agents : can(regex("^[a-z][a-z0-9-]{0,38}[a-z0-9]$", agent_name)) && can(regex("^A[A-Z0-9]+$", agent.app_id)) && can(regex("^T[A-Z0-9]+$", agent.workspace_id)) && can(regex("^arn:[^:]+:bedrock-agentcore:[^:]+:[0-9]{12}:harness/.+$", agent.harness_arn))
    ])
    error_message = "slack_agents keys must be agent names with valid Slack App/workspace IDs and exact AgentCore Harness ARNs."
  }
}

variable "events_name" {
  description = "Logical SQS/DynamoDB name prefix for Slack Events processing."
  type        = string
  default     = "slack-events"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,38}[a-z0-9]$", var.events_name))
    error_message = "events_name must be a lowercase DNS-style name between 2 and 40 characters."
  }
}

variable "agent_parameter_prefix" {
  description = "SSM parameter prefix owning per-agent Slack binding/credentials. Must match Slack reconciliation and event services."
  type        = string
  default     = "/agent-core/slack/agents"
}

variable "image_uri" {
  description = "Digest-pinned ECR image URI for the callback Lambda (package_type = Image)."
  type        = string

  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.image_uri))
    error_message = "image_uri must end in a full @sha256:<64 hex> image digest; a mutable tag or placeholder is not allowed."
  }
}

variable "events_image_uri" {
  description = "Digest-pinned ARM64 ECR image URI for Slack Events ingress and worker handlers."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.events_image_uri == null || can(regex("@sha256:[0-9a-f]{64}$", var.events_image_uri))
    error_message = "events_image_uri must end in a full @sha256:<64 hex> image digest."
  }
}

variable "events_worker_timeout_seconds" {
  description = "Worker timeout; the queue visibility timeout is six times this value."
  type        = number
  default     = 180

  validation {
    condition     = var.events_worker_timeout_seconds >= 30 && var.events_worker_timeout_seconds <= 900
    error_message = "events_worker_timeout_seconds must be between 30 and 900."
  }
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "tags" {
  type    = map(string)
  default = {}
}
