#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
build_dir="$(mktemp -d "${TMPDIR:-/tmp}/slack-oauth-callback.XXXXXX")"
output_path="${root_dir}/.build/slack-oauth-callback.zip"

trap 'rm -rf "${build_dir}"' EXIT
mkdir -p "${root_dir}/.build" "${build_dir}/services" "${build_dir}/contracts"
rm -f "${output_path}"

# Only the service's own code plus the shared state-signing module it
# imports -- no boto3 (Lambda-provided), no PyYAML/slack_sdk/other
# client-only dependencies from the rest of the repo.
cp "${root_dir}/services/__init__.py" "${build_dir}/services/"
cp -R "${root_dir}/services/slack_oauth_callback" "${build_dir}/services/"
cp "${root_dir}/contracts/slack_oauth_state.py" "${build_dir}/contracts/"

find "${build_dir}" -type d -name '__pycache__' -prune -exec rm -rf {} +
(cd "${build_dir}" && zip -qr "${output_path}" .)
echo "Done!"
