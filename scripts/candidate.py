#!/usr/bin/env python3
"""Create skill-sublation candidate scaffolds."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


CANDIDATE_TYPES = ("spec-patch", "script-enhance", "infra-fix", "tooling")
IGNORED_NAMES = {"__pycache__", ".git", ".hg", ".svn", ".DS_Store"}
IGNORED_SUFFIXES = (".pyc", ".pyo", ".orig", ".bak")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_hash(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def is_ignored_name(name: str) -> bool:
    return name in IGNORED_NAMES or name.endswith(IGNORED_SUFFIXES) or name.endswith("~")


def should_ignore(_dir: str, names: list[str]) -> set[str]:
    return {name for name in names if is_ignored_name(name)}


def collect_hashes(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if not path.is_file() or any(part in IGNORED_NAMES for part in rel.parts) or rel.name.endswith(IGNORED_SUFFIXES) or rel.name.endswith("~"):
            continue
        files[path.relative_to(root).as_posix()] = f"sha256:{file_hash(path)}"
    return files


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for rel, digest in collect_hashes(root).items():
        h.update(rel.encode("utf-8") + b"\0" + digest.encode("ascii") + b"\n")
    return f"sha256:{h.hexdigest()}"


def validate_path_component(value: str, label: str) -> None:
    if not value or value in {".", ".."} or value.startswith("~"):
        raise SystemExit(f"{label} must be a plain path segment")
    if "/" in value or "\\" in value or "\0" in value:
        raise SystemExit(f"{label} must not contain path separators or NUL")


def create(args: argparse.Namespace) -> int:
    validate_path_component(args.skill_name, "skill_name")
    validate_path_component(args.agent, "agent")
    source = Path(args.source_path).expanduser().resolve()
    if not source.exists() or not source.is_dir():
        raise SystemExit(f"source path not found or not a directory: {source}")

    now = datetime.now(timezone.utc)
    candidate_id = args.candidate_id or f"{now.strftime('%Y%m%d-%H%M%S')}-{args.agent}"
    validate_path_component(candidate_id, "candidate_id")
    candidate_root = Path(args.candidate_root).expanduser().resolve()
    root = (candidate_root / args.skill_name / candidate_id).resolve()
    try:
        root.relative_to(candidate_root)
    except ValueError:
        raise SystemExit("candidate path escaped candidate root")
    if root.exists():
        raise SystemExit(f"candidate already exists: {root}")

    shutil.copytree(source, root, ignore=should_ignore)
    (root / "RATIONALE.md").write_text(
        f"# Rationale\n\nCandidate: `{args.skill_name}/{candidate_id}`\n\n"
        "Describe why this candidate exists, what it changes, and what remains out of scope.\n",
        encoding="utf-8",
    )
    evidence = "\n".join(f"- {item}" for item in args.observation)
    (root / "EVIDENCE.md").write_text(
        f"# Evidence\n\nCandidate: `{args.skill_name}/{candidate_id}`\n\n"
        f"Observations:\n\n{evidence or '- pending'}\n",
        encoding="utf-8",
    )
    (root / "PATCH.diff").write_text("", encoding="utf-8")

    source_files = collect_hashes(source)
    manifest = {
        "schema_version": 3,
        "candidate_id": f"{args.skill_name}/{candidate_id}",
        "candidate_type": args.candidate_type,
        "created_by": args.agent,
        "created_at": now.isoformat(),
        "source_skill": {
            "path": str(source),
            "tree_hash": tree_hash(source),
            "files": source_files,
        },
        "candidate": {
            "path": str(root),
            "tree_hash": tree_hash(root),
            "files": collect_hashes(root),
        },
        "scope": {
            "changes": [],
            "out_of_scope": [],
        },
        "breaking_changes": [],
        "backward_compat": None,
        "rollback_hashes": source_files,
        "trigger_observations": args.observation,
        "validation": {
            "auditor_status": "conditional",
            "cross_reviewed_by": "none",
            "promotion_mode": "none",
            "status": "draft",
            "post_promotion_safety": {
                "rollback_ready": False,
                "rollback_point": "",
                "target_path_verified": False,
                "source_path_matches_promotion_target": None,
                "target_path_note": "",
                "business_smoke_test": {
                    "status": "pending",
                    "evidence": [],
                },
                "fallback_verified": None,
                "old_capability_retained": None,
                "notes": "Fill after promotion; required before closing observation window.",
            },
            "fixture_assertions_passed": 0,
            "notes": "Candidate scaffold created; edit candidate files, update diff/rationale/evidence, then run audit.py.",
        },
    }
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(root)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create_parser = sub.add_parser("create")
    create_parser.add_argument("skill_name")
    create_parser.add_argument("--source-path", required=True)
    create_parser.add_argument("--candidate-root", default="~/.hermes/sublation/candidates")
    create_parser.add_argument("--candidate-type", default="spec-patch", choices=CANDIDATE_TYPES)
    create_parser.add_argument("--agent", default="codex")
    create_parser.add_argument("--candidate-id")
    create_parser.add_argument("--observation", action="append", default=[])
    create_parser.set_defaults(func=create)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
