#!/bin/sh
# Links repository-owned mise plugins without loading this repository's mise.toml.
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

mise plugins link --force --cd /private/tmp \
  aws-ssm "$repo_root/extensions/mise-aws-ssm"
