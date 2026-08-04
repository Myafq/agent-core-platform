"""Offline tests for the container build/publish tool.

Uses a fake command runner injected in place of ``git``, ``docker``, and
``aws`` so nothing here touches the network, real Docker, or real AWS. Source
files live under a temporary directory that stands in for the repository
root; ``git ls-files`` output is canned per test, but file bytes are read for
real from that temporary directory, matching the tool's "hash the working
tree, not the git blob" contract.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.containers import (
    CommandResult,
    ContainerSpec,
    ContainersError,
    Manifest,
    build_one,
    cmd_build,
    cmd_digests,
    cmd_plan,
    compute_source_digest,
    ecr_login,
    parse_manifest,
    plan_containers,
    run_cli,
    select_build_targets,
    source_tag,
)


class FakeRunner:
    """Records every invocation and answers git/docker/aws calls deterministically."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.tracked_files: list[str] = []
        self.account_id = "111111111111"
        self.existing: set[tuple[str, str]] = set()
        self.digest_for: dict[tuple[str, str], str] = {}
        self.fail_build = False

    def run(self, args, *, cwd=None, input=None) -> CommandResult:
        args = list(args)
        self.calls.append({"args": args, "cwd": cwd, "input": input})

        if args[:2] == ["git", "ls-files"]:
            stdout = "".join(f"{path}\0" for path in self.tracked_files)
            return CommandResult(0, stdout, "")

        if args[:3] == ["aws", "sts", "get-caller-identity"]:
            return CommandResult(0, json.dumps({"Account": self.account_id}), "")

        if args[:3] == ["aws", "ecr", "describe-images"]:
            repository = args[args.index("--repository-name") + 1]
            tag = args[args.index("--image-ids") + 1].split("=", 1)[1]
            if (repository, tag) in self.existing:
                digest = self.digest_for.get((repository, tag), "sha256:" + "a" * 64)
                body = {"imageDetails": [{"imageDigest": digest}]}
                return CommandResult(0, json.dumps(body), "")
            return CommandResult(
                254,
                "",
                "An error occurred (RepositoryNotFoundException) when calling the "
                "DescribeImages operation: The repository does not exist.",
            )

        if args[:3] == ["aws", "ecr", "get-login-password"]:
            return CommandResult(0, "s3cr3t-token\n", "")

        if args[:2] == ["docker", "login"]:
            return CommandResult(0, "Login Succeeded", "")

        if args[:3] == ["docker", "buildx", "build"]:
            if self.fail_build:
                return CommandResult(1, "", "buildx failed")
            return CommandResult(0, "", "")

        raise AssertionError(f"FakeRunner received an unexpected command: {args}")


def make_container(**overrides) -> ContainerSpec:
    fields = dict(
        name="github-tool",
        repository="github-tool",
        dockerfile="containers/github-tool/Dockerfile",
        context=".",
        platform="linux/arm64",
        kind="lambda",
        sources=("containers/github-tool/", "services/"),
    )
    fields.update(overrides)
    fields["sources"] = tuple(fields["sources"])
    return ContainerSpec(**fields)


RAW_MANIFEST = {
    "version": 1,
    "containers": [
        {
            "name": "github-tool",
            "repository": "github-tool",
            "dockerfile": "containers/github-tool/Dockerfile",
            "context": ".",
            "platform": "linux/arm64",
            "kind": "lambda",
            "sources": ["containers/github-tool/", "services/", "contracts/", "schemas/"],
        },
        {
            "name": "harness-coding",
            "repository": "github-app-tool-coding",
            "dockerfile": "containers/harness-coding/Dockerfile",
            "context": "containers/harness-coding",
            "platform": "linux/arm64",
            "kind": "harness",
            "sources": ["containers/harness-coding/"],
        },
    ],
}


class TemporaryRootTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write(self, relative_path: str, content: bytes) -> None:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


