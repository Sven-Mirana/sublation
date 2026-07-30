#!/usr/bin/env python3
"""Aggregate privacy-minimal Skill usage events into Markdown."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


SKILL_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
SESSION_RE = re.compile(r"^[0-9a-f]{12}$")
LEGACY_SESSION_RE = re.compile(r"^[A-Za-z0-9._-]{1,16}$")


def _valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def normalize_record(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    keys = set(value)
    if keys == {"ts", "skill", "session_id"}:
        session = value.get("session_id")
        if not isinstance(session, str) or not SESSION_RE.fullmatch(session):
            return None
    elif keys == {"ts", "skill", "session"}:
        session = value.get("session")
        if not isinstance(session, str) or not LEGACY_SESSION_RE.fullmatch(session):
            return None
    else:
        return None
    skill = value.get("skill")
    if not isinstance(skill, str) or not SKILL_RE.fullmatch(skill):
        return None
    if not _valid_timestamp(value.get("ts")):
        return None
    return {"ts": value["ts"], "skill": skill, "session_id": session}


def load_events(path: Path) -> tuple[list[dict[str, str]], int]:
    events: list[dict[str, str]] = []
    rejected = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            normalized = normalize_record(json.loads(line))
        except json.JSONDecodeError:
            normalized = None
        if normalized is None:
            rejected += 1
        else:
            events.append(normalized)
    return events, rejected


def load_known_skills(path: Path | None) -> list[str]:
    if path is None:
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, list)
        or not all(isinstance(item, str) and SKILL_RE.fullmatch(item) for item in payload)
        or len(payload) != len(set(payload))
    ):
        raise ValueError("known-skills must be a unique JSON array of canonical skill ids")
    return sorted(payload)


def render_markdown(
    events: list[dict[str, str]],
    rejected: int = 0,
    known_skills: list[str] | None = None,
) -> str:
    aggregate: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"calls": 0, "sessions": set(), "timestamps": []}
    )
    for event in events:
        bucket = aggregate[event["skill"]]
        bucket["calls"] += 1
        bucket["sessions"].add(event["session_id"])
        bucket["timestamps"].append(event["ts"])

    skill_ids = set(aggregate)
    if known_skills:
        skill_ids.update(known_skills)
    lines = [
        "# Skill Sublation Usage Report",
        "",
        f"- Accepted events: {len(events)}",
        f"- Rejected records: {rejected}",
        "",
        "| Skill | Calls | Distinct sessions | First seen | Last seen |",
        "|---|---:|---:|---|---|",
    ]
    for skill in sorted(skill_ids):
        bucket = aggregate.get(skill)
        if bucket is None:
            lines.append(f"| `{skill}` | 0 | 0 | - | - |")
            continue
        timestamps = sorted(bucket["timestamps"])
        lines.append(
            f"| `{skill}` | {bucket['calls']} | {len(bucket['sessions'])} | "
            f"{timestamps[0]} | {timestamps[-1]} |"
        )
    if not skill_ids:
        lines.append("| None | 0 | 0 | - | - |")
    lines.extend(
        [
            "",
            "Session identifiers are intentionally omitted.",
            "A call count is supporting evidence, not a business-smoke verdict.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("usage_log")
    parser.add_argument("--known-skills")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        events, rejected = load_events(Path(args.usage_log))
        known = load_known_skills(Path(args.known_skills) if args.known_skills else None)
        output = render_markdown(events, rejected, known)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
