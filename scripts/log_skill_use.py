#!/usr/bin/env python3
"""Privacy-minimal PostToolUse logger for Skill invocations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


SKILL_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
DEFAULT_LOG = "~/.hermes/sublation/usage/usage-log.jsonl"
EVENT_KEYS = ("ts", "skill", "session_id")


def _timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def build_record(
    event: Any,
    now: Callable[[], str] = _timestamp,
) -> dict[str, str] | None:
    if not isinstance(event, dict) or event.get("tool_name") != "Skill":
        return None
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    skill = tool_input.get("skill")
    raw_session = event.get("session_id")
    if not isinstance(skill, str) or not SKILL_RE.fullmatch(skill):
        return None
    if not isinstance(raw_session, str) or not raw_session:
        return None
    session_id = hashlib.sha256(raw_session.encode("utf-8")).hexdigest()[:12]
    return {"ts": now(), "skill": skill, "session_id": session_id}


def append_record(record: dict[str, str], log_path: Path) -> None:
    if tuple(record) != EVENT_KEYS:
        raise ValueError("usage event must contain exactly ts, skill, session_id")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n"
    descriptor = os.open(
        log_path,
        os.O_WRONLY | os.O_APPEND | os.O_CREAT,
        0o600,
    )
    try:
        os.write(descriptor, line.encode("utf-8"))
    finally:
        os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--log",
        default=os.environ.get("SUBLATION_USAGE_LOG", DEFAULT_LOG),
    )
    args = parser.parse_args()
    try:
        event = json.load(sys.stdin)
        record = build_record(event)
        if record is not None:
            append_record(record, Path(args.log).expanduser())
    except Exception:
        # Monitoring must never block the underlying tool call.
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