class DigestStabilityTests(TemporaryRootTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.container = make_container()
        self.write("containers/github-tool/Dockerfile", b"FROM scratch\n")
        self.write("services/github_tool/handler.py", b"def handler(): pass\n")
        self.runner = FakeRunner()
        self.runner.tracked_files = [
            "containers/github-tool/Dockerfile",
            "services/github_tool/handler.py",
        ]

    def test_same_inputs_produce_the_same_tag(self) -> None:
        first = source_tag(self.container, self.root, self.runner)
        second = source_tag(self.container, self.root, self.runner)
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("src-"))
        self.assertEqual(len(first), len("src-") + 12)

    def test_changed_file_bytes_change_the_tag(self) -> None:
        before = source_tag(self.container, self.root, self.runner)
        self.write("services/github_tool/handler.py", b"def handler(): return 1\n")
        after = source_tag(self.container, self.root, self.runner)
        self.assertNotEqual(before, after)

    def test_changed_platform_changes_the_tag(self) -> None:
        before = source_tag(self.container, self.root, self.runner)
        other = make_container(platform="linux/amd64")
        after = source_tag(other, self.root, self.runner)
        self.assertNotEqual(before, after)

    def test_changed_dockerfile_path_changes_the_tag(self) -> None:
        before = source_tag(self.container, self.root, self.runner)
        other = make_container(dockerfile="containers/github-tool/Dockerfile.alt")
        after = source_tag(other, self.root, self.runner)
        self.assertNotEqual(before, after)

    def test_changed_context_changes_the_tag(self) -> None:
        before = source_tag(self.container, self.root, self.runner)
        other = make_container(context="containers/github-tool")
        after = source_tag(other, self.root, self.runner)
        self.assertNotEqual(before, after)

    def test_file_ordering_does_not_affect_the_tag(self) -> None:
        forward = FakeRunner()
        forward.tracked_files = [
            "containers/github-tool/Dockerfile",
            "services/github_tool/handler.py",
        ]
        reverse = FakeRunner()
        reverse.tracked_files = list(reversed(forward.tracked_files))

        self.assertEqual(
            source_tag(self.container, self.root, forward),
            source_tag(self.container, self.root, reverse),
        )

    def test_missing_tracked_file_raises_a_clear_error(self) -> None:
        runner = FakeRunner()
        runner.tracked_files = ["containers/github-tool/Dockerfile", "services/does_not_exist.py"]
        with self.assertRaisesRegex(ContainersError, "missing from the working tree.*does_not_exist.py"):
            compute_source_digest(self.container, self.root, runner)

    def test_no_tracked_sources_raises_rather_than_tagging_nothing(self) -> None:
        runner = FakeRunner()
        runner.tracked_files = []
        with self.assertRaisesRegex(ContainersError, "no tracked files under"):
            compute_source_digest(self.container, self.root, runner)


