#!/usr/bin/env python3
"""Build and publish container images with source-digest change detection.

Replaces ``scripts/package_github_tool.sh`` and
``scripts/build_harness_coding_image.sh``. Reads ``containers/manifest.json``
(repo-root relative ``dockerfile``/``context``/``sources``) and, for each
container:

- computes a deterministic ``src-<12 hex>`` tag from the working-tree bytes of
  its tracked source files plus its build configuration (``dockerfile``,
  ``context``, ``platform``);
- can report whether that tag already exists in ECR (``plan``);
- can build (and optionally push) only the containers whose tag is new
  (``build``);
- can resolve each container's current tag to an immutable
  ``<registry>/<repository>@sha256:...`` URI for Terraform to consume
  (``digests``).

Every external call (``git``, ``docker``, ``aws``) goes through the injectable
``CommandRunner`` seam so this module can be unit tested without a network,
Docker, or AWS credentials. ECR repositories here use immutable tags, so
re-pushing an existing tag fails; ``plan``/skip exists to avoid ever trying.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Protocol, Sequence


REQUIRED_CONTAINER_FIELDS = frozenset(
    {"name", "repository", "dockerfile", "context", "platform", "kind", "sources"}
)
_ECR_MISSING_MARKERS = ("RepositoryNotFoundException", "ImageNotFoundException")
DEFAULT_REGION = "us-east-1"


class ContainersError(RuntimeError):
    """A safe, user-facing error for command-line output."""


# --------------------------------------------------------------------------
# Injectable command seam
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        input: str | None = None,
    ) -> CommandResult: ...


class SubprocessRunner:
    """Real runner used outside of tests."""

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        input: str | None = None,
    ) -> CommandResult:
        completed = subprocess.run(
            list(args),
            cwd=cwd,
            input=input,
            capture_output=True,
            text=True,
            check=False,
        )
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def run_or_raise(
    runner: CommandRunner,
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    input: str | None = None,
    error_prefix: str = "",
) -> str:
    result = runner.run(args, cwd=cwd, input=input)
    if result.returncode != 0:
        prefix = f"{error_prefix}: " if error_prefix else ""
        detail = result.stderr.strip() or result.stdout.strip() or f"exit status {result.returncode}"
        raise ContainersError(f"{prefix}{' '.join(args)} failed: {detail}")
    return result.stdout


# --------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ContainerSpec:
    name: str
    repository: str
    dockerfile: str
    context: str
    platform: str
    kind: str
    sources: tuple[str, ...]


@dataclass(frozen=True)
class Manifest:
    version: int
    containers: tuple[ContainerSpec, ...]

    def get(self, name: str) -> ContainerSpec:
        for container in self.containers:
            if container.name == name:
                return container
        known = ", ".join(container.name for container in self.containers) or "<none>"
        raise ContainersError(f"unknown container {name!r}; manifest defines: {known}")

    def select(self, names: Sequence[str]) -> tuple[ContainerSpec, ...]:
        if not names:
            return self.containers
        return tuple(self.get(name) for name in names)


def parse_manifest(raw: Any) -> Manifest:
    if not isinstance(raw, dict):
        raise ContainersError("manifest must be a JSON object")

    unknown_top = set(raw) - {"version", "containers"}
    if unknown_top:
        raise ContainersError(f"manifest has unknown top-level fields: {', '.join(sorted(unknown_top))}")
    missing_top = {"version", "containers"} - set(raw)
    if missing_top:
        raise ContainersError(f"manifest is missing required fields: {', '.join(sorted(missing_top))}")

    version = raw["version"]
    if not isinstance(version, int) or isinstance(version, bool) or version != 1:
        raise ContainersError(f"unsupported manifest version {version!r}; expected 1")

    raw_containers = raw["containers"]
    if not isinstance(raw_containers, list):
        raise ContainersError("manifest.containers must be a list")

    containers: list[ContainerSpec] = []
    seen_names: set[str] = set()
    for index, entry in enumerate(raw_containers):
        if not isinstance(entry, dict):
            raise ContainersError(f"containers[{index}] must be an object")

        unknown = set(entry) - REQUIRED_CONTAINER_FIELDS
        if unknown:
            raise ContainersError(f"containers[{index}] has unknown fields: {', '.join(sorted(unknown))}")
        missing = REQUIRED_CONTAINER_FIELDS - set(entry)
        if missing:
            raise ContainersError(f"containers[{index}] is missing required fields: {', '.join(sorted(missing))}")

        for field in ("name", "repository", "dockerfile", "context", "platform", "kind"):
            value = entry[field]
            if not isinstance(value, str) or not value:
                raise ContainersError(f"containers[{index}].{field} must be a non-empty string")

        sources = entry["sources"]
        if not isinstance(sources, list) or not sources or not all(isinstance(item, str) and item for item in sources):
            raise ContainersError(f"containers[{index}].sources must be a non-empty list of non-empty strings")

        name = entry["name"]
        if name in seen_names:
            raise ContainersError(f"duplicate container name: {name}")
        seen_names.add(name)

        containers.append(
            ContainerSpec(
                name=name,
                repository=entry["repository"],
                dockerfile=entry["dockerfile"],
                context=entry["context"],
                platform=entry["platform"],
                kind=entry["kind"],
                sources=tuple(sources),
            )
        )

    return Manifest(version=version, containers=tuple(containers))


def load_manifest(path: Path) -> Manifest:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ContainersError(f"manifest not found: {path}") from error
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as error:
        raise ContainersError(f"manifest is not valid JSON: {error}") from error
    return parse_manifest(raw)


# --------------------------------------------------------------------------
# Source digest / tag scheme
# --------------------------------------------------------------------------


def tracked_source_files(container: ContainerSpec, root: Path, runner: CommandRunner) -> list[str]:
    """Sorted, de-duplicated tracked files under the container's source prefixes."""
    result = runner.run(["git", "ls-files", "-z", "--", *container.sources], cwd=root)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ContainersError(f"{container.name}: git ls-files failed: {detail}")
    files = [path for path in result.stdout.split("\0") if path]
    return sorted(set(files))


