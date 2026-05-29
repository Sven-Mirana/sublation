#!/usr/bin/env python3
"""Create a structured skill-sublation observation record."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


CLASSIFICATIONS = ("clean", "partial", "defect", "critical")
REFLECTION_TYPES = ("DISCOVERY", "OPTIMIZATION", "SKILL_DEFECT", "EXECUTION_LAPSE")
RECOMMENDATIONS = ("obs_only", "flag_for_review", "create_candidate")
IGNORED_NAMES = {"__pycache__", ".git", ".hg", ".svn", ".DS_Store"}
IGNORED_SUFFIXES = (".pyc", ".pyo", ".orig", ".bak")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_hash(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def tree_hash(path: Path) -> str:
    h = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        rel_path = item.relative_to(path)
        if (
            not item.is_file()
            or any(part in IGNORED_NAMES for part in rel_path.parts)
            or rel_path.name.endswith(IGNORED_SUFFIXES)
            or rel_path.name.endswith("~")
        ):
            continue
        rel = rel_path.as_posix()
        h.update(rel.encode("utf-8") + b"\0" + file_hash(item).encode("ascii") + b"\n")
    return h.hexdigest()


def content_hash(skill_name: str, skill_path: str | None) -> str:
    if skill_path:
        path = Path(skill_path).expanduser()
        if path.exists():
            return tree_hash(path)
    return sha256_bytes(skill_name.encode("utf-8"))


def validate_unit_interval(parser: argparse.ArgumentParser, value: float, label: str) -> None:
    if not 0 <= value <= 1:
        parser.error(f"{label} must be between 0 and 1")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skill_name")
    parser.add_argument("--skill-path")
    parser.add_argument("--session", required=True)
    parser.add_argument("--classification", required=True, choices=CLASSIFICATIONS)
    parser.add_argument("--reflection-type", required=True, choices=REFLECTION_TYPES)
    parser.add_argument("--confidence", type=float, default=0.8)
    parser.add_argument("--trace-completeness", type=float, default=0.8)
    parser.add_argument("--step", required=True)
    parser.add_argument("--status", default="defect_suspected")
    parser.add_argument("--sub-label", default="")
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--recommendation", default="flag_for_review", choices=RECOMMENDATIONS)
    parser.add_argument("--observations-root", default="~/.hermes/skill-observations")
    parser.add_argument("--print-json", action="store_true")
    args = parser.parse_args()
    validate_unit_interval(parser, args.confidence, "--confidence")
    validate_unit_interval(parser, args.trace_completeness, "--trace-completeness")

    now = datetime.now(timezone.utc)
    full_hash = content_hash(args.skill_name, args.skill_path)
    short_hash = full_hash[:12]
    session_hash = sha256_bytes(args.session.encode("utf-8"))[:12]

    root = Path(args.observations_root).expanduser() / short_hash
    obs_dir = root / "observations"
    obs_dir.mkdir(parents=True, exist_ok=True)

    record = {
        "schema_version": 3,
        "timestamp": now.isoformat(),
        "skill_name": args.skill_name,
        "skill_path": args.skill_path,
        "skill_content_hash": f"sha256:{full_hash}",
        "source_session_hash": f"sha256:{session_hash}",
        "source_session": args.session,
        "classification": args.classification,
        "reflection_type": args.reflection_type,
        "confidence": args.confidence,
        "trace_completeness": args.trace_completeness,
        "step_details": [
            {
                "step": args.step,
                "status": args.status,
                "sub_label": args.sub_label,
                "evidence_short": args.evidence,
                "confidence": args.confidence,
            }
        ],
        "summary": args.summary,
        "recommendation": args.recommendation,
    }

    filename = f"{now.strftime('%Y%m%d-%H%M%S')}-{session_hash}.json"
    path = obs_dir / filename
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    index_item = {
        "timestamp": record["timestamp"],
        "skill_name": args.skill_name,
        "classification": args.classification,
        "reflection_type": args.reflection_type,
        "recommendation": args.recommendation,
        "path": str(path),
    }
    with (root / "index.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(index_item, ensure_ascii=False) + "\n")

    if args.print_json:
        print(json.dumps(record, ensure_ascii=False, indent=2))
    else:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