class ManifestValidationTests(unittest.TestCase):
    def test_valid_manifest_parses(self) -> None:
        manifest = parse_manifest(RAW_MANIFEST)
        self.assertEqual(manifest.version, 1)
        self.assertEqual([c.name for c in manifest.containers], ["github-tool", "harness-coding"])
        self.assertEqual(manifest.get("harness-coding").repository, "github-app-tool-coding")

    def test_rejects_bad_version(self) -> None:
        raw = {"version": 2, "containers": []}
        with self.assertRaisesRegex(ContainersError, "unsupported manifest version"):
            parse_manifest(raw)

    def test_rejects_non_integer_version(self) -> None:
        raw = {"version": "1", "containers": []}
        with self.assertRaisesRegex(ContainersError, "unsupported manifest version"):
            parse_manifest(raw)

    def test_rejects_duplicate_names(self) -> None:
        raw = {
            "version": 1,
            "containers": [
                {
                    "name": "dup",
                    "repository": "r",
                    "dockerfile": "d",
                    "context": ".",
                    "platform": "linux/arm64",
                    "kind": "lambda",
                    "sources": ["a/"],
                },
                {
                    "name": "dup",
                    "repository": "r2",
                    "dockerfile": "d2",
                    "context": ".",
                    "platform": "linux/arm64",
                    "kind": "lambda",
                    "sources": ["b/"],
                },
            ],
        }
        with self.assertRaisesRegex(ContainersError, "duplicate container name"):
            parse_manifest(raw)

    def test_rejects_missing_required_field(self) -> None:
        raw = {
            "version": 1,
            "containers": [
                {
                    "name": "x",
                    "repository": "r",
                    "dockerfile": "d",
                    "context": ".",
                    "kind": "lambda",
                    "sources": ["a/"],
                }
            ],
        }
        with self.assertRaisesRegex(ContainersError, "missing required fields.*platform"):
            parse_manifest(raw)

    def test_rejects_unknown_field(self) -> None:
        raw = {
            "version": 1,
            "containers": [
                {
                    "name": "x",
                    "repository": "r",
                    "dockerfile": "d",
                    "context": ".",
                    "platform": "linux/arm64",
                    "kind": "lambda",
                    "sources": ["a/"],
                    "extra": "nope",
                }
            ],
        }
        with self.assertRaisesRegex(ContainersError, "unknown fields.*extra"):
            parse_manifest(raw)

    def test_rejects_non_list_sources(self) -> None:
        raw = {
            "version": 1,
            "containers": [
                {
                    "name": "x",
                    "repository": "r",
                    "dockerfile": "d",
                    "context": ".",
                    "platform": "linux/arm64",
                    "kind": "lambda",
                    "sources": "a/",
                }
            ],
        }
        with self.assertRaisesRegex(ContainersError, "sources must be a non-empty list"):
            parse_manifest(raw)

    def test_rejects_unknown_top_level_field(self) -> None:
        raw = {"version": 1, "containers": [], "unexpected": True}
        with self.assertRaisesRegex(ContainersError, "unknown top-level fields.*unexpected"):
            parse_manifest(raw)

    def test_manifest_must_be_an_object(self) -> None:
        with self.assertRaisesRegex(ContainersError, "must be a JSON object"):
            parse_manifest(["not", "an", "object"])


