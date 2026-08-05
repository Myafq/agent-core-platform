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

variable "agent_parameter_prefix" {
  description = "SSM parameter prefix owning per-agent Slack binding/credentials. Must match clients/slack/reconciliation.py and clients/slack/launcher.py."
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

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "tags" {
  type    = map(string)
  default = {}
}
