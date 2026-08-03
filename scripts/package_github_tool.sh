#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
build_dir="$(mktemp -d "${TMPDIR:-/tmp}/github-tool.XXXXXX")"
output_path="${root_dir}/.build/github-tool-python311-manylinux.zip"

trap 'rm -rf "${build_dir}"' EXIT
mkdir -p "${root_dir}/.build"
rm -f "${output_path}"

"${root_dir}/.venv/bin/pip" install \
  --quiet \
  --target "${build_dir}" \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version 311 \
  --only-binary=:all: \
  -r "${root_dir}/services/github_tool/requirements.txt"

cp -R "${root_dir}/services" "${root_dir}/contracts" "${root_dir}/schemas" "${build_dir}/"
find "${build_dir}" -type d -name '__pycache__' -prune -exec rm -rf {} +
(cd "${build_dir}" && zip -qr "${output_path}" .)
echo "Done!"