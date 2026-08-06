#!/usr/bin/env python3
"""Resolve agent manifest targets for provisioning runs.

Single target-resolution entrypoint shared by local runs and CI. Emits one
manifest-relative target per line on stdout (``agents/<name>/agent.yaml``);
all diagnostics go to stderr. In diff mode, removed manifests are a lifecycle
gate: manifest absence never authorizes destroy.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIRECTORY = "agents"
MANIFEST_FILENAME = "agent.yaml"
AGENT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,38}[a-z0-9]$")
SHARED_AGENT_PATHS = (
    "entrypoints/agents/",
    "compositions/agents/",
    "modules/agentcore-harness/",
)
SHARED_AGENT_FILES = {
    "schemas/agent-v1alpha1.schema.json",
    "scripts/validate_spec.py",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPOSITORY_ROOT,
        help="Repository root containing the agents/ manifest tree.",
    )
    parser.add_argument(
        "--diff",
        nargs=2,
        metavar=("BASE", "HEAD"),
        help="Resolve only targets changed between two git revisions.",
    )
    parser.add_argument(
        "--allow-retire",
        action="append",
        default=[],
        metavar="NAME",
        dest="allow_retire",
        help=(
            "Acknowledge the removal of agents/<NAME>/agent.yaml as an "
            "explicit retirement. Repeatable. Without this flag a removed "
            "manifest is an error."
        ),
    )
    parser.add_argument(
        "--retirement-output",
        type=Path,
        help=(
            "Write acknowledged retirements to this new JSON file. Required "
            "with --allow-retire; the file is a destroy-plan input, never a "
            "normal manifest target. Existing files are not overwritten."
        ),
    )
    return parser.parse_args(argv)


def target_for(name: str) -> str:
    return f"{AGENTS_DIRECTORY}/{name}/{MANIFEST_FILENAME}"


def validate_names(names: set[str]) -> list[str]:
    errors = []
    for name in sorted(names):
        if not AGENT_NAME_PATTERN.match(name):
            errors.append(
                f"Invalid agent directory name {name!r} for target "
                f"{target_for(name)}: names must match "
                f"{AGENT_NAME_PATTERN.pattern}"
            )
    return errors


def run_git(repo_root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_root), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


def manifests_at_revision(
    repo_root: Path, revision: str
) -> tuple[set[str], list[str]]:
    """Return agent names with manifests at revision and any git errors."""
    listing = run_git(
        repo_root,
        "ls-tree",
        "-r",
        "--name-only",
        revision,
        "--",
        AGENTS_DIRECTORY,
    )
    if listing.returncode != 0:
        return set(), [
            f"git ls-tree failed for {revision}: {listing.stderr.strip()}"
        ]

    names = set()
    for path in listing.stdout.splitlines():
        classified = classify_path(path)
        if classified is not None and classified[1]:
            names.add(classified[0])
    return names, validate_names(names)


def is_shared_agent_path(path: str) -> bool:
    """Return whether a path change can affect every agent composition."""
    return path in SHARED_AGENT_FILES or path.startswith(SHARED_AGENT_PATHS)


def resolve_revision(repo_root: Path, revision: str) -> tuple[str | None, str | None]:
    resolved = run_git(repo_root, "rev-parse", "--verify", f"{revision}^{{commit}}")
    if resolved.returncode != 0:
        return None, f"git rev-parse failed for {revision}: {resolved.stderr.strip()}"
    return resolved.stdout.strip(), None


def retirement_descriptor(
    name: str, base: str, head: str, manifest_tree_oid: str
) -> dict[str, object]:
    """Build an explicit input for a separate, reviewed destroy-plan runner."""
    manifest_target = target_for(name)
    manifest_tree = f"{AGENTS_DIRECTORY}/{name}"
    return {
        "kind": "agent-retirement",
        "name": name,
        "manifest_target": manifest_target,
        "manifest_source_revision": base,
        "manifest_source_tree": manifest_tree,
        "manifest_tree_oid": manifest_tree_oid,
        "planned_revision": head,
        "state_key": f"{AGENTS_DIRECTORY}/{name}/terraform.tfstate",
        "plan_mode": "destroy",
        "requires_reviewed_destroy": True,
        "materialize_and_plan": {
            "placeholders": [
                "REPOSITORY_ROOT",
                "RETIREMENT_WORKTREE",
                "PLAN_FILE",
            ],
            "preconditions": [
                "RETIREMENT_WORKTREE must not exist",
                "PLAN_FILE must be a new path inside RETIREMENT_WORKTREE",
                "Review the complete destroy plan before any apply",
            ],
            "steps": [
                (
                    "git -C \"${REPOSITORY_ROOT}\" worktree add --detach "
                    f'"${{RETIREMENT_WORKTREE}}" {head}'
                ),
                (
                    f'git -C "${{REPOSITORY_ROOT}}" archive {base} -- '
                    f"{manifest_tree} | tar -x -C \"${{RETIREMENT_WORKTREE}}\""
                ),
                (
                    'test "$(git -C "${RETIREMENT_WORKTREE}" rev-parse '
                    f'{base}:{manifest_tree})" = "{manifest_tree_oid}"'
                ),
                'test ! -e "${RETIREMENT_WORKTREE}/.venv"',
                'python3 -m venv "${RETIREMENT_WORKTREE}/.venv"',
                (
                    '"${RETIREMENT_WORKTREE}/.venv/bin/python" -m pip install '
                    '--requirement '
                    '"${RETIREMENT_WORKTREE}/requirements-dev.txt"'
                ),
                (
                    f'cd "${{RETIREMENT_WORKTREE}}/entrypoints/agents" && '
                    f"MANIFEST_TARGET={manifest_target} mise exec -- terragrunt "
                    'plan -destroy -out="${PLAN_FILE}"'
                ),
            ],
            "expected_manifest_tree_oid": manifest_tree_oid,
            "review_plan_before_apply": True,
        },
    }


def write_retirement_output(
    output: Path, base: str, head: str, retirements: list[dict[str, object]]
) -> str | None:
    """Write retirement descriptors without replacing an existing file."""
    payload = {
        "schema_version": 1,
        "base_revision": base,
        "head_revision": head,
        "retirements": retirements,
    }
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except FileExistsError:
        return f"Refusing to overwrite retirement output: {output}"
    except OSError as error:
        return f"Could not write retirement output {output}: {error}"
    return None


def enumerate_targets(repo_root: Path) -> tuple[list[str], list[str]]:
    """Return (targets, errors) for every manifest under agents/."""
    agents_directory = repo_root / AGENTS_DIRECTORY
    if not agents_directory.is_dir():
        return [], []

    names = set()
    for entry in agents_directory.iterdir():
        if entry.is_dir() and (entry / MANIFEST_FILENAME).is_file():
            names.add(entry.name)

    errors = validate_names(names)
    targets = sorted(target_for(name) for name in names)
    return targets, errors


def classify_path(path: str) -> tuple[str, bool] | None:
    """Return (agent name, is_manifest) for a path under agents/, else None."""
    parts = PurePosixPath(path).parts
    if len(parts) < 3 or parts[0] != AGENTS_DIRECTORY:
        return None
    is_manifest = len(parts) == 3 and parts[2] == MANIFEST_FILENAME
    return parts[1], is_manifest


def diff_targets(
    repo_root: Path, base: str, head: str, allow_retire: list[str]
) -> tuple[list[str], list[dict[str, object]], list[str]]:
    """Return head targets, retirement descriptors, and resolution errors."""
    diff = run_git(repo_root, "diff", "--name-status", base, head)
    if diff.returncode != 0:
        return [], [], [f"git diff failed: {diff.stderr.strip()}"]

    base_names, base_errors = manifests_at_revision(repo_root, base)
    head_names, head_errors = manifests_at_revision(repo_root, head)

    changed: set[str] = set()
    errors = [*base_errors, *head_errors]
    shared_change = False

    for line in diff.stdout.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        status = fields[0][0]
        if status in {"R", "C"} and len(fields) == 3:
            events = [("D", fields[1])] if status == "R" else []
            events.append(("A", fields[2]))
        elif len(fields) == 2:
            events = [(status, fields[1])]
        else:
            errors.append(f"Unparseable diff line: {line!r}")
            continue

        for event_status, path in events:
            if is_shared_agent_path(path):
                shared_change = True
            classified = classify_path(path)
            if classified is None:
                continue
            name, is_manifest = classified
            if event_status != "D" or not is_manifest:
                changed.add(name)

    # Compare both trees instead of relying on diff rename detection. A removed
    # manifest always remains a retirement event; a rename is delete plus add.
    removed = base_names - head_names
    if shared_change:
        changed.update(base_names | head_names)

    # A removed manifest is never emitted as a normal head target.
    changed -= removed

    unacknowledged = sorted(removed - set(allow_retire))
    for name in unacknowledged:
        errors.append(
            f"Removed manifest {target_for(name)} requires explicit "
            "retirement intent: manifest absence never authorizes destroy. "
            f"Re-run with --allow-retire {name} only alongside a separately "
            "reviewed destroy plan."
        )

    for name in sorted(set(allow_retire) - removed):
        errors.append(
            f"--allow-retire {name} did not match any removed manifest in "
            "this diff; no retirement descriptor can be produced."
        )

    errors.extend(validate_names(changed))

    targets = []
    for name in sorted(changed):
        target = target_for(name)
        exists = run_git(repo_root, "cat-file", "-e", f"{head}:{target}")
        if exists.returncode != 0:
            errors.append(
                f"Changed files under {AGENTS_DIRECTORY}/{name}/ but "
                f"{target} does not exist at {head}."
            )
            continue
        targets.append(target)

    retirements = [
        {"name": name} for name in sorted(removed & set(allow_retire))
    ]
    return targets, retirements, errors


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()

    if args.diff:
        base, head = args.diff
        if args.allow_retire and args.retirement_output is None:
            print(
                "--allow-retire requires --retirement-output PATH so every "
                "acknowledged removal yields an explicit destroy-plan input.",
                file=sys.stderr,
            )
            return 1
        if args.retirement_output is not None and not args.allow_retire:
            print(
                "--retirement-output requires at least one --allow-retire NAME.",
                file=sys.stderr,
            )
            return 1

        targets, retirements, errors = diff_targets(
            repo_root, base, head, args.allow_retire
        )
        resolved_base, base_error = resolve_revision(repo_root, base)
        resolved_head, head_error = resolve_revision(repo_root, head)
        errors.extend(error for error in (base_error, head_error) if error)
        if resolved_base and resolved_head:
            resolved_retirements = []
            for retirement in retirements:
                name = str(retirement["name"])
                tree = run_git(
                    repo_root,
                    "rev-parse",
                    "--verify",
                    f"{resolved_base}:{AGENTS_DIRECTORY}/{name}",
                )
                if tree.returncode != 0:
                    errors.append(
                        f"Could not resolve immutable manifest tree for {name}: "
                        f"{tree.stderr.strip()}"
                    )
                    continue
                resolved_retirements.append(
                    retirement_descriptor(
                        name, resolved_base, resolved_head, tree.stdout.strip()
                    )
                )
            retirements = resolved_retirements
    else:
        if args.allow_retire or args.retirement_output is not None:
            print(
                "--allow-retire and --retirement-output require --diff.",
                file=sys.stderr,
            )
            return 1
        targets, errors = enumerate_targets(repo_root)
        retirements = []

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    if retirements:
        assert args.retirement_output is not None
        output = args.retirement_output
        if not output.is_absolute():
            output = repo_root / output
        write_error = write_retirement_output(
            output, resolved_base, resolved_head, retirements
        )
        if write_error:
            print(write_error, file=sys.stderr)
            return 1
        for retirement in retirements:
            print(
                f"Acknowledged retirement of {retirement['manifest_target']}; "
                f"destroy-plan descriptor written to {output}. The manifest "
                "is not emitted as a normal target; destroy still requires a "
                "separately reviewed plan.",
                file=sys.stderr,
            )

    for target in targets:
        print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