def compute_source_digest(container: ContainerSpec, root: Path, runner: CommandRunner) -> str:
    """sha256 over sorted (path, content-hash) pairs, mixed with build config."""
    hasher = hashlib.sha256()
    paths = tracked_source_files(container, root, runner)
    if not paths:
        # Only tracked files are hashed. A container whose sources are all
        # untracked would otherwise get a stable tag over no source at all.
        raise ContainersError(
            f"{container.name}: no tracked files under {', '.join(container.sources)}; "
            "git add the container's sources before building"
        )
    for path in paths:
        file_path = root / path
        try:
            data = file_path.read_bytes()
        except OSError as error:
            raise ContainersError(
                f"{container.name}: tracked source file is missing from the working tree: {path}"
            ) from error
        content_hash = hashlib.sha256(data).hexdigest()
        hasher.update(path.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(content_hash.encode("ascii"))
        hasher.update(b"\n")

    for key, value in (
        ("dockerfile", container.dockerfile),
        ("context", container.context),
        ("platform", container.platform),
    ):
        hasher.update(key.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(value.encode("utf-8"))
        hasher.update(b"\n")

    return hasher.hexdigest()


def source_tag(container: ContainerSpec, root: Path, runner: CommandRunner) -> str:
    return "src-" + compute_source_digest(container, root, runner)[:12]


# --------------------------------------------------------------------------
# Registry / ECR
# --------------------------------------------------------------------------


def determine_region(args: argparse.Namespace, env: Mapping[str, str]) -> str:
    return args.region or env.get("AWS_REGION") or DEFAULT_REGION


def sts_account_id(runner: CommandRunner) -> str:
    stdout = run_or_raise(
        runner,
        ["aws", "sts", "get-caller-identity", "--output", "json"],
        error_prefix="aws sts get-caller-identity",
    )
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise ContainersError(f"aws sts get-caller-identity returned invalid JSON: {error}") from error
    account = data.get("Account")
    if not isinstance(account, str) or not account:
        raise ContainersError("aws sts get-caller-identity response is missing Account")
    return account


def resolve_registry(explicit: str | None, env: Mapping[str, str], runner: CommandRunner, region: str) -> str:
    if explicit:
        return explicit
    from_env = env.get("CONTAINER_REGISTRY")
    if from_env:
        return from_env
    account = sts_account_id(runner)
    return f"{account}.dkr.ecr.{region}.amazonaws.com"


def _describe_images(runner: CommandRunner, repository: str, tag: str, region: str) -> CommandResult:
    return runner.run(
        [
            "aws",
            "ecr",
            "describe-images",
            "--repository-name",
            repository,
            "--image-ids",
            f"imageTag={tag}",
            "--region",
            region,
            "--output",
            "json",
        ]
    )


def ecr_tag_exists(runner: CommandRunner, repository: str, tag: str, region: str) -> bool:
    result = _describe_images(runner, repository, tag, region)
    if result.returncode == 0:
        return True
    if any(marker in result.stderr for marker in _ECR_MISSING_MARKERS):
        return False
    detail = result.stderr.strip() or result.stdout.strip()
    raise ContainersError(f"aws ecr describe-images failed for {repository}:{tag}: {detail}")


def ecr_image_digest(runner: CommandRunner, repository: str, tag: str, region: str) -> str:
    result = _describe_images(runner, repository, tag, region)
    if result.returncode != 0:
        if any(marker in result.stderr for marker in _ECR_MISSING_MARKERS):
            raise ContainersError(f"{repository}:{tag} does not exist in ECR; build and push it first")
        detail = result.stderr.strip() or result.stdout.strip()
        raise ContainersError(f"aws ecr describe-images failed for {repository}:{tag}: {detail}")
    try:
        data = json.loads(result.stdout)
        digest = data["imageDetails"][0]["imageDigest"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        raise ContainersError(
            f"aws ecr describe-images response is missing imageDigest for {repository}:{tag}"
        ) from error
    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        raise ContainersError(f"aws ecr describe-images returned an unexpected digest for {repository}:{tag}")
    return digest


def ecr_login(runner: CommandRunner, registry: str, region: str) -> None:
    password = run_or_raise(
        runner,
        ["aws", "ecr", "get-login-password", "--region", region],
        error_prefix="aws ecr get-login-password",
    ).strip()
    run_or_raise(
        runner,
        ["docker", "login", "--username", "AWS", "--password-stdin", registry],
        input=password,
        error_prefix="docker login",
    )


# --------------------------------------------------------------------------
# plan
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanEntry:
    name: str
    tag: str
    exists: bool | None
    action: str

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "tag": self.tag, "exists": self.exists, "action": self.action}


def plan_containers(
    manifest: Manifest,
    names: Sequence[str],
    root: Path,
    runner: CommandRunner,
    *,
    registry_enabled: bool,
    region: str,
) -> list[PlanEntry]:
    entries: list[PlanEntry] = []
    for container in manifest.select(names):
        tag = source_tag(container, root, runner)
        if not registry_enabled:
            entries.append(PlanEntry(container.name, tag, None, "build"))
            continue
        exists = ecr_tag_exists(runner, container.repository, tag, region)
        entries.append(PlanEntry(container.name, tag, exists, "skip" if exists else "build"))
    return entries


def cmd_plan(
    args: argparse.Namespace,
    manifest: Manifest,
    root: Path,
    runner: CommandRunner,
    env: Mapping[str, str],
) -> int:
    region = determine_region(args, env)
    entries = plan_containers(
        manifest,
        tuple(args.names),
        root,
        runner,
        registry_enabled=not args.no_registry,
        region=region,
    )
    if args.json:
        print(json.dumps([entry.as_dict() for entry in entries], indent=2))
        return 0

    name_width = max((len(entry.name) for entry in entries), default=4)
    tag_width = max((len(entry.tag) for entry in entries), default=3)
    print(f"{'NAME'.ljust(name_width)}  {'TAG'.ljust(tag_width)}  EXISTS  ACTION")
    for entry in entries:
        exists_display = "-" if entry.exists is None else ("yes" if entry.exists else "no")
        print(f"{entry.name.ljust(name_width)}  {entry.tag.ljust(tag_width)}  {exists_display.ljust(6)}  {entry.action}")
    return 0


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------


def select_build_targets(args: argparse.Namespace) -> tuple[str, ...]:
    if args.all and args.names:
        raise ContainersError("cannot combine --all with explicit container names")
    if not args.all and not args.names:
        raise ContainersError("specify one or more container names or --all")
    return () if args.all else tuple(args.names)


def build_one(runner: CommandRunner, root: Path, container: ContainerSpec, registry: str, tag: str, *, push: bool) -> None:
    image_ref = f"{registry}/{container.repository}:{tag}"
    argv = [
        "docker",
        "buildx",
        "build",
        "--platform",
        container.platform,
        "--provenance=false",
        "--file",
        container.dockerfile,
        "--tag",
        image_ref,
    ]
    # Without an explicit output, buildx only warms the cache on a container
    # driver and leaves nothing runnable, so a no-push build loads locally.
    argv.append("--push" if push else "--load")
    argv.append(container.context)
    run_or_raise(runner, argv, cwd=root, error_prefix=f"docker buildx build ({container.name})")


def cmd_build(
    args: argparse.Namespace,
    manifest: Manifest,
    root: Path,
    runner: CommandRunner,
    env: Mapping[str, str],
) -> int:
    names = select_build_targets(args)
    targets = manifest.select(names)
    region = determine_region(args, env)
    registry = resolve_registry(args.registry, env, runner, region)

    logged_in = False
    for container in targets:
        tag = source_tag(container, root, runner)
        if not args.force:
            if ecr_tag_exists(runner, container.repository, tag, region):
                print(f"skip {container.name}: {tag} already in ECR")
                continue
        if args.push and not logged_in:
            ecr_login(runner, registry, region)
            logged_in = True
        build_one(runner, root, container, registry, tag, push=args.push)
        verb = "built and pushed" if args.push else "built"
        print(f"{verb} {container.name}: {registry}/{container.repository}:{tag}")
    return 0


# --------------------------------------------------------------------------
# digests
# --------------------------------------------------------------------------


def cmd_digests(
    args: argparse.Namespace,
    manifest: Manifest,
    root: Path,
    runner: CommandRunner,
    env: Mapping[str, str],
) -> int:
    targets = manifest.select(tuple(args.names))
    region = determine_region(args, env)
    registry = resolve_registry(args.registry, env, runner, region)

    result: dict[str, dict[str, str]] = {}
    for container in targets:
        tag = source_tag(container, root, runner)
        digest = ecr_image_digest(runner, container.repository, tag, region)
        result[container.name] = {
            "repository": container.repository,
            "tag": tag,
            "image_uri": f"{registry}/{container.repository}@{digest}",
        }

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for name in sorted(result):
            print(f"{name}\t{result[name]['image_uri']}")
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="containers.py",
        description="Build and publish container images with source-digest change detection.",
    )
    parser.add_argument("--manifest", type=Path, default=None, help="Path to containers/manifest.json")
    parser.add_argument("--region", default=None, help="AWS region (default: $AWS_REGION or us-east-1)")
    parser.add_argument(
        "--registry",
        default=None,
        help="Registry host (default: $CONTAINER_REGISTRY or derived from aws sts get-caller-identity)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="Show build/skip status for each container")
    plan_parser.add_argument("names", nargs="*")
    plan_parser.add_argument("--json", action="store_true")
    plan_parser.add_argument("--no-registry", action="store_true", help="Compute tags without any AWS call")
    plan_parser.set_defaults(func=cmd_plan)

    build_parser = subparsers.add_parser("build", help="Build (and optionally push) changed containers")
    build_parser.add_argument("names", nargs="*")
    build_parser.add_argument("--push", action="store_true", help="Log in to ECR and push after building")
    build_parser.add_argument("--all", action="store_true", help="Build every container in the manifest")
    build_parser.add_argument("--force", action="store_true", help="Rebuild regardless of ECR tag existence")
    build_parser.set_defaults(func=cmd_build)

    digests_parser = subparsers.add_parser(
        "digests", help="Resolve each container's current tag to an immutable digest URI"
    )
    digests_parser.add_argument("names", nargs="*")
    digests_parser.add_argument("--json", action="store_true")
    digests_parser.set_defaults(func=cmd_digests)

    return parser


def run_cli(
    argv: Sequence[str] | None,
    *,
    root: Path,
    runner: CommandRunner,
    env: Mapping[str, str],
) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    manifest_path = args.manifest or (root / "containers" / "manifest.json")
    try:
        manifest = load_manifest(manifest_path)
        return args.func(args, manifest, root, runner, env)
    except ContainersError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli(argv, root=repository_root(), runner=SubprocessRunner(), env=os.environ)


if __name__ == "__main__":
    raise SystemExit(main())
