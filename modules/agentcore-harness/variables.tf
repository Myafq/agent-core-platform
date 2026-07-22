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
  type    = number
  default = 0.9
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

variable "tags" {
  type    = map(string)
  default = {}
}

variable "github_oauth_provider_name" {
  description = "Name of the AgentCore GitHub OAuth credential provider."
  type        = string
  default     = "github-assistant-oauth"
}

variable "github_client_id" {
  description = "GitHub OAuth App client ID. Ephemeral; never stored in state."
  type        = string
  sensitive   = true
  ephemeral   = true
}

variable "github_client_secret" {
  description = "GitHub OAuth App client secret. Ephemeral; never stored in state."
  type        = string
  sensitive   = true
  ephemeral   = true
}

variable "github_credentials_version" {
  description = "Increase after rotating either GitHub OAuth App credential."
  type        = number
  default     = 1
}
