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

variable "github_gateway_arn" {
  description = "Non-secret ARN of the reviewed GitHub current-user Gateway, supplied after its deployment."
  type        = string

  validation {
    condition     = can(regex("^arn:[^:]+:bedrock-agentcore:[^:]+:[0-9]{12}:gateway/.+$", var.github_gateway_arn))
    error_message = "github_gateway_arn must be an AgentCore Gateway ARN."
  }
}

variable "github_oauth_provider_arn" {
  description = "Non-secret ARN of the shared GitHub OAuth credential provider."
  type        = string

  validation {
    condition     = can(regex("^arn:[^:]+:bedrock-agentcore:[^:]+:[0-9]{12}:token-vault/.+/oauth2credentialprovider/.+$", var.github_oauth_provider_arn))
    error_message = "github_oauth_provider_arn must be an AgentCore OAuth2 credential-provider ARN."
  }
}

variable "github_client_secret_arn" {
  description = "Non-secret ARN of the GitHub OAuth client secret managed by AgentCore."
  type        = string

  validation {
    condition     = can(regex("^arn:[^:]+:secretsmanager:[^:]+:[0-9]{12}:secret:.+$", var.github_client_secret_arn))
    error_message = "github_client_secret_arn must be a Secrets Manager secret ARN."
  }
}

variable "github_post_consent_return_url" {
  description = "Required non-secret HTTPS URL used after GitHub authorization-code consent."
  type        = string

  validation {
    condition = (
      can(regex("^https://[^[:space:]]+$", var.github_post_consent_return_url)) &&
      !can(regex("^https://[^/?#]*@", var.github_post_consent_return_url)) &&
      !can(regex("(?i)(?:[?&]|#)[^=&#]*(?:token|code|secret|password|credential|key)[^=&#]*(?:=|&|#|$)", var.github_post_consent_return_url)) &&
      !can(regex("(?i)(?:[?&]|#)[^=&#]*=[^&#]*(?:token|code|secret|password|credential|key)[^&#]*", var.github_post_consent_return_url))
    )
    error_message = "github_post_consent_return_url must be HTTPS, contain no userinfo, and contain no sensitive query or fragment key/value."
  }
}
