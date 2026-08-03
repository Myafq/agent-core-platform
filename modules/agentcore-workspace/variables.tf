variable "name" {
  description = "DNS-style workspace name used in resource names and tags."
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR for the isolated coding workspace VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "tags" {
  type    = map(string)
  default = {}
}
