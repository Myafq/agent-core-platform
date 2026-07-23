variable "name" {
  description = "Name of the shared AgentCore OAuth credential provider."
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

variable "tags" {
  type    = map(string)
  default = {}
}
