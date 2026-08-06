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

variable "slack_agent_names" {
  description = "Manifest-derived names of Slack-enabled agents. Environment bindings remain in SSM; Harness ARNs come from the corresponding manifest-owned remote states."
  type        = set(string)
  default     = []

  validation {
    condition = alltrue([
      for agent_name in var.slack_agent_names : can(regex("^[a-z][a-z0-9-]{0,38}[a-z0-9]$", agent_name))
    ])
    error_message = "slack_agent_names must contain lowercase DNS-style manifest identities."
  }
}

variable "agent_state" {
  description = "Remote-state location for manifest-owned agent states. Keys are derived as agents/<name>/terraform.tfstate."
  type = object({
    bucket = string
    region = string
  })

  validation {
    condition     = var.agent_state.bucket != "" && can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]+$", var.agent_state.region))
    error_message = "agent_state requires a non-empty bucket and AWS region."
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
