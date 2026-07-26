variable "name" { type = string }
variable "github_app_id" { type = string }
variable "github_app_installation_id" { type = string }
variable "github_app_private_key_secret_arn" { type = string }
variable "github_app_private_key_secret_key" { type = string }
variable "lambda_package_path" { type = string }
variable "tags" {
  type    = map(string)
  default = {}
}
