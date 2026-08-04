variable "name" {
  description = "Logical agent name. Hyphens are converted to underscores for Harness."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,38}[a-z0-9]$", var.name))
    error_message = "name must be a lowercase DNS-style name between 2 and 40 characters."
  }
}

variable "description" {
  description = "Human-readable description used in tags."
  type        = string
  default     = ""
}

variable "model_id" {
  description = "Amazon Bedrock model identifier."
  type        = string
}

variable "api_format" {
  description = "API format used to invoke the Bedrock model."
  type        = string
  default     = "converse_stream"

  validation {
    condition     = contains(["converse_stream", "responses", "chat_completions"], var.api_format)
    error_message = "api_format must be converse_stream, responses, or chat_completions."
  }
}

variable "temperature" {
  type    = number
  default = 0.2
}

variable "top_p" {
  type     = number
  default  = null
  nullable = true
}

variable "system_prompt" {
  description = "Resolved system prompt text."
  type        = string
  sensitive   = true
}

variable "max_iterations" {
  type = number
}

variable "max_tokens" {
  type = number
}

variable "timeout_seconds" {
  type = number
}

variable "gateway_arn" {
  description = "Optional single AgentCore Gateway ARN serving the reviewed GitHub read tools."
  type        = string
  default     = null
  nullable    = true
}

variable "github_credential_broker_function_arn" {
  description = "Optional broker Lambda the Harness may invoke to mint temporary GitHub App credentials."
  type        = string
  default     = null
  nullable    = true
}

variable "container_uri" {
  description = "Optional immutable ARM64 ECR image for the Harness execution environment."
  type        = string
  default     = null
  nullable    = true
}

variable "container_repository_arn" {
  description = "Private ECR repository ARN from which the Harness may pull container_uri."
  type        = string
  default     = null
  nullable    = true
}

variable "session_storage_mount_path" {
  description = "Absolute path under /mnt for per-session managed coding storage."
  type        = string
  default     = "/mnt/workspace"

  validation {
    condition     = can(regex("^/mnt/[^/]+$", var.session_storage_mount_path))
    error_message = "session_storage_mount_path must be directly under /mnt."
  }
}

variable "tags" {
  type    = map(string)
  default = {}
}
