variable "REGISTRY" {
  default = "local"
}

variable "TAG" {
  default = "dev"
}

group "default" {
  targets = ["github-tool", "slack-oauth-callback", "slack-events", "harness-coding"]
}

target "github-tool" {
  context    = "."
  dockerfile = "containers/github-tool/Dockerfile"
  platforms  = ["linux/arm64"]
  tags       = ["${REGISTRY}/github-tool:${TAG}"]
}

target "slack-oauth-callback" {
  context    = "."
  dockerfile = "containers/slack-oauth-callback/Dockerfile"
  platforms  = ["linux/arm64"]
  tags       = ["${REGISTRY}/slack-oauth-callback:${TAG}"]
}

target "slack-events" {
  context    = "."
  dockerfile = "containers/slack-events/Dockerfile"
  platforms  = ["linux/arm64"]
  tags       = ["${REGISTRY}/slack-events:${TAG}"]
}

target "harness-coding" {
  context    = "containers/harness-coding"
  dockerfile = "containers/harness-coding/Dockerfile"
  platforms  = ["linux/arm64"]
  tags       = ["${REGISTRY}/github-app-tool-coding:${TAG}"]
}
