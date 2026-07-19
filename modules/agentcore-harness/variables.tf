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

