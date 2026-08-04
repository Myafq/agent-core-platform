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

variable "lambda_package_path" {
  description = "Path to the zipped services/slack_oauth_callback deployment package."
  type        = string
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "tags" {
  type    = map(string)
  default = {}
}
