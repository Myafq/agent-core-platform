variable "repositories" {
  description = "Repository names to create. Does not include harness_coding, which modules/github-app-tool owns."
  type        = set(string)
  default     = []
}

variable "tags" {
  type    = map(string)
  default = {}
}
