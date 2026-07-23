variable "name" {
  description = "Gateway name. It remains independent from a future OpenAPI target."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,38}[a-z0-9]$", var.name))
    error_message = "name must be a lowercase DNS-style name between 2 and 40 characters."
  }
}

variable "description" {
  description = "Human-readable description used by the Gateway and tags."
  type        = string
  default     = ""
}

variable "tags" {
  description = "Additional tags applied to the Gateway and its service role."
  type        = map(string)
  default     = {}
}

variable "github_oauth_provider_arn" {
  description = "Non-secret ARN of the existing GitHub OAuth credential provider."
  type        = string

  validation {
    condition     = can(regex("^arn:[^:]+:bedrock-agentcore:[^:]+:[0-9]{12}:token-vault/.+/oauth2credentialprovider/.+$", var.github_oauth_provider_arn))
    error_message = "github_oauth_provider_arn must be an AgentCore OAuth2 credential-provider ARN."
  }
}

variable "github_oauth_client_secret_arn" {
  description = "Non-secret ARN of the GitHub OAuth client secret managed by AgentCore."
  type        = string

  validation {
    condition     = can(regex("^arn:[^:]+:secretsmanager:[^:]+:[0-9]{12}:secret:.+$", var.github_oauth_client_secret_arn))
    error_message = "github_oauth_client_secret_arn must be a Secrets Manager secret ARN."
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

variable "github_openapi_payload" {
  description = "Frozen GitHub GET /user OpenAPI contract, resolved by Terragrunt outside the module cache."
  type        = string

  validation {
    condition     = can(regex("(?s)^.*https://api\\.github\\.com.*?/user.*?getAuthenticatedUser.*$", var.github_openapi_payload))
    error_message = "github_openapi_payload must contain the frozen GitHub GET /user operation."
  }
}
