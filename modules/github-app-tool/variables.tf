variable "name" { type = string }
variable "github_app_id" { type = string }
variable "github_app_installation_id" { type = string }
variable "github_app_private_key_secret_arn" { type = string }
variable "github_app_private_key_secret_key" { type = string }
variable "image_uri" {
  description = "Digest-pinned ECR image URI for the broker Lambda (package_type = Image)."
  type        = string

  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.image_uri))
    error_message = "image_uri must end in a full @sha256:<64 hex> image digest; a mutable tag or placeholder is not allowed."
  }
}
variable "tags" {
  type    = map(string)
  default = {}
}
