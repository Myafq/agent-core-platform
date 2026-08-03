#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repository_uri="$1"
image_tag="$2"
region="${AWS_REGION:-us-east-1}"

aws ecr get-login-password --region "${region}" | docker login --username AWS --password-stdin "${repository_uri%%/*}"
docker buildx build --platform linux/arm64 --provenance=false --push \
  --tag "${repository_uri}:${image_tag}" \
  "${root_dir}/containers/harness-coding"
