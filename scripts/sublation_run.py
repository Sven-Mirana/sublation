#!/usr/bin/env python3
"""Durable, candidate-only orchestration ledger for one-shot Sublation runs."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import hmac
import json
import os
import re
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = 1
CONTROL_DIRNAME = ".control"
CONTROL_KEY_NAME = "run-attestation.key"
RUN_STATES = {
    "DISCOVERING",
    "WORKING",
    "REWORKING",
    "AGGREGATING",
    "USER_DECISION_REQUIRED",
    "PARTIAL",
    "BLOCKED",
    "CLOSED",
    "APPROVED_PENDING_EXECUTION",
    "USER_REJECTED",
    "OBSERVING",
}
ITEM_STATES = {
    "PENDING",
    "OBSERVED",
    "CANDIDATE_READY",
    "AUDIT_PASSED",
    "VERIFY_PASSED",
    "REWORK_REQUIRED",
    "REVIEW_PASSED",
    "APPROVAL_READY",
    "CLOSED_REPORT_ONLY",
    "CLOSED_NOOP",
    "BLOCKED",
}
TERMINAL_ITEM_STATES = {
    "APPROVAL_READY",
    "CLOSED_REPORT_ONLY",
    "CLOSED_NOOP",
    "BLOCKED",
}
NEXT_PHASE = {
    "PENDING": "observe",
    "OBSERVED": "candidate",
    "CANDIDATE_READY": "audit",
    "AUDIT_PASSED": "independent_verify",
    "VERIFY_PASSED": "boundary_review",
    "REWORK_REQUIRED": "candidate_rework",
    "REVIEW_PASSED": "aggregate",
}
ALLOWED_ITEM_TRANSITIONS = {
    "PENDING": {"OBSERVED", "CLOSED_REPORT_ONLY", "CLOSED_NOOP", "BLOCKED"},
    "OBSERVED": {"CANDIDATE_READY", "CLOSED_REPORT_ONLY", "CLOSED_NOOP", "BLOCKED"},
    "CANDIDATE_READY": {"AUDIT_PASSED", "REWORK_REQUIRED", "BLOCKED"},
    "AUDIT_PASSED": {"VERIFY_PASSED", "REWORK_REQUIRED", "BLOCKED"},
    "VERIFY_PASSED": {"REVIEW_PASSED", "REWORK_REQUIRED", "BLOCKED"},
    "REWORK_REQUIRED": {"CANDIDATE_READY", "BLOCKED"},
    "REVIEW_PASSED": {"APPROVAL_READY", "CLOSED_REPORT_ONLY", "CLOSED_NOOP", "BLOCKED"},
}
DEEP_HINTS = ("深度", "跨技能", "安全", "权限", "供应链", "正式根", "deep", "security")
ALL_HINTS = ("现有技能", "全部技能", "所有技能", "全量技能", "all skills")
TRIGGER_HINTS = ("sublation", "扬弃")
DISCOVERY_EXCLUDED_PARTS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    "candidates",
    "node_modules",
    "rollback-points",
    "runs",
    "validation",
}
PHASE_ROLES = {
    "observe": "builder",
    "candidate": "builder",
    "audit": "builder",
    "candidate_rework": "builder",
    "independent_verify": "independent_verifier",
    "boundary_review": "reviewer",
    "aggregate": "coordinator",
}
DEFAULT_ROLE_ACTORS = {
    "builder": "codex",
    "independent_verifier": "claude-code",
    "reviewer": "hermes",
    "coordinator": "hermes",
}
TASK_STATES = {"PENDING", "LEASED", "COMPLETED", "CANCELLED"}
PHASE_INSTRUCTIONS = {
    "observe": "Inspect the current skill and prior evidence; record a sourced observation without formal writes.",
    "candidate": "Build an isolated candidate or close as report-only/no-op; preserve the formal root.",
    "audit": "Run strict candidate, patch, scope, provenance, value-delta, and boundary checks.",
    "independent_verify": "Reproduce the shared candidate independently and challenge unsupported claims.",
    "candidate_rework": "Repair the candidate-layer findings, refresh evidence, and return it to audit.",
    "boundary_review": "Review value delta, user authority, privacy, login, live-action, and rollback boundaries.",
    "aggregate": "Choose the terminal disposition from verified evidence and write a plain-language summary.",
}
STEP_STATUSES = {"pass", "hold", "fail", "blocked"}
PASS_ITEM_STATES = {
    "OBSERVED",
    "CANDIDATE_READY",
    "AUDIT_PASSED",
    "VERIFY_PASSED",
    "REVIEW_PASSED",
    "APPROVAL_READY",
    "CLOSED_REPORT_ONLY",
    "CLOSED_NOOP",
}
PHASE_ITEM_STATES = {
    "observe": {"OBSERVED", "CLOSED_REPORT_ONLY", "CLOSED_NOOP", "BLOCKED"},
    "candidate": {"CANDIDATE_READY", "CLOSED_REPORT_ONLY", "CLOSED_NOOP", "BLOCKED"},
    "audit": {"AUDIT_PASSED", "REWORK_REQUIRED", "BLOCKED"},
    "independent_verify": {"VERIFY_PASSED", "REWORK_REQUIRED", "BLOCKED"},
    "candidate_rework": {"CANDIDATE_READY", "BLOCKED"},
    "boundary_review": {"REVIEW_PASSED", "REWORK_REQUIRED", "BLOCKED"},
    "aggregate": {"APPROVAL_READY", "CLOSED_REPORT_ONLY", "CLOSED_NOOP", "BLOCKED"},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256(value: Any) -> str:
    data = value if isinstance(value, bytes) else canonical(value)
    return "sha256:" + hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()


def ignored_tree_path(rel: Path) -> bool:
    return (
        ".git" in rel.parts
        or "__pycache__" in rel.parts
        or rel.suffix in {".pyc", ".pyo"}
        or rel.name == ".DS_Store"
    )


def collect_tree_hashes(root: Path) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    root = root.expanduser().absolute()
    if not root.exists() and not root.is_symlink():
        return {".": {"kind": "missing"}}
    root_metadata = os.lstat(root)
    root_mode = stat.S_IMODE(root_metadata.st_mode)
    if stat.S_ISLNK(root_metadata.st_mode):
        return {".": {"kind": "symlink", "mode": root_mode, "target": os.readlink(root)}}
    if stat.S_ISREG(root_metadata.st_mode):
        return {".": {"kind": "file", "mode": root_mode, "sha256": sha256(root.read_bytes())}}
    if not stat.S_ISDIR(root_metadata.st_mode):
        return {".": {"kind": "other", "mode": root_mode, "device": int(root_metadata.st_rdev)}}
    entries["./"] = {"kind": "directory", "mode": root_mode}
    root = root.resolve()
    for current, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        retained_dirs: list[str] = []
        for name in sorted(dirnames):
            path = current_path / name
            rel = path.relative_to(root)
            if ignored_tree_path(rel):
                continue
            metadata = os.lstat(path)
            mode = stat.S_IMODE(metadata.st_mode)
            if stat.S_ISLNK(metadata.st_mode):
                entries[rel.as_posix()] = {"kind": "symlink", "mode": mode, "target": os.readlink(path)}
            else:
                entries[rel.as_posix() + "/"] = {"kind": "directory", "mode": mode}
                retained_dirs.append(name)
        dirnames[:] = retained_dirs
        for name in sorted(filenames):
            path = current_path / name
            rel = path.relative_to(root)
            if ignored_tree_path(rel):
                continue
            metadata = os.lstat(path)
            mode = stat.S_IMODE(metadata.st_mode)
            if stat.S_ISLNK(metadata.st_mode):
                entry = {"kind": "symlink", "mode": mode, "target": os.readlink(path)}
            elif stat.S_ISREG(metadata.st_mode):
                entry = {"kind": "file", "mode": mode, "sha256": sha256(path.read_bytes())}
            else:
                entry = {"kind": "other", "mode": mode, "device": int(metadata.st_rdev)}
            entries[rel.as_posix()] = entry
    return entries


def tree_hash(root: Path) -> str:
    return sha256(collect_tree_hashes(root))


def control_dir(run_dir: Path) -> Path:
    return run_dir.expanduser().resolve() / CONTROL_DIRNAME


def control_key_path(run_dir: Path) -> Path:
    return control_dir(run_dir) / CONTROL_KEY_NAME


def initialize_control_key(run_dir: Path) -> bytes:
    directory = control_dir(run_dir)
    if directory.is_symlink():
        raise ValueError("run control directory must not be a symlink")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    path = control_key_path(run_dir)
    if path.exists():
        return load_control_key(run_dir)
    key = os.urandom(32)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, key)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return key


def load_control_key(run_dir: Path) -> bytes:
    path = control_key_path(run_dir)
    metadata = os.lstat(path)
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("run attestation key must be a regular file")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError("run attestation key permissions must be 0600")
    key = path.read_bytes()
    if len(key) != 32:
        raise ValueError("run attestation key must contain exactly 32 bytes")
    return key


def attestation_mac(run_dir: Path, payload: Any) -> str:
    return "hmac-sha256:" + hmac.new(load_control_key(run_dir), canonical(payload), hashlib.sha256).hexdigest()


def write_receipt_attestation(run_dir: Path, payload: dict[str, Any]) -> Path:
    required = {
        "adapter_id",
        "channel",
        "event_id",
        "sender_id",
        "in_reply_to",
        "message",
        "received_at",
        "source_event_hash",
        "report_version",
        "report_hash",
        "scope_revision",
        "approval_code",
    }
    missing = sorted(field for field in required if not str(payload.get(field) or "").strip())
    if missing:
        raise ValueError("receipt attestation is missing fields: " + ", ".join(missing))
    event_id = str(payload["event_id"])
    if not re.fullmatch(r"[A-Za-z0-9._:-]+", event_id):
        raise ValueError("receipt event id contains unsupported characters")
    evidence = {"schema_version": 1, **payload}
    evidence["attestation_mac"] = attestation_mac(run_dir, evidence)
    path = run_dir.expanduser().resolve() / "receipt-io" / f"{event_id}.attested.json"
    if path.exists():
        existing = read_json(path)
        if canonical(existing) != canonical(evidence):
            raise ValueError(f"receipt event id collision with different attested content: {event_id}")
        return path
    atomic_write_json(path, evidence)
    return path


def verify_receipt_attestation(run_dir: Path, evidence_path: Path) -> tuple[dict[str, Any], dict[str, str]]:
    resolved_run = run_dir.expanduser().resolve()
    path = evidence_path.expanduser().resolve()
    receipt_root = resolved_run / "receipt-io"
    if not path.is_file() or not path_is_inside(path, receipt_root):
        raise ValueError("receipt evidence must be an existing attestation inside run/receipt-io")
    evidence = read_json(path)
    attested = dict(evidence)
    supplied_mac = attested.pop("attestation_mac", None)
    expected_mac = attestation_mac(resolved_run, attested)
    if not isinstance(supplied_mac, str) or not hmac.compare_digest(supplied_mac, expected_mac):
        raise ValueError("receipt attestation MAC verification failed")
    if evidence.get("schema_version") != 1:
        raise ValueError("unsupported receipt attestation schema")
    record = {"path": str(path), "sha256": sha256(path.read_bytes())}
    return evidence, record


def path_is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


@contextmanager
def locked_run(run_dir: Path) -> Iterator[None]:
    run_dir.mkdir(parents=True, exist_ok=True)
    lock_path = run_dir / ".run.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def journal_entries(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "journal.jsonl"
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"journal line {line_number} is not an object")
        entries.append(value)
    return entries


def append_event(run_dir: Path, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    entries = verified_journal_entries(run_dir)
    event: dict[str, Any] = {
        "sequence": len(entries) + 1,
        "timestamp": utc_now(),
        "type": event_type,
        "payload": payload,
        "previous_hash": entries[-1]["event_hash"] if entries else None,
    }
    event["event_hash"] = sha256(event)
    event["event_mac"] = attestation_mac(run_dir, event)
    with (run_dir / "journal.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return event


def commit_run(run_dir: Path, run: dict[str, Any], event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    event_payload = dict(payload)
    event_payload["run_revision"] = run["revision"]
    event_payload["run_snapshot"] = run
    event = append_event(run_dir, event_type, event_payload)
    if os.environ.get("SUBLATION_TEST_CRASH_AFTER_JOURNAL") == "1":
        os._exit(91)
    atomic_write_json(run_dir / "run.json", run)
    return event


def verify_journal(
    run_dir: Path, entries: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    previous: str | None = None
    entries = journal_entries(run_dir) if entries is None else entries
    for index, entry in enumerate(entries, start=1):
        if entry.get("sequence") != index:
            raise ValueError(f"journal sequence mismatch at entry {index}")
        if entry.get("previous_hash") != previous:
            raise ValueError(f"journal previous_hash mismatch at entry {index}")
        expected = dict(entry)
        event_mac = expected.pop("event_mac", None)
        event_hash = expected.pop("event_hash", None)
        if event_hash != sha256(expected):
            raise ValueError(f"journal event_hash mismatch at entry {index}")
        signed = {**expected, "event_hash": event_hash}
        if not isinstance(event_mac, str) or not hmac.compare_digest(event_mac, attestation_mac(run_dir, signed)):
            raise ValueError(f"journal event_mac mismatch at entry {index}")
        previous = str(event_hash)
    return {"entries": len(entries), "last_hash": previous, "valid": True}


def verified_journal_entries(run_dir: Path) -> list[dict[str, Any]]:
    entries = journal_entries(run_dir)
    verify_journal(run_dir, entries)
    return entries


def parse_root(raw: str) -> dict[str, str]:
    name, separator, path = raw.partition("=")
    if not separator or not name.strip() or not path.strip():
        raise ValueError("roots must use NAME=PATH")
    return {"name": name.strip(), "path": str(Path(path).expanduser().resolve())}


def load_roots(raw_roots: list[str], roots_file: str | None = None) -> list[dict[str, str]]:
    roots = [parse_root(raw) for raw in raw_roots]
    if roots_file:
        data = json.loads(Path(roots_file).expanduser().read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("roots file must contain an array")
        for item in data:
            if not isinstance(item, dict) or not item.get("name") or not item.get("path"):
                raise ValueError("each roots-file item needs name and path")
            roots.append({"name": str(item["name"]), "path": str(Path(item["path"]).expanduser().resolve())})
    unique: dict[str, dict[str, str]] = {}
    for root in roots:
        key = root["name"].casefold()
        if key in unique and unique[key]["path"] != root["path"]:
            raise ValueError(f"duplicate root name with different paths: {root['name']}")
        unique[key] = root
    result = sorted(unique.values(), key=lambda item: item["name"].casefold())
    if not result:
        raise ValueError("at least one configured root is required")
    return result


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def discover_skills(roots: list[dict[str, str]]) -> list[dict[str, Any]]:
    discovered: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for root in roots:
        root_path = Path(root["path"]).expanduser().resolve()
        if not root_path.is_dir():
            discovered.append(
                {
                    "root_name": root["name"],
                    "root_path": str(root_path),
                    "relative_path": ".",
                    "target": root["name"],
                    "target_path": str(root_path),
                    "skill_name": root["name"],
                    "tree_hash": None,
                    "change_type": "root_missing",
                    "is_symlink": False,
                }
            )
            continue
        for skill_file in sorted(root_path.rglob("SKILL.md")):
            try:
                relative_file = skill_file.relative_to(root_path)
            except ValueError:
                continue
            if any(part in DISCOVERY_EXCLUDED_PARTS for part in relative_file.parts):
                continue
            skill_dir = skill_file.parent
            resolved_skill = skill_dir.resolve()
            resolved_key = str(resolved_skill)
            if resolved_key in seen_paths:
                continue
            seen_paths.add(resolved_key)
            try:
                relative_dir = skill_dir.relative_to(root_path).as_posix()
            except ValueError:
                continue
            relative_dir = relative_dir or "."
            target = root["name"] if relative_dir == "." else f"{root['name']}:{relative_dir}"
            discovered.append(
                {
                    "root_name": root["name"],
                    "root_path": str(root_path),
                    "relative_path": relative_dir,
                    "target": target,
                    "target_path": resolved_key,
                    "skill_name": skill_dir.name if relative_dir != "." else root["name"],
                    "tree_hash": tree_hash(resolved_skill),
                    "change_type": "present",
                    "is_symlink": skill_dir.is_symlink(),
                }
            )
    return sorted(
        discovered,
        key=lambda item: (
            str(item["root_name"]).casefold(),
            str(item["relative_path"]).casefold(),
            str(item["target_path"]),
        ),
    )


def latest_inventory(
    runs_root: Path, roots: list[dict[str, str]], excluded_run_id: str | None = None
) -> tuple[list[str], dict[str, Any]]:
    root = runs_root.expanduser().resolve()
    candidates: list[tuple[datetime, dict[str, Any]]] = []
    if not root.is_dir():
        return [], {}
    for run_file in root.glob("*/run.json"):
        try:
            run = read_json(run_file)
            if run.get("run_id") == excluded_run_id or not run.get("latest_report"):
                continue
            inventory = run.get("inventory")
            if not isinstance(inventory, dict) or not isinstance(inventory.get("skills"), list):
                continue
            candidates.append((parse_timestamp(str(run.get("updated_at") or run.get("created_at"))), run))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    if not candidates:
        return [], {}
    candidates.sort(key=lambda item: item[0], reverse=True)
    hashes: dict[str, Any] = {}
    baseline_run_ids: list[str] = []
    for selected_root in roots:
        selected_path = str(Path(selected_root["path"]).expanduser().resolve())
        previous = next(
            (
                run
                for _timestamp, run in candidates
                if any(
                    str(Path(target.get("path", "")).expanduser().resolve()) == selected_path
                    for target in run.get("scope", {}).get("targets", [])
                    if isinstance(target, dict) and target.get("path")
                )
            ),
            None,
        )
        if not previous:
            continue
        run_id = str(previous.get("run_id"))
        if run_id not in baseline_run_ids:
            baseline_run_ids.append(run_id)
        for skill in previous["inventory"]["skills"]:
            if not isinstance(skill, dict) or not skill.get("target_path"):
                continue
            if str(Path(str(skill.get("root_path", ""))).expanduser().resolve()) != selected_path:
                continue
            hashes[str(skill["target_path"])] = skill.get("tree_hash")
    return baseline_run_ids, hashes


def incremental_inventory(
    roots: list[dict[str, str]], runs_root: Path, excluded_run_id: str | None = None
) -> dict[str, Any]:
    current = discover_skills(roots)
    baseline_run_ids, previous_hashes = latest_inventory(runs_root, roots, excluded_run_id)
    current_paths = {str(skill["target_path"]) for skill in current}
    changed: list[dict[str, Any]] = []
    unchanged: list[str] = []
    for skill in current:
        path = str(skill["target_path"])
        if skill["change_type"] == "root_missing":
            changed.append(skill)
        elif path not in previous_hashes:
            changed.append({**skill, "change_type": "new"})
        elif previous_hashes[path] != skill.get("tree_hash"):
            changed.append({**skill, "change_type": "modified"})
        else:
            unchanged.append(path)
    for removed_path in sorted(set(previous_hashes) - current_paths):
        matching_root = next(
            (root for root in roots if removed_path == root["path"] or removed_path.startswith(root["path"] + os.sep)),
            None,
        )
        if not matching_root:
            continue
        rel = Path(removed_path).relative_to(Path(matching_root["path"])).as_posix() or "."
        target = matching_root["name"] if rel == "." else f"{matching_root['name']}:{rel}"
        changed.append(
            {
                "root_name": matching_root["name"],
                "root_path": matching_root["path"],
                "relative_path": rel,
                "target": target,
                "target_path": removed_path,
                "skill_name": Path(removed_path).name,
                "tree_hash": None,
                "change_type": "removed",
                "is_symlink": False,
            }
        )
    changed.sort(key=lambda item: (str(item["root_name"]).casefold(), str(item["relative_path"]).casefold()))
    return {
        "scanned_at": utc_now(),
        "baseline_run_ids": baseline_run_ids,
        "mode": "incremental" if baseline_run_ids else "initial_full_snapshot",
        "skills": current,
        "changed_skills": changed,
        "unchanged_paths": sorted(unchanged),
        "counts": {
            "discovered": len(current),
            "changed": len(changed),
            "unchanged": len(unchanged),
            "removed": sum(1 for item in changed if item["change_type"] == "removed"),
            "missing_roots": sum(1 for item in changed if item["change_type"] == "root_missing"),
        },
    }


def resolve_scope(intent: str, roots: list[dict[str, str]]) -> dict[str, Any]:
    folded = intent.casefold()
    if not any(hint in folded for hint in TRIGGER_HINTS):
        raise ValueError("intent must explicitly request sublation/扬弃")
    explicit = [root for root in roots if root["name"].casefold() in folded]
    if explicit:
        mode = "named_targets"
        selected = explicit
    elif any(hint in folded for hint in ALL_HINTS):
        mode = "all_roots_incremental"
        selected = roots
    else:
        mode = "all_roots_incremental"
        selected = roots
    detail = "deep" if any(hint in folded for hint in DEEP_HINTS) else "standard"
    return {
        "mode": mode,
        "detail": detail,
        "revision": 1,
        "targets": selected,
        "resolution_note": (
            "Explicit root names select only those roots. Generic '现有技能' or an unnamed request "
            "selects all configured roots incrementally."
        ),
    }


def make_run_id(intent: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"sub-{stamp}-{hashlib.sha256(intent.encode('utf-8')).hexdigest()[:6]}"


def load_run(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "run.json"
    if not path.exists():
        raise FileNotFoundError(f"run ledger missing: {path}")
    run = read_json(path)
    control = run.get("control")
    if not isinstance(control, dict) or control.get("journal_attestation") != "hmac-sha256":
        raise ValueError("run is missing the HMAC-attested control-plane binding")
    key_hash = sha256(load_control_key(run_dir))
    if control.get("attestation_key_sha256") != key_hash:
        raise ValueError("run attestation key fingerprint changed")
    entries = verified_journal_entries(run_dir)
    if entries:
        snapshot = entries[-1].get("payload", {}).get("run_snapshot")
        if isinstance(snapshot, dict):
            snapshot_revision = int(snapshot.get("revision", 0))
            run_revision = int(run.get("revision", 0))
            if snapshot_revision > run_revision:
                run = snapshot
                atomic_write_json(path, run)
            elif snapshot_revision < run_revision:
                raise ValueError("run.json is ahead of the durable journal")
            elif canonical(snapshot) != canonical(run):
                raise ValueError("run.json differs from the journal snapshot at the same revision")
    if run.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported run schema: {run.get('schema_version')!r}")
    if run.get("state") not in RUN_STATES:
        raise ValueError(f"invalid run state: {run.get('state')!r}")
    return run


def item_for_target(index: int, target: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_id": f"A{index}",
        "target": target["target"],
        "target_path": target["target_path"],
        "root_name": target["root_name"],
        "relative_path": target["relative_path"],
        "skill_name": target["skill_name"],
        "source_tree_hash": target.get("tree_hash"),
        "change_type": target["change_type"],
        "is_symlink": bool(target.get("is_symlink")),
        "status": "PENDING",
        "next_phase": "observe",
        "candidate_id": None,
        "candidate_path": None,
        "patch_path": None,
        "patch_hash": None,
        "target_baseline_hash": None,
        "summary": "",
        "disposition": None,
        "approval_required": None,
        "steps": [],
        "evidence": [],
        "blockers": [],
        "phase_attempts": {},
    }


def role_policy(
    role_actors: dict[str, str] | None = None, *, allow_single_agent: bool = False
) -> dict[str, Any]:
    actors = dict(DEFAULT_ROLE_ACTORS)
    if role_actors:
        for role, actor in role_actors.items():
            if role not in DEFAULT_ROLE_ACTORS:
                raise ValueError(f"unknown orchestration role: {role}")
            if not str(actor).strip():
                raise ValueError(f"actor for role {role} must not be empty")
            actors[role] = str(actor).strip()
    independent_seats = {actors["builder"], actors["independent_verifier"], actors["reviewer"]}
    if len(independent_seats) != 3 and not allow_single_agent:
        raise ValueError(
            "builder, independent_verifier, and reviewer must be distinct; "
            "single-agent mode requires explicit user authorization"
        )
    return {
        "mode": "user_authorized_single_agent" if allow_single_agent else "configured_multi_agent",
        "roles": actors,
        "independence_required": not allow_single_agent,
        "single_agent_user_authorized": allow_single_agent,
    }


def bind_worker_identities(run_dir: Path, identities: dict[str, dict[str, Any]]) -> dict[str, Any]:
    normalized: dict[str, dict[str, Any]] = {}
    for actor, identity in identities.items():
        principal = str(identity.get("principal_id") or "").strip()
        fingerprint = str(identity.get("adapter_fingerprint") or "").strip()
        raw_write_roots = identity.get("write_roots")
        if not isinstance(raw_write_roots, list) or not all(
            isinstance(path, str) and path.strip() for path in raw_write_roots
        ):
            raise ValueError("worker identities require a write_roots string array")
        write_roots = sorted(
            {str(Path(path).expanduser().resolve()) for path in raw_write_roots}
        )
        if not actor.strip() or not principal or not fingerprint:
            raise ValueError(
                "worker identities require actor, principal_id, adapter_fingerprint, and write_roots"
            )
        normalized[actor] = {
            "principal_id": principal,
            "adapter_fingerprint": fingerprint,
            "write_roots": write_roots,
        }
    with locked_run(run_dir):
        run = load_run(run_dir)
        roles = run["review_policy"]["roles"]
        missing = sorted({actor for actor in roles.values() if actor not in normalized})
        if missing:
            raise ValueError("worker identity bindings are missing actors: " + ", ".join(missing))
        independent = [roles[role] for role in ("builder", "independent_verifier", "reviewer")]
        if run["review_policy"].get("independence_required"):
            principals = {normalized[actor]["principal_id"] for actor in independent}
            fingerprints = {normalized[actor]["adapter_fingerprint"] for actor in independent}
            if len(principals) != 3 or len(fingerprints) != 3:
                raise ValueError(
                    "independent roles require distinct principals and distinct adapter fingerprints"
                )
            builder_actor = roles["builder"]
            if not normalized[builder_actor]["write_roots"]:
                raise ValueError("the builder identity requires an isolated candidate write_root")
            for role in ("independent_verifier", "reviewer"):
                actor = roles[role]
                if normalized[actor]["write_roots"]:
                    raise ValueError(f"independent {role} identity must have empty write_roots")
        bound = {actor: normalized[actor] for actor in sorted({*roles.values()})}
        if isinstance(run.get("worker_identities"), dict):
            if run["worker_identities"] != bound:
                raise ValueError("worker identity bindings cannot change after the run starts")
            return run
        run["worker_identities"] = bound
        run["revision"] = int(run.get("revision", 0)) + 1
        run["updated_at"] = utc_now()
        commit_run(run_dir, run, "worker_identities_bound", {"worker_identities": bound})
        return run


def task_id_for(item: dict[str, Any], phase: str, attempt: int) -> str:
    return f"{item['item_id']}:{phase}:r{attempt}"


def enqueue_next_task(run: dict[str, Any], item: dict[str, Any]) -> dict[str, Any] | None:
    phase = item.get("next_phase")
    if not phase:
        return None
    active = [
        task
        for task in run.get("tasks", {}).values()
        if task.get("item_id") == item["item_id"]
        and task.get("phase") == phase
        and task.get("state") in {"PENDING", "LEASED"}
    ]
    if active:
        return active[0]
    attempts = item.setdefault("phase_attempts", {})
    attempt = int(attempts.get(phase, 0)) + 1
    attempts[phase] = attempt
    role = PHASE_ROLES[phase]
    actor = run["review_policy"]["roles"][role]
    task_id = task_id_for(item, phase, attempt)
    task = {
        "task_id": task_id,
        "item_id": item["item_id"],
        "phase": phase,
        "attempt": attempt,
        "role": role,
        "assigned_actor": actor,
        "state": "PENDING",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "lease": None,
        "lease_count": 0,
        "release_count": 0,
        "last_error": None,
        "dispatch": [],
        "result_step_id": None,
        "instruction": PHASE_INSTRUCTIONS[phase],
    }
    run.setdefault("tasks", {})[task_id] = task
    run.setdefault("task_order", []).append(task_id)
    return task


def sync_item_tasks(run: dict[str, Any], item: dict[str, Any]) -> dict[str, Any] | None:
    next_phase = item.get("next_phase")
    for task in run.get("tasks", {}).values():
        if task.get("item_id") != item["item_id"] or task.get("state") not in {"PENDING", "LEASED"}:
            continue
        if task.get("phase") != next_phase:
            task["state"] = "CANCELLED"
            task["updated_at"] = utc_now()
            task["lease"] = None
    return enqueue_next_task(run, item) if next_phase else None


def start_run(
    intent: str,
    runs_root: Path,
    roots: list[dict[str, str]],
    run_id: str | None = None,
    role_actors: dict[str, str] | None = None,
    allow_single_agent: bool = False,
) -> Path:
    normalized_roots = [
        {"name": str(root["name"]), "path": str(Path(root["path"]).expanduser().resolve())} for root in roots
    ]
    scope = resolve_scope(intent, normalized_roots)
    identifier = run_id or make_run_id(intent)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", identifier) or identifier in {".", ".."}:
        raise ValueError("run id may contain only letters, digits, dot, underscore, and hyphen")
    root = runs_root.expanduser().resolve()
    requested_run_dir = root / identifier
    if requested_run_dir.is_symlink():
        raise ValueError("run directory must not be a symlink")
    run_dir = requested_run_dir.resolve()
    if run_dir.parent != root or run_dir.name != identifier:
        raise ValueError("run id must resolve directly under runs root")
    with locked_run(run_dir):
        control_key = initialize_control_key(run_dir)
        if (run_dir / "run.json").exists():
            existing = load_run(run_dir)
            if existing.get("intent") != intent:
                raise ValueError(f"run id already exists for a different intent: {identifier}")
            return run_dir
        inventory = incremental_inventory(scope["targets"], root, identifier)
        items = [item_for_target(index, target) for index, target in enumerate(inventory["changed_skills"], start=1)]
        now = utc_now()
        run: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "run_id": identifier,
            "intent": intent,
            "created_at": now,
            "updated_at": now,
            "revision": 1,
            "state": "DISCOVERING" if items else "AGGREGATING",
            "configured_roots": normalized_roots,
            "scope": scope,
            "inventory": inventory,
            "items": items,
            "steps": {},
            "review_policy": role_policy(role_actors, allow_single_agent=allow_single_agent),
            "tasks": {},
            "task_order": [],
            "reports": [],
            "latest_report": None,
            "approval": None,
            "worker_identities": None,
            "control": {
                "journal_attestation": "hmac-sha256",
                "attestation_key_sha256": sha256(control_key),
                "worker_key_readable": False,
            },
            "boundaries": {
                "candidate_only": True,
                "formal_write_requires_user_approval": True,
                "promotion_requires_user_approval": True,
                "credential_or_login_requires_user_approval": True,
                "live_validation_requires_user_approval": True,
                "persistent_control_plane_change_requires_user_approval": True,
            },
        }
        for item in items:
            enqueue_next_task(run, item)
        commit_run(
            run_dir,
            run,
            "run_started",
            {
                "run_id": identifier,
                "intent_hash": sha256(intent.encode("utf-8")),
                "scope": scope,
                "inventory_counts": inventory["counts"],
                "task_ids": list(run["task_order"]),
                "boundary": "candidate-only; stop before formal promotion",
            },
        )
    return run_dir


def find_item(run: dict[str, Any], item_id: str) -> dict[str, Any]:
    for item in run.get("items", []):
        if item.get("item_id") == item_id.upper():
            return item
    raise ValueError(f"unknown item id: {item_id}")


def derive_work_state(run: dict[str, Any]) -> str:
    statuses = {str(item.get("status")) for item in run.get("items", [])}
    if statuses and statuses <= TERMINAL_ITEM_STATES:
        return "AGGREGATING"
    if "REWORK_REQUIRED" in statuses:
        return "REWORKING"
    if statuses == {"PENDING"}:
        return "DISCOVERING"
    return "WORKING"


def task_payload(run: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    item = find_item(run, str(task["item_id"]))
    identity = (run.get("worker_identities") or {}).get(str(task.get("assigned_actor")))
    return {
        **task,
        "run_id": run["run_id"],
        "scope_revision": run["scope"]["revision"],
        "run_dir_hint": f"runs/{run['run_id']}",
        "item": {
            key: item.get(key)
            for key in (
                "item_id",
                "target",
                "target_path",
                "root_name",
                "relative_path",
                "skill_name",
                "source_tree_hash",
                "change_type",
                "is_symlink",
                "status",
                "candidate_id",
                "candidate_path",
                "evidence",
                "blockers",
            )
        },
        "boundaries": run["boundaries"],
        "executor_identity": identity,
    }


def reclaim_expired_leases(run: dict[str, Any], now: datetime) -> list[str]:
    reclaimed: list[str] = []
    for task in run.get("tasks", {}).values():
        if task.get("state") != "LEASED" or not isinstance(task.get("lease"), dict):
            continue
        try:
            expires_at = parse_timestamp(str(task["lease"]["expires_at"]))
        except (KeyError, TypeError, ValueError):
            expires_at = now
        if expires_at <= now:
            task["state"] = "PENDING"
            task["lease"] = None
            task["updated_at"] = utc_now()
            task["last_error"] = "lease_expired_recovered"
            reclaimed.append(str(task["task_id"]))
    return reclaimed


def claim_task(
    run_dir: Path, actor: str, lease_seconds: int = 600, item_id: str | None = None
) -> dict[str, Any] | None:
    actor = actor.strip()
    if not actor:
        raise ValueError("actor is required")
    if lease_seconds < 30 or lease_seconds > 86400:
        raise ValueError("lease_seconds must be between 30 and 86400")
    with locked_run(run_dir):
        run = load_run(run_dir)
        now = datetime.now(timezone.utc)
        reclaimed = reclaim_expired_leases(run, now)
        existing = next(
            (
                task
                for task in run.get("tasks", {}).values()
                if task.get("state") == "LEASED"
                and isinstance(task.get("lease"), dict)
                and task["lease"].get("holder") == actor
                and (item_id is None or task.get("item_id") == item_id.upper())
            ),
            None,
        )
        if existing:
            return task_payload(run, existing)
        task = next(
            (
                run["tasks"][task_id]
                for task_id in run.get("task_order", [])
                if run["tasks"][task_id].get("state") == "PENDING"
                and run["tasks"][task_id].get("assigned_actor") == actor
                and (item_id is None or run["tasks"][task_id].get("item_id") == item_id.upper())
            ),
            None,
        )
        if not task:
            if reclaimed:
                run["revision"] = int(run.get("revision", 0)) + 1
                run["updated_at"] = utc_now()
                commit_run(run_dir, run, "expired_leases_recovered", {"task_ids": reclaimed})
            return None
        token = hashlib.sha256(os.urandom(32)).hexdigest()
        task["state"] = "LEASED"
        task["lease_count"] = int(task.get("lease_count", 0)) + 1
        task["lease"] = {
            "holder": actor,
            "token": token,
            "claimed_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=lease_seconds)).isoformat(),
        }
        task["updated_at"] = utc_now()
        run["revision"] = int(run.get("revision", 0)) + 1
        run["updated_at"] = utc_now()
        commit_run(
            run_dir,
            run,
            "task_claimed",
            {"task_id": task["task_id"], "actor": actor, "lease_seconds": lease_seconds, "reclaimed": reclaimed},
        )
        return task_payload(run, task)


def validate_task_lease(task: dict[str, Any], actor: str, lease_token: str) -> None:
    lease = task.get("lease")
    if task.get("state") != "LEASED" or not isinstance(lease, dict):
        raise ValueError("task is not leased")
    if lease.get("holder") != actor or lease.get("token") != lease_token:
        raise ValueError("task lease holder or token mismatch")
    if parse_timestamp(str(lease.get("expires_at"))) <= datetime.now(timezone.utc):
        raise ValueError("task lease expired")


def heartbeat_task(run_dir: Path, task_id: str, actor: str, lease_token: str, lease_seconds: int = 600) -> dict[str, Any]:
    if lease_seconds < 30 or lease_seconds > 86400:
        raise ValueError("lease_seconds must be between 30 and 86400")
    with locked_run(run_dir):
        run = load_run(run_dir)
        task = run.get("tasks", {}).get(task_id)
        if not task:
            raise ValueError(f"unknown task id: {task_id}")
        validate_task_lease(task, actor, lease_token)
        task["lease"]["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
        task["updated_at"] = utc_now()
        run["revision"] = int(run.get("revision", 0)) + 1
        run["updated_at"] = utc_now()
        commit_run(run_dir, run, "task_heartbeat", {"task_id": task_id, "actor": actor})
        return task_payload(run, task)


def release_task(
    run_dir: Path,
    task_id: str,
    actor: str,
    lease_token: str,
    error: str,
    *,
    retryable: bool = True,
    max_releases: int = 3,
) -> dict[str, Any]:
    with locked_run(run_dir):
        run = load_run(run_dir)
        task = run.get("tasks", {}).get(task_id)
        if not task:
            raise ValueError(f"unknown task id: {task_id}")
        validate_task_lease(task, actor, lease_token)
        task["release_count"] = int(task.get("release_count", 0)) + 1
        task["last_error"] = error.strip() or "worker_released_without_reason"
        task["lease"] = None
        task["updated_at"] = utc_now()
        item = find_item(run, str(task["item_id"]))
        coordinator_actor = run["review_policy"]["roles"]["coordinator"]
        exhausted_at_coordinator = retryable and task["release_count"] >= max_releases and actor == coordinator_actor
        if not retryable or exhausted_at_coordinator:
            task["state"] = "COMPLETED"
            item["status"] = "BLOCKED"
            item["next_phase"] = None
            item["disposition"] = "blocked"
            item["approval_required"] = False
            item["summary"] = f"{task['phase']} blocked: {task['last_error']}"
            item.setdefault("blockers", []).append(task["last_error"])
            step_id = f"{task_id.replace(':', '-')}-blocked"
            identity = (run.get("worker_identities") or {}).get(actor, {})
            step_payload = {
                "step_id": step_id,
                "item_id": item["item_id"],
                "actor": actor,
                "phase": task["phase"],
                "step_status": "blocked",
                "item_status": "BLOCKED",
                "candidate_id": item.get("candidate_id"),
                "candidate_path": item.get("candidate_path"),
                "patch_path": item.get("patch_path"),
                "patch_hash": item.get("patch_hash"),
                "summary": item["summary"],
                "disposition": "blocked",
                "evidence": [],
                "blockers": [task["last_error"]],
                "task_id": task_id,
                "executor_principal": identity.get("principal_id"),
                "adapter_fingerprint": identity.get("adapter_fingerprint"),
                "candidate_tree_hash": (
                    tree_hash(Path(str(item["candidate_path"])).expanduser().resolve())
                    if item.get("candidate_path")
                    else None
                ),
            }
            step_payload_hash = sha256(step_payload)
            run.setdefault("steps", {})[step_id] = {
                **step_payload,
                "payload_hash": step_payload_hash,
                "recorded_at": utc_now(),
            }
            item.setdefault("steps", []).append(step_id)
            task["result_step_id"] = step_id
            sync_item_tasks(run, item)
        else:
            task["state"] = "PENDING"
            if task["release_count"] >= max_releases:
                task["role"] = "coordinator"
                task["assigned_actor"] = coordinator_actor
                task["escalated_from_actor"] = actor
        run["state"] = derive_work_state(run)
        run["revision"] = int(run.get("revision", 0)) + 1
        run["updated_at"] = utc_now()
        commit_run(
            run_dir,
            run,
            "task_released",
            {
                "task_id": task_id,
                "actor": actor,
                "retryable": retryable,
                "release_count": task["release_count"],
                "assigned_actor": task.get("assigned_actor"),
                "error": task["last_error"],
            },
        )
        return task_payload(run, task)


def record_task_dispatch(run_dir: Path, task_id: str, channel: str, message_ref: str) -> dict[str, Any]:
    if not channel.strip() or not message_ref.strip():
        raise ValueError("channel and message_ref are required")
    with locked_run(run_dir):
        run = load_run(run_dir)
        task = run.get("tasks", {}).get(task_id)
        if not task:
            raise ValueError(f"unknown task id: {task_id}")
        dispatch = {"channel": channel.strip(), "message_ref": message_ref.strip(), "ts": utc_now()}
        if dispatch not in task.setdefault("dispatch", []):
            task["dispatch"].append(dispatch)
            task["updated_at"] = utc_now()
            run["revision"] = int(run.get("revision", 0)) + 1
            run["updated_at"] = utc_now()
            commit_run(run_dir, run, "task_dispatched", {"task_id": task_id, **dispatch})
        return task_payload(run, task)


def validate_step_outcome(phase: str, step_status: str, item_status: str | None) -> str:
    normalized = step_status.strip().casefold()
    if normalized not in STEP_STATUSES:
        raise ValueError("step_status must be one of: " + ", ".join(sorted(STEP_STATUSES)))
    if item_status and phase in PHASE_ITEM_STATES and item_status not in PHASE_ITEM_STATES[phase]:
        raise ValueError(f"phase {phase} cannot produce item status {item_status}")
    if item_status in PASS_ITEM_STATES and normalized != "pass":
        raise ValueError(f"item status {item_status} requires step_status=pass")
    if item_status == "REWORK_REQUIRED" and normalized not in {"hold", "fail"}:
        raise ValueError("REWORK_REQUIRED requires step_status=hold or fail")
    if item_status == "BLOCKED" and normalized not in {"blocked", "fail"}:
        raise ValueError("BLOCKED requires step_status=blocked or fail")
    if normalized == "pass" and item_status in {"REWORK_REQUIRED", "BLOCKED"}:
        raise ValueError("step_status=pass cannot advance a failed or blocked result")
    return normalized


def evidence_records(
    run_dir: Path,
    raw_evidence: list[str],
    candidate_roots: list[Path],
) -> list[dict[str, str]]:
    allowed_roots = [run_dir.resolve(), *(root.resolve() for root in candidate_roots)]
    records: list[dict[str, str]] = []
    for raw in raw_evidence:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("evidence paths must be non-empty strings")
        requested = Path(raw).expanduser()
        choices = [requested.resolve()] if requested.is_absolute() else [
            (run_dir / requested).resolve(),
            *((root / requested).resolve() for root in candidate_roots),
        ]
        path = next((choice for choice in choices if choice.is_file()), None)
        if path is None:
            raise ValueError(f"evidence file does not exist: {raw}")
        if not any(path_is_inside(path, root) for root in allowed_roots):
            raise ValueError(f"evidence file is outside the run/candidate boundary: {path}")
        record = {"path": str(path), "sha256": sha256(path.read_bytes())}
        if record not in records:
            records.append(record)
    return records


def validate_patch_for_target(target: Path, patch: Path) -> None:
    if not target.is_dir():
        raise ValueError("candidate patch target must be an existing directory")
    completed = subprocess.run(
        ["git", "-C", str(target), "apply", "--check", str(patch)],
        text=True,
        capture_output=True,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or "patch does not apply").strip().splitlines()
        raise ValueError("candidate patch does not match item target: " + " | ".join(detail[:4]))


def record_step(
    run_dir: Path,
    *,
    step_id: str,
    item_id: str,
    actor: str,
    phase: str,
    step_status: str,
    item_status: str | None = None,
    candidate_id: str | None = None,
    candidate_path: str | None = None,
    summary: str | None = None,
    disposition: str | None = None,
    evidence: list[str] | None = None,
    blockers: list[str] | None = None,
    task_id: str | None = None,
    lease_token: str | None = None,
    executor_principal: str | None = None,
    adapter_fingerprint: str | None = None,
    candidate_tree_hash: str | None = None,
) -> dict[str, Any]:
    if not step_id.strip() or not actor.strip() or not phase.strip():
        raise ValueError("step_id, actor, and phase are required")
    if item_status and item_status not in ITEM_STATES:
        raise ValueError(f"invalid item status: {item_status}")
    if disposition and disposition not in {"promotion", "report_only", "no_op", "blocked"}:
        raise ValueError(f"invalid disposition: {disposition}")
    normalized_step_status = validate_step_outcome(phase, step_status, item_status)
    resolved_candidate: str | None = None
    patch_path: str | None = None
    patch_hash: str | None = None
    if candidate_path and phase not in {"candidate", "candidate_rework"}:
        raise ValueError("candidate_path may only be supplied by candidate or candidate_rework phases")
    if candidate_path:
        candidate_root = Path(candidate_path).expanduser().resolve()
        patch = candidate_root / "PATCH.diff"
        if not candidate_root.is_dir() or not patch.is_file():
            raise ValueError("candidate_path must be a directory containing PATCH.diff")
        if not patch.read_bytes().strip():
            raise ValueError("candidate PATCH.diff must be non-empty")
        resolved_candidate = str(candidate_root)
        patch_path = str(patch)
        patch_hash = sha256(patch.read_bytes())
    with locked_run(run_dir):
        run = load_run(run_dir)
        item = find_item(run, item_id)
        candidate_roots = [
            Path(path).expanduser().resolve()
            for path in (resolved_candidate, item.get("candidate_path"))
            if path
        ]
        if resolved_candidate:
            target = Path(str(item["target_path"])).expanduser().resolve()
            candidate_root = Path(resolved_candidate)
            identity = (run.get("worker_identities") or {}).get(actor)
            if not isinstance(identity, dict):
                raise ValueError(f"worker identity is not bound for actor: {actor}")
            authorized_candidate_roots = [
                Path(path).expanduser().resolve() for path in identity.get("write_roots", [])
            ]
            if path_is_inside(candidate_root, run_dir.resolve()) or not any(
                path_is_inside(candidate_root, root) for root in authorized_candidate_roots
            ):
                raise ValueError("candidate_path is outside the bound candidate write_roots")
            prior_candidate_paths = {
                str(Path(path).expanduser().resolve())
                for existing_step_id, existing_step in run.get("steps", {}).items()
                if existing_step_id != step_id
                for path in [existing_step.get("candidate_path")]
                if path
            }
            if str(candidate_root) in prior_candidate_paths:
                raise ValueError("candidate revisions must use a new immutable candidate_path")
            formal_roots = [Path(str(root["path"])).expanduser().resolve() for root in run["configured_roots"]]
            if any(
                path_is_inside(candidate_root, root) or path_is_inside(root, candidate_root)
                for root in formal_roots
            ):
                raise ValueError("candidate_path and all configured formal roots must be isolated")
            validate_patch_for_target(target, Path(str(patch_path)))
        current_candidate_path = resolved_candidate or item.get("candidate_path")
        current_candidate_hash = (
            tree_hash(Path(str(current_candidate_path)).expanduser().resolve())
            if current_candidate_path
            else None
        )
        if candidate_tree_hash and candidate_tree_hash != current_candidate_hash:
            raise ValueError("candidate tree hash differs from the durable candidate revision")
        if task_id and phase in {"audit", "independent_verify", "boundary_review", "aggregate"}:
            if not candidate_tree_hash:
                raise ValueError(f"{phase} task requires an immutable candidate tree hash")
        bound_candidate_hash = candidate_tree_hash or current_candidate_hash
        raw_evidence = list(evidence or [])
        if resolved_candidate and patch_path and patch_path not in raw_evidence:
            raw_evidence.append(patch_path)
        captured_evidence = evidence_records(run_dir, raw_evidence, candidate_roots)
        if item_status in PASS_ITEM_STATES and not captured_evidence:
            raise ValueError(f"{item_status} requires at least one existing hash-bound evidence file")
        payload = {
            "step_id": step_id,
            "item_id": item_id.upper(),
            "actor": actor,
            "phase": phase,
            "step_status": normalized_step_status,
            "item_status": item_status,
            "candidate_id": candidate_id,
            "candidate_path": resolved_candidate,
            "patch_path": patch_path,
            "patch_hash": patch_hash,
            "summary": summary,
            "disposition": disposition,
            "evidence": captured_evidence,
            "blockers": blockers or [],
            "task_id": task_id,
            "executor_principal": executor_principal,
            "adapter_fingerprint": adapter_fingerprint,
            "candidate_tree_hash": bound_candidate_hash,
        }
        payload_hash = sha256(payload)
        existing = run.get("steps", {}).get(step_id)
        if existing:
            if existing.get("payload_hash") != payload_hash:
                raise ValueError(f"step id collision with different payload: {step_id}")
            return {"idempotent": True, "run": run, "step": existing}
        task: dict[str, Any] | None = None
        if task_id:
            task = run.get("tasks", {}).get(task_id)
            if not task:
                raise ValueError(f"unknown task id: {task_id}")
            if not lease_token:
                raise ValueError("lease_token is required when task_id is provided")
            validate_task_lease(task, actor, lease_token)
            if task.get("item_id") != item_id.upper() or task.get("phase") != phase:
                raise ValueError("task item or phase does not match the recorded step")
            if task.get("escalated_from_actor") and item_status != "BLOCKED":
                raise ValueError("coordinator may only close an exhausted delegated task as BLOCKED")
            identity = (run.get("worker_identities") or {}).get(actor)
            if not isinstance(identity, dict):
                raise ValueError(f"worker identity is not bound for actor: {actor}")
            if (
                executor_principal != identity.get("principal_id")
                or adapter_fingerprint != identity.get("adapter_fingerprint")
            ):
                raise ValueError("step executor identity differs from the bound worker adapter")
        current_status = str(item.get("status"))
        if item_status and item_status != current_status:
            allowed = ALLOWED_ITEM_TRANSITIONS.get(current_status, set())
            if item_status not in allowed:
                raise ValueError(f"invalid item transition: {current_status} -> {item_status}")
        if item_status == "APPROVAL_READY" and (disposition or item.get("disposition")) != "promotion":
            raise ValueError("APPROVAL_READY requires disposition=promotion")
        if item_status == "APPROVAL_READY" and not (candidate_id or item.get("candidate_id")):
            raise ValueError("APPROVAL_READY requires candidate_id")
        if item_status == "APPROVAL_READY" and not (summary or item.get("summary")):
            raise ValueError("APPROVAL_READY requires a plain-language summary")

        step = {**payload, "payload_hash": payload_hash, "recorded_at": utc_now()}
        run.setdefault("steps", {})[step_id] = step
        item.setdefault("steps", []).append(step_id)
        item.setdefault("evidence", []).extend(captured_evidence)
        item.setdefault("blockers", []).extend(blockers or [])
        if item_status:
            item["status"] = item_status
            item["next_phase"] = NEXT_PHASE.get(item_status)
        if candidate_id is not None:
            item["candidate_id"] = candidate_id
        if resolved_candidate is not None:
            item["candidate_path"] = resolved_candidate
            item["patch_path"] = patch_path
            item["patch_hash"] = patch_hash
            target = Path(str(item["target_path"])).expanduser().resolve()
            if target.is_dir():
                item["target_baseline_hash"] = tree_hash(target)
        if summary is not None:
            item["summary"] = summary
        if disposition is not None:
            item["disposition"] = disposition
            item["approval_required"] = disposition == "promotion"
        if item["status"] == "CLOSED_REPORT_ONLY":
            item["disposition"] = "report_only"
            item["approval_required"] = False
        elif item["status"] == "CLOSED_NOOP":
            item["disposition"] = "no_op"
            item["approval_required"] = False
        elif item["status"] == "BLOCKED":
            item["disposition"] = "blocked"
            item["approval_required"] = False

        if task:
            task["state"] = "COMPLETED"
            task["lease"] = None
            task["result_step_id"] = step_id
            task["updated_at"] = utc_now()
        next_task = sync_item_tasks(run, item)

        run["state"] = derive_work_state(run)
        run["revision"] = int(run.get("revision", 0)) + 1
        run["updated_at"] = utc_now()
        commit_run(
            run_dir,
            run,
            "step_recorded",
            {
                "payload": payload,
                "payload_hash": payload_hash,
                "completed_task_id": task_id,
                "next_task_id": next_task.get("task_id") if next_task else None,
            },
        )
        return {"idempotent": False, "run": run, "step": step}


def report_hash(report: dict[str, Any]) -> str:
    payload = dict(report)
    payload.pop("report_hash", None)
    payload.pop("plain_report_sha256", None)
    payload.pop("delivery", None)
    return sha256(payload)


def render_plain_report(report: dict[str, Any]) -> str:
    review_mode = str(report.get("review_policy", {}).get("mode") or "configured_multi_agent")
    process_label = (
        "用户授权的单代理席位"
        if review_mode == "user_authorized_single_agent"
        else "配置的多代理席位"
    )
    completion_line = (
        f"{process_label}已把本轮各项推进到合法终态并完成汇总。下面只列需要你决定的正式变更；未列出的项不会被晋升。"
        if report["items"]
        else "本轮技能级增量扫描没有发现新增、修改或删除项，因此无需建立候选，也没有正式变更需要批准。"
    )
    lines = [
        f"# Sublation 交付报告 {report['run_id']} / v{report['report_version']}",
        "",
        f"结果：`{report['state']}`",
        f"批准码：`{report['approval_code']}`",
        "",
        completion_line,
        "",
        "## 需要批准",
        "",
    ]
    if report["approval_items"]:
        for item in report["approval_items"]:
            lines.append(f"- `{item['item_id']}` {item['target']}：{item['summary']}（候选 `{item['candidate_id']}`）")
    else:
        lines.append("- 无。本轮只有 no-op / report-only 项，已经在候选层闭环。")
    lines.extend(["", "## 其他结果", ""])
    for item in report["items"]:
        if item["item_id"] not in {entry["item_id"] for entry in report["approval_items"]}:
            lines.append(f"- `{item['item_id']}` {item['target']}：{item['status']}。{item['summary']}")
    if all(item["item_id"] in {entry["item_id"] for entry in report["approval_items"]} for item in report["items"]):
        lines.append("- 无额外项目。")
    if report["approval_items"]:
        lines.extend(
            [
                "",
                "## 你的回复",
                "",
                f"请带批准码回复，例如“{report['approval_code']} 全部批准”或“{report['approval_code']} A1 批准，A2 暂缓”。未明确点到的项目保持待定。",
                "",
                f"报告绑定：`v{report['report_version']}` / `{report['report_hash']}` / scope revision `{report['scope_revision']}`。",
                "",
                "此报告本身不授权正式写入；回执解析后仍只生成精确授权范围，正式执行另行保留授权证据。",
                "",
            ]
        )
    else:
        lines.extend(["", "本轮没有晋升批准项，无需回复批准。", ""])
    return "\n".join(lines)


def verify_plain_report(run_dir: Path, report: dict[str, Any]) -> dict[str, str]:
    if report.get("report_hash") != report_hash(report):
        raise ValueError("report hash verification failed")
    rendered = render_plain_report(report).encode("utf-8")
    expected_hash = sha256(rendered)
    if report.get("plain_report_sha256") != expected_hash:
        raise ValueError("plain report body hash verification failed")
    path = run_dir.expanduser().resolve() / f"report-v{int(report['report_version'])}.md"
    if not path.is_file() or path.read_bytes() != rendered:
        raise ValueError("plain report body differs from its report snapshot")
    return {"path": str(path), "sha256": expected_hash}


def evidence_integrity_findings(run_dir: Path, run: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    candidate_roots = sorted(
        {
            Path(str(path)).expanduser().resolve()
            for path in [
                *(item.get("candidate_path") for item in run.get("items", [])),
                *(step.get("candidate_path") for step in run.get("steps", {}).values()),
            ]
            if path
        },
        key=str,
    )
    allowed_roots = [run_dir.resolve(), *candidate_roots]
    for step_id, step in run.get("steps", {}).items():
        records = step.get("evidence")
        if step.get("item_status") in PASS_ITEM_STATES and not records:
            findings.append(f"{step_id} lacks hash-bound evidence")
            continue
        if not isinstance(records, list):
            findings.append(f"{step_id} evidence is not an array")
            continue
        for index, record in enumerate(records, start=1):
            if not isinstance(record, dict) or not record.get("path") or not record.get("sha256"):
                findings.append(f"{step_id} evidence #{index} is not a path/hash record")
                continue
            path = Path(str(record["path"])).expanduser().resolve()
            if not path.is_file():
                findings.append(f"{step_id} evidence is missing: {path}")
            elif not any(path_is_inside(path, root) for root in allowed_roots):
                findings.append(f"{step_id} evidence escaped the run/candidate boundary: {path}")
            elif record["sha256"] != sha256(path.read_bytes()):
                findings.append(f"{step_id} evidence hash drifted: {path}")
    return findings


def orchestration_integrity_findings(run_dir: Path, run: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    identities = run.get("worker_identities")
    roles = run.get("review_policy", {}).get("roles", {})
    if not isinstance(identities, dict):
        findings.append("run has no durable worker identity bindings")
        identities = {}
    elif run.get("review_policy", {}).get("independence_required"):
        independent = [roles.get(role) for role in ("builder", "independent_verifier", "reviewer")]
        bound = [identities.get(str(actor)) for actor in independent]
        if any(not isinstance(identity, dict) for identity in bound):
            findings.append("one or more independent roles lack a bound worker identity")
        else:
            principals = {identity.get("principal_id") for identity in bound}
            fingerprints = {identity.get("adapter_fingerprint") for identity in bound}
            if len(principals) != 3 or len(fingerprints) != 3:
                findings.append("independent roles do not have three distinct principals and adapters")
            builder = identities.get(str(roles.get("builder"))) or {}
            if not builder.get("write_roots"):
                findings.append("builder identity has no isolated candidate write root")
            for role in ("independent_verifier", "reviewer"):
                identity = identities.get(str(roles.get(role))) or {}
                if identity.get("write_roots"):
                    findings.append(f"independent {role} identity retained candidate write access")
    tasks = list(run.get("tasks", {}).values())
    for item in run.get("items", []):
        item_tasks = [task for task in tasks if task.get("item_id") == item.get("item_id")]
        active = [task["task_id"] for task in item_tasks if task.get("state") in {"PENDING", "LEASED"}]
        if active:
            findings.append(f"{item['item_id']} still has active tasks: {', '.join(active)}")
        completed = [task for task in item_tasks if task.get("state") == "COMPLETED" and task.get("result_step_id")]
        if not completed:
            findings.append(f"{item['item_id']} has no completed durable task")
            continue
        for task in completed:
            step = run.get("steps", {}).get(task["result_step_id"])
            if not step:
                findings.append(f"{task['task_id']} references a missing result step")
                continue
            if step.get("task_id") != task.get("task_id"):
                findings.append(f"{task['task_id']} result step is not task-bound")
            if step.get("actor") != task.get("assigned_actor"):
                findings.append(f"{task['task_id']} was completed by the wrong actor")
            identity = identities.get(str(task.get("assigned_actor")))
            if not isinstance(identity, dict) or any(
                step.get(field) != identity.get(expected)
                for field, expected in (
                    ("executor_principal", "principal_id"),
                    ("adapter_fingerprint", "adapter_fingerprint"),
                )
            ):
                findings.append(f"{task['task_id']} lacks the bound executor identity proof")
        if item.get("status") == "APPROVAL_READY":
            completed_roles = {task.get("role") for task in completed}
            required_roles = {"builder", "independent_verifier", "reviewer", "coordinator"}
            missing_roles = sorted(required_roles - completed_roles)
            if missing_roles:
                findings.append(f"{item['item_id']} lacks completed roles: {', '.join(missing_roles)}")
            candidate_path = item.get("candidate_path")
            if not candidate_path:
                findings.append(f"{item['item_id']} lacks a current candidate revision")
                continue
            current_candidate_hash = tree_hash(Path(str(candidate_path)).expanduser().resolve())
            ordered_step_ids = list(item.get("steps") or [])
            candidate_indexes = [
                index
                for index, step_id in enumerate(ordered_step_ids)
                for step in [run.get("steps", {}).get(step_id)]
                if isinstance(step, dict)
                and step.get("phase") in {"candidate", "candidate_rework"}
                and step.get("candidate_path") == candidate_path
                and step.get("candidate_tree_hash") == current_candidate_hash
            ]
            if not candidate_indexes:
                findings.append(f"{item['item_id']} current candidate lacks a hash-bound builder step")
                continue
            candidate_index = max(candidate_indexes)
            for phase in ("audit", "independent_verify", "boundary_review", "aggregate"):
                matching = [
                    run.get("steps", {}).get(step_id)
                    for step_id in ordered_step_ids[candidate_index + 1 :]
                ]
                matching = [
                    step
                    for step in matching
                    if isinstance(step, dict)
                    and step.get("phase") == phase
                    and step.get("step_status") == "pass"
                    and step.get("candidate_tree_hash") == current_candidate_hash
                ]
                if not matching:
                    findings.append(
                        f"{item['item_id']} {phase} is not bound to the current candidate tree"
                    )
    findings.extend(evidence_integrity_findings(run_dir, run))
    return findings


def finalize_report(run_dir: Path) -> dict[str, Any]:
    with locked_run(run_dir):
        run = load_run(run_dir)
        nonterminal = [item["item_id"] for item in run["items"] if item.get("status") not in TERMINAL_ITEM_STATES]
        if nonterminal:
            raise ValueError("cannot finalize; nonterminal items: " + ", ".join(nonterminal))
        missing_summaries = [item["item_id"] for item in run["items"] if not str(item.get("summary") or "").strip()]
        if missing_summaries:
            raise ValueError("cannot finalize; missing plain-language summaries: " + ", ".join(missing_summaries))
        approval_items = [item for item in run["items"] if item.get("status") == "APPROVAL_READY"]
        incomplete_approvals = [
            item["item_id"]
            for item in approval_items
            if not all(
                item.get(field)
                for field in ("candidate_id", "candidate_path", "patch_path", "patch_hash", "target_baseline_hash")
            )
        ]
        if incomplete_approvals:
            raise ValueError("cannot finalize; approval items lack executable evidence: " + ", ".join(incomplete_approvals))
        drifted_targets = [
            item["item_id"]
            for item in approval_items
            if tree_hash(Path(str(item["target_path"])).expanduser().resolve())
            != item.get("target_baseline_hash")
        ]
        if drifted_targets:
            raise ValueError(
                "cannot finalize; approval target baseline drifted: " + ", ".join(drifted_targets)
            )
        orchestration_findings = orchestration_integrity_findings(run_dir, run)
        if orchestration_findings:
            raise ValueError("cannot finalize; orchestration integrity failed: " + "; ".join(orchestration_findings))
        blocked_items = [item for item in run["items"] if item.get("status") == "BLOCKED"]
        if approval_items and blocked_items:
            state = "PARTIAL"
        elif approval_items:
            state = "USER_DECISION_REQUIRED"
        elif blocked_items:
            state = "BLOCKED"
        else:
            state = "CLOSED"
        item_fields = (
            "item_id",
            "target",
            "target_path",
            "source_tree_hash",
            "status",
            "candidate_id",
            "candidate_path",
            "patch_path",
            "patch_hash",
            "target_baseline_hash",
            "summary",
            "disposition",
            "approval_required",
            "evidence",
            "blockers",
        )
        items: list[dict[str, Any]] = []
        for item in run["items"]:
            snapshot = {key: item.get(key) for key in item_fields}
            candidate_path = item.get("candidate_path")
            snapshot["candidate_tree_hash"] = (
                tree_hash(Path(str(candidate_path)).expanduser().resolve()) if candidate_path else None
            )
            items.append(snapshot)
        approval_ids = {item["item_id"] for item in approval_items}
        approval_payload = []
        for snapshot in items:
            if snapshot["item_id"] not in approval_ids:
                continue
            approval_snapshot = {
                key: snapshot.get(key)
                for key in (
                    "item_id",
                    "target",
                    "target_path",
                    "source_tree_hash",
                    "candidate_id",
                    "candidate_path",
                    "candidate_tree_hash",
                    "patch_path",
                    "patch_hash",
                    "target_baseline_hash",
                    "summary",
                    "disposition",
                    "approval_required",
                )
            }
            approval_snapshot["approval_snapshot_hash"] = sha256(approval_snapshot)
            approval_payload.append(approval_snapshot)
        material_hash = sha256(
            {
                "scope_revision": run["scope"]["revision"],
                "state": state,
                "items": items,
                "approval_items": approval_payload,
                "review_policy": run["review_policy"],
                "worker_identities": run["worker_identities"],
                "boundary": "Candidate and evidence aggregation only; formal promotion requires user approval.",
            }
        )
        latest = run.get("latest_report")
        if isinstance(latest, dict) and latest.get("material_hash") == material_hash:
            existing_path = run_dir / f"report-v{int(latest['report_version'])}.json"
            existing_report = read_json(existing_path)
            verify_plain_report(run_dir, existing_report)
            return existing_report
        version = len(run.get("reports", [])) + 1
        report: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run["run_id"],
            "report_version": version,
            "scope_revision": run["scope"]["revision"],
            "generated_at": utc_now(),
            "state": state,
            "items": items,
            "approval_items": approval_payload,
            "review_policy": run["review_policy"],
            "worker_identities": run["worker_identities"],
            "boundary": "Candidate and evidence aggregation only; formal promotion requires user approval.",
            "material_hash": material_hash,
            "approval_code": "SR-" + sha256(
                {"run_id": run["run_id"], "report_version": version, "material_hash": material_hash}
            ).split(":", 1)[1][:8].upper(),
            "delivery": [],
        }
        report["report_hash"] = report_hash(report)
        markdown = render_plain_report(report)
        report["plain_report_sha256"] = sha256(markdown.encode("utf-8"))
        json_path = run_dir / f"report-v{version}.json"
        markdown_path = run_dir / f"report-v{version}.md"
        atomic_write_json(json_path, report)
        atomic_write_text(markdown_path, markdown)
        verify_plain_report(run_dir, report)
        report_summary = {
            "report_version": version,
            "scope_revision": report["scope_revision"],
            "report_hash": report["report_hash"],
            "plain_report_sha256": report["plain_report_sha256"],
            "material_hash": material_hash,
            "state": state,
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "delivery": [],
        }
        run.setdefault("reports", []).append(report_summary)
        run["latest_report"] = report_summary
        run["approval"] = None
        run["state"] = state
        run["revision"] = int(run.get("revision", 0)) + 1
        run["updated_at"] = utc_now()
        commit_run(
            run_dir,
            run,
            "report_finalized",
            {
                "report_version": version,
                "scope_revision": report["scope_revision"],
                "report_hash": report["report_hash"],
                "plain_report_sha256": report["plain_report_sha256"],
                "state": state,
                "approval_item_ids": [item["item_id"] for item in approval_items],
                "approval_items_hash": sha256(approval_payload),
            },
        )
        return report


def record_delivery(
    run_dir: Path,
    channel: str,
    message_ref: str,
    authorized_reply_senders: list[str],
    report_version: int | None = None,
    *,
    sender_actor: str,
    idempotency_key: str,
    adapter_evidence_path: str,
    report_body_hash: str,
    delivery_text_hash: str,
) -> dict[str, Any]:
    if not all(
        str(value or "").strip()
        for value in (channel, message_ref, sender_actor, idempotency_key, report_body_hash, delivery_text_hash)
    ):
        raise ValueError(
            "channel, message_ref, sender_actor, idempotency_key, report_body_hash, and delivery_text_hash are required"
        )
    senders = sorted({sender.strip() for sender in authorized_reply_senders if sender.strip()})
    if not senders:
        raise ValueError("at least one authorized reply sender is required")
    evidence_path = Path(adapter_evidence_path).expanduser().resolve()
    if not evidence_path.is_file() or not path_is_inside(evidence_path, run_dir.resolve()):
        raise ValueError("delivery adapter evidence must be an existing file inside the run directory")
    with locked_run(run_dir):
        run = load_run(run_dir)
        if not run.get("latest_report"):
            raise ValueError("no finalized report")
        version = report_version or int(run["latest_report"]["report_version"])
        if version != int(run["latest_report"]["report_version"]):
            raise ValueError("only the latest report may be delivered for approval")
        path = run_dir / f"report-v{version}.json"
        report = read_json(path)
        plain_report = verify_plain_report(run_dir, report)
        if report_body_hash != plain_report["sha256"]:
            raise ValueError("delivery report body hash differs from the finalized plain report")
        evidence_payload = read_json(evidence_path)
        expected_adapter_fields = {
            "message_ref": message_ref,
            "sender_actor": sender_actor,
            "report_body_hash": report_body_hash,
            "delivery_text_hash": delivery_text_hash,
        }
        if any(evidence_payload.get(key) != value for key, value in expected_adapter_fields.items()):
            raise ValueError("delivery adapter evidence fields differ from the delivery result")
        adapter_evidence = {"path": str(evidence_path), "sha256": sha256(evidence_path.read_bytes())}
        delivery = {
            "channel": channel,
            "message_ref": message_ref,
            "ts": utc_now(),
            "sender_actor": sender_actor,
            "idempotency_key": idempotency_key,
            "adapter_evidence": adapter_evidence,
            "report_body_hash": report_body_hash,
            "delivery_text_hash": delivery_text_hash,
            "authorized_reply_senders": senders,
        }
        existing = report.setdefault("delivery", [])
        duplicate = next(
            (item for item in existing if item.get("channel") == channel and item.get("message_ref") == message_ref),
            None,
        )
        if duplicate:
            stable_fields = {
                "authorized_reply_senders": senders,
                "sender_actor": sender_actor,
                "idempotency_key": idempotency_key,
                "adapter_evidence": adapter_evidence,
                "report_body_hash": report_body_hash,
                "delivery_text_hash": delivery_text_hash,
            }
            if any(duplicate.get(key) != value for key, value in stable_fields.items()):
                raise ValueError("delivery identity binding cannot change after publication")
            expected_journal_fields = {
                "report_version": version,
                "report_hash": report["report_hash"],
                "channel": channel,
                "message_ref": message_ref,
                "sender_actor": sender_actor,
                "idempotency_key": idempotency_key,
                "adapter_evidence": adapter_evidence,
                "report_body_hash": report_body_hash,
                "delivery_text_hash": delivery_text_hash,
                "authorized_reply_senders": senders,
            }
            journaled = any(
                entry.get("type") in {"report_delivered", "report_delivery_recovered"}
                and all(entry.get("payload", {}).get(key) == value for key, value in expected_journal_fields.items())
                for entry in verified_journal_entries(run_dir)
            )
            if run["latest_report"].get("delivery") != existing or not journaled:
                run["latest_report"]["delivery"] = existing
                run["reports"][-1]["delivery"] = existing
                run["revision"] = int(run.get("revision", 0)) + 1
                run["updated_at"] = utc_now()
                commit_run(
                    run_dir,
                    run,
                    "report_delivery_recovered",
                    {
                        "report_version": version,
                        "report_hash": report["report_hash"],
                        "channel": channel,
                        "message_ref": message_ref,
                        "sender_actor": sender_actor,
                        "idempotency_key": idempotency_key,
                        "adapter_evidence": adapter_evidence,
                        "report_body_hash": report_body_hash,
                        "delivery_text_hash": delivery_text_hash,
                        "authorized_reply_senders": senders,
                    },
                )
            return report
        existing.append(delivery)
        atomic_write_json(path, report)
        if os.environ.get("SUBLATION_TEST_CRASH_AFTER_DELIVERY_REPORT_WRITE") == "1":
            os._exit(98)
        run["latest_report"]["delivery"] = existing
        run["reports"][-1]["delivery"] = existing
        run["revision"] = int(run.get("revision", 0)) + 1
        run["updated_at"] = utc_now()
        commit_run(
            run_dir,
            run,
            "report_delivered",
            {
                "report_version": version,
                "report_hash": report["report_hash"],
                "channel": channel,
                "message_ref": message_ref,
                "sender_actor": sender_actor,
                "idempotency_key": idempotency_key,
                "adapter_evidence": adapter_evidence,
                "report_body_hash": report_body_hash,
                "delivery_text_hash": delivery_text_hash,
                "authorized_reply_senders": senders,
            },
        )
        return report


def status(run_dir: Path) -> dict[str, Any]:
    run = load_run(run_dir)
    journal = verify_journal(run_dir)
    tasks = [run["tasks"][task_id] for task_id in run.get("task_order", []) if task_id in run.get("tasks", {})]
    next_actions = [
        {
            "task_id": task["task_id"],
            "item_id": task["item_id"],
            "target": find_item(run, str(task["item_id"]))["target"],
            "phase": task["phase"],
            "role": task["role"],
            "assigned_actor": task["assigned_actor"],
            "state": task["state"],
            "lease": task.get("lease"),
        }
        for task in tasks
        if task.get("state") in {"PENDING", "LEASED"}
    ]
    return {
        "run_id": run["run_id"],
        "state": run["state"],
        "revision": run["revision"],
        "scope": run["scope"],
        "inventory": run.get("inventory"),
        "next_actions": next_actions,
        "task_counts": {state: sum(1 for task in tasks if task.get("state") == state) for state in sorted(TASK_STATES)},
        "review_policy": run.get("review_policy"),
        "worker_identities": run.get("worker_identities"),
        "latest_report": run.get("latest_report"),
        "approval": run.get("approval"),
        "journal": journal,
    }


def command_start(args: argparse.Namespace) -> int:
    roots = load_roots(args.root, args.roots_file)
    roles: dict[str, str] = {}
    for raw in args.role:
        role, separator, actor = raw.partition("=")
        if not separator:
            raise ValueError("roles must use ROLE=ACTOR")
        roles[role.strip()] = actor.strip()
    run_dir = start_run(
        args.intent,
        Path(args.runs_root),
        roots,
        args.run_id,
        roles,
        allow_single_agent=args.allow_single_agent,
    )
    print(json.dumps({"run_dir": str(run_dir), **status(run_dir)}, ensure_ascii=False, indent=2))
    return 0


def command_record(args: argparse.Namespace) -> int:
    result = record_step(
        Path(args.run_dir),
        step_id=args.step_id,
        item_id=args.item_id,
        actor=args.actor,
        phase=args.phase,
        step_status=args.step_status,
        item_status=args.item_status,
        candidate_id=args.candidate_id,
        candidate_path=args.candidate_path,
        summary=args.summary,
        disposition=args.disposition,
        evidence=args.evidence,
        blockers=args.blocker,
        task_id=args.task_id,
        lease_token=args.lease_token,
        executor_principal=args.executor_principal,
        adapter_fingerprint=args.adapter_fingerprint,
        candidate_tree_hash=args.candidate_tree_hash,
    )
    print(json.dumps({"idempotent": result["idempotent"], **status(Path(args.run_dir))}, ensure_ascii=False, indent=2))
    return 0


def command_report(args: argparse.Namespace) -> int:
    report = finalize_report(Path(args.run_dir))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def command_deliver(args: argparse.Namespace) -> int:
    report = record_delivery(
        Path(args.run_dir),
        args.channel,
        args.message_ref,
        args.authorized_reply_sender,
        args.report_version,
        sender_actor=args.sender_actor,
        idempotency_key=args.idempotency_key,
        adapter_evidence_path=args.adapter_evidence,
        report_body_hash=args.report_body_hash,
        delivery_text_hash=args.delivery_text_hash,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def command_status(args: argparse.Namespace) -> int:
    print(json.dumps(status(Path(args.run_dir)), ensure_ascii=False, indent=2))
    return 0


def command_claim(args: argparse.Namespace) -> int:
    task = claim_task(Path(args.run_dir), args.actor, args.lease_seconds, args.item_id)
    print(json.dumps({"task": task, **status(Path(args.run_dir))}, ensure_ascii=False, indent=2))
    return 0


def command_heartbeat(args: argparse.Namespace) -> int:
    task = heartbeat_task(Path(args.run_dir), args.task_id, args.actor, args.lease_token, args.lease_seconds)
    print(json.dumps({"task": task, **status(Path(args.run_dir))}, ensure_ascii=False, indent=2))
    return 0


def command_release(args: argparse.Namespace) -> int:
    task = release_task(
        Path(args.run_dir),
        args.task_id,
        args.actor,
        args.lease_token,
        args.error,
        retryable=not args.nonretryable,
        max_releases=args.max_releases,
    )
    print(json.dumps({"task": task, **status(Path(args.run_dir))}, ensure_ascii=False, indent=2))
    return 0


def command_dispatch(args: argparse.Namespace) -> int:
    task = record_task_dispatch(Path(args.run_dir), args.task_id, args.channel, args.message_ref)
    print(json.dumps({"task": task, **status(Path(args.run_dir))}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="create or resume a durable one-shot run")
    start.add_argument("--intent", required=True)
    start.add_argument("--runs-root", required=True)
    start.add_argument("--root", action="append", default=[], help="configured root as NAME=PATH")
    start.add_argument("--roots-file")
    start.add_argument("--run-id")
    start.add_argument("--role", action="append", default=[], help="role assignment as ROLE=ACTOR")
    start.add_argument(
        "--allow-single-agent",
        action="store_true",
        help="explicitly record user authorization for reduced-independence single-agent operation",
    )
    start.set_defaults(func=command_start)

    record = sub.add_parser("record", help="record one idempotent agent step")
    record.add_argument("--run-dir", required=True)
    record.add_argument("--step-id", required=True)
    record.add_argument("--item-id", required=True)
    record.add_argument("--actor", required=True)
    record.add_argument("--phase", required=True)
    record.add_argument("--step-status", required=True)
    record.add_argument("--item-status", choices=sorted(ITEM_STATES))
    record.add_argument("--candidate-id")
    record.add_argument("--candidate-path")
    record.add_argument("--summary")
    record.add_argument("--disposition", choices=["promotion", "report_only", "no_op", "blocked"])
    record.add_argument("--evidence", action="append", default=[])
    record.add_argument("--blocker", action="append", default=[])
    record.add_argument("--task-id")
    record.add_argument("--lease-token")
    record.add_argument("--executor-principal")
    record.add_argument("--adapter-fingerprint")
    record.add_argument("--candidate-tree-hash")
    record.set_defaults(func=command_record)

    claim = sub.add_parser("claim", help="claim the next durable task assigned to an actor")
    claim.add_argument("--run-dir", required=True)
    claim.add_argument("--actor", required=True)
    claim.add_argument("--lease-seconds", type=int, default=600)
    claim.add_argument("--item-id")
    claim.set_defaults(func=command_claim)

    heartbeat = sub.add_parser("heartbeat", help="extend a claimed task lease")
    heartbeat.add_argument("--run-dir", required=True)
    heartbeat.add_argument("--task-id", required=True)
    heartbeat.add_argument("--actor", required=True)
    heartbeat.add_argument("--lease-token", required=True)
    heartbeat.add_argument("--lease-seconds", type=int, default=600)
    heartbeat.set_defaults(func=command_heartbeat)

    release = sub.add_parser("release", help="release a failed task for retry or mark it blocked")
    release.add_argument("--run-dir", required=True)
    release.add_argument("--task-id", required=True)
    release.add_argument("--actor", required=True)
    release.add_argument("--lease-token", required=True)
    release.add_argument("--error", required=True)
    release.add_argument("--nonretryable", action="store_true")
    release.add_argument("--max-releases", type=int, default=3)
    release.set_defaults(func=command_release)

    dispatch = sub.add_parser("dispatch", help="record a channel-neutral task dispatch reference")
    dispatch.add_argument("--run-dir", required=True)
    dispatch.add_argument("--task-id", required=True)
    dispatch.add_argument("--channel", required=True)
    dispatch.add_argument("--message-ref", required=True)
    dispatch.set_defaults(func=command_dispatch)

    report = sub.add_parser("report", help="finalize a versioned plain-language approval report")
    report.add_argument("--run-dir", required=True)
    report.set_defaults(func=command_report)

    deliver = sub.add_parser("deliver", help="bind the latest report to any delivery channel")
    deliver.add_argument("--run-dir", required=True)
    deliver.add_argument("--channel", required=True)
    deliver.add_argument("--message-ref", required=True)
    deliver.add_argument("--authorized-reply-sender", action="append", required=True)
    deliver.add_argument("--report-version", type=int)
    deliver.add_argument("--sender-actor", required=True)
    deliver.add_argument("--idempotency-key", required=True)
    deliver.add_argument("--adapter-evidence", required=True)
    deliver.add_argument("--report-body-hash", required=True)
    deliver.add_argument("--delivery-text-hash", required=True)
    deliver.set_defaults(func=command_deliver)

    show = sub.add_parser("status", help="verify and show resumable run state")
    show.add_argument("--run-dir", required=True)
    show.set_defaults(func=command_status)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