class PlanTests(TemporaryRootTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.manifest = parse_manifest(RAW_MANIFEST)
        for source in ("containers/github-tool/Dockerfile", "containers/harness-coding/Dockerfile"):
            self.write(source, b"FROM scratch\n")
        self.runner = FakeRunner()

    def entries_by_name(self, entries):
        return {entry.name: entry for entry in entries}

    def test_skip_when_tag_already_exists_in_ecr(self) -> None:
        self.runner.tracked_files = ["containers/github-tool/Dockerfile"]
        github_tool = self.manifest.get("github-tool")
        tag = source_tag(github_tool, self.root, self.runner)
        self.runner.existing.add((github_tool.repository, tag))

        entries = self.entries_by_name(
            plan_containers(
                self.manifest, ["github-tool"], self.root, self.runner, registry_enabled=True, region="us-east-1"
            )
        )
        self.assertEqual(entries["github-tool"].action, "skip")
        self.assertTrue(entries["github-tool"].exists)

    def test_build_when_tag_is_new(self) -> None:
        self.runner.tracked_files = ["containers/github-tool/Dockerfile"]
        entries = self.entries_by_name(
            plan_containers(
                self.manifest, ["github-tool"], self.root, self.runner, registry_enabled=True, region="us-east-1"
            )
        )
        self.assertEqual(entries["github-tool"].action, "build")
        self.assertFalse(entries["github-tool"].exists)

    def test_missing_repository_is_treated_as_build_not_a_crash(self) -> None:
        # FakeRunner answers every non-`existing` (repository, tag) with
        # RepositoryNotFoundException, exactly like a brand new ECR repository.
        self.runner.tracked_files = ["containers/harness-coding/Dockerfile"]
        entries = self.entries_by_name(
            plan_containers(
                self.manifest, ["harness-coding"], self.root, self.runner, registry_enabled=True, region="us-east-1"
            )
        )
        self.assertEqual(entries["harness-coding"].action, "build")

    def test_no_registry_mode_makes_no_aws_calls(self) -> None:
        self.runner.tracked_files = ["containers/github-tool/Dockerfile"]
        entries = self.entries_by_name(
            plan_containers(
                self.manifest, ["github-tool"], self.root, self.runner, registry_enabled=False, region="us-east-1"
            )
        )
        self.assertEqual(entries["github-tool"].action, "build")
        self.assertIsNone(entries["github-tool"].exists)
        aws_calls = [call for call in self.runner.calls if call["args"][0] == "aws"]
        self.assertEqual(aws_calls, [])

    def test_unknown_container_name_is_a_clear_error(self) -> None:
        with self.assertRaisesRegex(ContainersError, "unknown container"):
            plan_containers(
                self.manifest, ["nope"], self.root, self.runner, registry_enabled=False, region="us-east-1"
            )


class BuildTests(TemporaryRootTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.manifest = parse_manifest(RAW_MANIFEST)
        self.write("containers/github-tool/Dockerfile", b"FROM scratch\n")
        self.write("containers/harness-coding/Dockerfile", b"FROM scratch\n")
        self.runner = FakeRunner()
        self.runner.tracked_files = ["containers/github-tool/Dockerfile"]
        self.env = {"AWS_REGION": "us-east-1", "CONTAINER_REGISTRY": "123456789012.dkr.ecr.us-east-1.amazonaws.com"}

    def buildx_calls(self):
        return [call for call in self.runner.calls if call["args"][:3] == ["docker", "buildx", "build"]]

    def test_push_issues_login_then_buildx_with_push_flag(self) -> None:
        args = make_build_args(push=True, names=["github-tool"])
        exit_code = cmd_build(args, self.manifest, self.root, self.runner, self.env)
        self.assertEqual(exit_code, 0)

        get_password_calls = [call for call in self.runner.calls if call["args"][:3] == ["aws", "ecr", "get-login-password"]]
        self.assertEqual(len(get_password_calls), 1)

        login_calls = [call for call in self.runner.calls if call["args"][:2] == ["docker", "login"]]
        self.assertEqual(len(login_calls), 1)
        self.assertEqual(login_calls[0]["input"], "s3cr3t-token")
        self.assertNotIn("s3cr3t-token", login_calls[0]["args"])

        build_calls = self.buildx_calls()
        self.assertEqual(len(build_calls), 1)
        expected_tag = source_tag(self.manifest.get("github-tool"), self.root, self.runner)
        expected_image = f"123456789012.dkr.ecr.us-east-1.amazonaws.com/github-tool:{expected_tag}"
        self.assertIn("--push", build_calls[0]["args"])
        self.assertIn(expected_image, build_calls[0]["args"])
        self.assertIn("containers/github-tool/Dockerfile", build_calls[0]["args"])

    def test_without_push_issues_no_login_and_no_push_flag(self) -> None:
        args = make_build_args(push=False, names=["github-tool"])
        cmd_build(args, self.manifest, self.root, self.runner, self.env)

        login_calls = [call for call in self.runner.calls if call["args"][:2] == ["docker", "login"]]
        get_password_calls = [call for call in self.runner.calls if call["args"][:3] == ["aws", "ecr", "get-login-password"]]
        self.assertEqual(login_calls, [])
        self.assertEqual(get_password_calls, [])

        build_calls = self.buildx_calls()
        self.assertEqual(len(build_calls), 1)
        self.assertNotIn("--push", build_calls[0]["args"])
        # A no-push build must still leave a runnable local image.
        self.assertIn("--load", build_calls[0]["args"])

    def test_skips_build_when_tag_already_exists_and_not_forced(self) -> None:
        tag = source_tag(self.manifest.get("github-tool"), self.root, self.runner)
        self.runner.existing.add(("github-tool", tag))
        args = make_build_args(push=False, names=["github-tool"])
        cmd_build(args, self.manifest, self.root, self.runner, self.env)
        self.assertEqual(self.buildx_calls(), [])

    def test_force_rebuilds_even_when_tag_exists(self) -> None:
        tag = source_tag(self.manifest.get("github-tool"), self.root, self.runner)
        self.runner.existing.add(("github-tool", tag))
        args = make_build_args(push=False, names=["github-tool"], force=True)
        cmd_build(args, self.manifest, self.root, self.runner, self.env)
        self.assertEqual(len(self.buildx_calls()), 1)

    def test_all_flag_builds_every_manifest_container(self) -> None:
        args = make_build_args(push=False, all_=True)
        cmd_build(args, self.manifest, self.root, self.runner, self.env)
        built_repositories = {call["args"][call["args"].index("--tag") + 1].split(":")[0] for call in self.buildx_calls()}
        self.assertEqual(
            built_repositories,
            {
                "123456789012.dkr.ecr.us-east-1.amazonaws.com/github-tool",
                "123456789012.dkr.ecr.us-east-1.amazonaws.com/github-app-tool-coding",
            },
        )

    def test_all_and_explicit_names_together_is_rejected(self) -> None:
        args = make_build_args(push=False, all_=True, names=["github-tool"])
        with self.assertRaisesRegex(ContainersError, "cannot combine --all"):
            select_build_targets(args)

    def test_neither_all_nor_names_is_rejected(self) -> None:
        args = make_build_args(push=False)
        with self.assertRaisesRegex(ContainersError, "specify one or more container names or --all"):
            select_build_targets(args)

    def test_never_prints_the_login_password(self) -> None:
        # ecr_login should only ever pass the password through `input`, never argv.
        ecr_login(self.runner, "registry.example", "us-east-1")
        for call in self.runner.calls:
            self.assertNotIn("s3cr3t-token", call["args"])


class _Args:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


def make_build_args(*, push: bool, all_: bool = False, names=None, force: bool = False) -> _Args:
    return _Args(
        names=list(names) if names else [],
        all=all_,
        push=push,
        force=force,
        region=None,
        registry=None,
    )


class DigestsTests(TemporaryRootTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.manifest = parse_manifest(RAW_MANIFEST)
        self.write("containers/github-tool/Dockerfile", b"FROM scratch\n")
        self.runner = FakeRunner()
        self.runner.tracked_files = ["containers/github-tool/Dockerfile"]
        self.env = {"AWS_REGION": "us-east-1", "CONTAINER_REGISTRY": "123456789012.dkr.ecr.us-east-1.amazonaws.com"}

    def test_resolves_current_tag_to_an_immutable_digest_uri(self) -> None:
        tag = source_tag(self.manifest.get("github-tool"), self.root, self.runner)
        self.runner.existing.add(("github-tool", tag))
        self.runner.digest_for[("github-tool", tag)] = "sha256:" + "b" * 64

        args = _Args(names=["github-tool"], json=True, region=None, registry=None)
        cmd_digests(args, self.manifest, self.root, self.runner, self.env)
        # Re-run through plan-style helper for direct assertion instead of stdout capture:
        from scripts.containers import ecr_image_digest, resolve_registry

        region = "us-east-1"
        registry = resolve_registry(None, self.env, self.runner, region)
        digest = ecr_image_digest(self.runner, "github-tool", tag, region)
        self.assertEqual(digest, "sha256:" + "b" * 64)
        self.assertEqual(registry, "123456789012.dkr.ecr.us-east-1.amazonaws.com")

    def test_missing_image_raises_a_clear_error(self) -> None:
        args = _Args(names=["github-tool"], json=True, region=None, registry=None)
        with self.assertRaisesRegex(ContainersError, "does not exist in ECR"):
            cmd_digests(args, self.manifest, self.root, self.runner, self.env)


class CliManifestParsingTests(TemporaryRootTestCase):
    def setUp(self) -> None:
        super().setUp()
        (self.root / "containers").mkdir()
        (self.root / "containers" / "manifest.json").write_text(json.dumps(RAW_MANIFEST), encoding="utf-8")
        self.write("containers/github-tool/Dockerfile", b"FROM scratch\n")
        self.write("containers/harness-coding/Dockerfile", b"FROM scratch\n")

    def test_plan_json_parses_the_manifest_and_reports_all_containers(self) -> None:
        runner = FakeRunner()
        runner.tracked_files = ["containers/github-tool/Dockerfile", "containers/harness-coding/Dockerfile"]
        exit_code = run_cli(
            ["plan", "--json", "--no-registry"],
            root=self.root,
            runner=runner,
            env={},
        )
        self.assertEqual(exit_code, 0)

    def test_unknown_manifest_path_is_a_clean_failure(self) -> None:
        runner = FakeRunner()
        exit_code = run_cli(
            ["--manifest", str(self.root / "containers" / "missing.json"), "plan", "--no-registry"],
            root=self.root,
            runner=runner,
            env={},
        )
        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
