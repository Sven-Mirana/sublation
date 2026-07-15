#!/usr/bin/env python3
"""Run a candidate-only Loop Engineering v3 gate and decision-packet pass."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


METADATA_PATHS = {"manifest.json", "RATIONALE.md", "EVIDENCE.md", "PATCH.diff"}
METADATA_PREFIXES = ("validation/",)
REQUIRED_OUT_OF_SCOPE_TOKENS = {
    "formal_write": ("formal", "write"),
    "promotion_approval": ("promotion", "approval"),
    "credential_login": ("credential", "login"),
    "live_validation": ("live", "validation"),
    "optimizer_iterative_sync_load_skill": ("optimizer", "iterative", "sync", "load_skill"),
}


@dataclass
class Gate:
    name: str
    status: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def file_hash(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def collect_hashes(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    if not root.exists():
        return files
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if "__pycache__" in rel.parts or rel.suffix == ".pyc" or rel.name == ".DS_Store":
            continue
        files[rel.as_posix()] = file_hash(path)
    return files


def collect_significant_hashes(root: Path) -> dict[str, str]:
    return {rel: value for rel, value in collect_hashes(root).items() if not is_metadata_path(rel)}


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for rel, value in collect_hashes(root).items():
        digest.update(rel.encode("utf-8") + b"\0" + value.encode("ascii") + b"\n")
    return "sha256:" + digest.hexdigest()


def is_metadata_path(rel: str) -> bool:
    return rel in METADATA_PATHS or any(rel.startswith(prefix) for prefix in METADATA_PREFIXES)


def changed_paths(source_files: dict[str, str], candidate_files: dict[str, str]) -> list[str]:
    keys = set(source_files) | set(candidate_files)
    return sorted(rel for rel in keys if source_files.get(rel) != candidate_files.get(rel))


def read_manifest(candidate: Path) -> tuple[dict[str, Any] | None, str | None]:
    manifest_path = candidate / "manifest.json"
    if not manifest_path.exists():
        return None, "manifest.json missing"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, f"manifest.json invalid JSON: {exc}"
    if not isinstance(data, dict):
        return None, "manifest.json must be an object"
    return data, None


def path_is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def candidate_path_gate(candidate: Path, manifest_path: Path, allow_mirror: bool) -> Gate:
    if manifest_path == candidate:
        return Gate("candidate_path", "pass", f"manifest candidate.path={manifest_path}")
    if allow_mirror:
        return Gate("candidate_path", "pass", f"mirror explicitly allowed; manifest candidate.path={manifest_path}")
    if manifest_path.exists() and collect_significant_hashes(manifest_path) == collect_significant_hashes(candidate):
        return Gate(
            "candidate_path",
            "pass",
            f"mirror accepted; significant files match manifest candidate.path={manifest_path}",
        )
    return Gate("candidate_path", "fail", f"manifest candidate.path={manifest_path}; actual candidate={candidate}")


def normalized_text(items: list[str]) -> str:
    return "\n".join(items).lower().replace("-", "_")


def out_of_scope_gate(scope: dict[str, Any]) -> Gate:
    raw = scope.get("out_of_scope")
    if not isinstance(raw, list) or not all(isinstance(item, str) and item.strip() for item in raw):
        return Gate("scope_out_of_scope", "fail", "scope.out_of_scope must be a non-empty string array")
    text = normalized_text(raw)
    missing: list[str] = []
    for label, tokens in REQUIRED_OUT_OF_SCOPE_TOKENS.items():
        if not all(token in text for token in tokens):
            missing.append(label)
    if missing:
        return Gate("scope_out_of_scope", "fail", "missing boundary token groups: " + ", ".join(missing))
    return Gate("scope_out_of_scope", "pass", "hard boundary exclusions present")


def value_delta_gate(validation: dict[str, Any]) -> Gate:
    value_delta = validation.get("value_delta")
    if not isinstance(value_delta, dict):
        return Gate("value_delta", "fail", "validation.value_delta missing")
    if value_delta.get("status") != "positive_delta":
        return Gate("value_delta", "fail", f"value_delta.status={value_delta.get('status')!r}")
    evidence = value_delta.get("evidence")
    fallback = value_delta.get("fallback_or_rollback")
    if not isinstance(evidence, list) or not evidence or not isinstance(fallback, str) or not fallback.strip():
        return Gate("value_delta", "fail", "positive delta requires evidence and fallback_or_rollback")
    return Gate("value_delta", "pass", str(value_delta.get("summary") or "positive delta recorded"))


def apply_check(candidate: Path, patch_path: Path, source_path: Path) -> Gate:
    if not patch_path.exists() or not patch_path.read_text(encoding="utf-8", errors="replace").strip():
        return Gate("patch_apply_check", "fail", "PATCH.diff missing or empty")
    if not source_path.exists() or not source_path.is_dir():
        return Gate("patch_apply_check", "fail", f"source/formal root unavailable: {source_path}")
    with tempfile.TemporaryDirectory(prefix="loop-v3-apply-") as tmp:
        work = Path(tmp) / "formal-copy"
        shutil.copytree(source_path, work, ignore=lambda _d, names: {name for name in names if name == ".DS_Store"})
        proc = subprocess.run(
            ["git", "-C", str(work), "apply", "--check", str(patch_path.resolve())],
            text=True,
            capture_output=True,
        )
        if proc.returncode == 0:
            return Gate("patch_apply_check", "pass", "git apply --check passed on source/formal copy")
        detail = (proc.stderr or proc.stdout or "git apply --check failed").strip().splitlines()
        return Gate("patch_apply_check", "fail", "; ".join(detail[:4]))


def review_state(validation: dict[str, Any]) -> tuple[Gate, bool]:
    reports = validation.get("pre_promotion_reports")
    policy = validation.get("review_policy")
    required: set[str]
    by_role = isinstance(policy, dict) and policy.get("mode") == "configured_multi_agent"
    if by_role:
        configured = policy.get("required_roles")
        required = {str(item) for item in configured if isinstance(item, str) and item.strip()} if isinstance(configured, list) else set()
    else:
        required = {"codex", "claude-code", "hermes"}
    if not required:
        return Gate("review_evidence", "fail", "review policy has no required reviewers or roles"), False
    if not isinstance(reports, list):
        return Gate("review_evidence", "warn", "validation.pre_promotion_reports missing; review required"), False

    approved: set[str] = set()
    latest: dict[str, str] = {}
    for report in reports:
        if not isinstance(report, dict):
            continue
        key = str(report.get("role") if by_role else report.get("reviewer") or "").strip()
        status = str(report.get("status") or "").strip()
        if key in required:
            latest[key] = status
            if status == "approve":
                approved.add(key)

    missing = sorted(required - set(latest))
    non_approve = sorted(key for key, status in latest.items() if key in required and status != "approve")
    if missing or non_approve:
        detail = []
        if missing:
            detail.append("missing: " + ", ".join(missing))
        if non_approve:
            detail.append("not approving: " + ", ".join(non_approve))
        return Gate("review_evidence", "warn", "; ".join(detail)), False
    return Gate("review_evidence", "pass", "required review evidence is approving"), True


def room_health(url: str | None) -> Gate | None:
    if not url:
        return None
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return Gate("room_health", "warn", f"room health unavailable: {exc}")
    ok = bool(payload.get("ok"))
    pid = payload.get("pid")
    return Gate("room_health", "pass" if ok else "warn", f"ok={ok}, pid={pid}")


def markdown_packet(report: dict[str, Any]) -> str:
    gates = report["gates"]
    blockers = [gate for gate in gates if gate["status"] == "fail"]
    warnings = [gate for gate in gates if gate["status"] == "warn"]
    lines = [
        "# Promotion Decision Packet",
        "",
        f"Candidate: `{report['candidate_id']}`",
        f"Loop state: `{report['state']}`",
        f"Generated at: `{report['generated_at']}`",
        "",
        "## Changed Paths",
        "",
    ]
    lines.extend(f"- `{path}`" for path in report["changed_paths"][:80])
    if not report["changed_paths"]:
        lines.append("- none")
    lines.extend(["", "## Gate Results", ""])
    lines.extend(f"- {gate['status'].upper()}: {gate['name']} - {gate['detail']}" for gate in gates)
    lines.extend(["", "## Value Delta", "", report.get("value_delta_summary") or "No value-delta summary recorded."])
    lines.extend(["", "## Blockers", ""])
    lines.extend(f"- {gate['name']}: {gate['detail']}" for gate in blockers)
    if not blockers:
        lines.append("- none")
    lines.extend(["", "## Warnings", ""])
    lines.extend(f"- {gate['name']}: {gate['detail']}" for gate in warnings)
    if not warnings:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## User Decision Required",
            "",
            "Choose exactly one:",
            "",
            "- approve exact promotion scope",
            "- hold",
            "- request changes",
            "- reject",
            "",
            "Automation stops here. No formal skill write, live validation, credential/login step, publication, or promotion is authorized by this packet alone.",
            "",
        ]
    )
    return "\n".join(lines)


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    candidate = Path(args.candidate).expanduser().resolve()
    manifest, manifest_error = read_manifest(candidate)
    gates: list[Gate] = []
    if manifest_error:
        gates.append(Gate("manifest", "fail", manifest_error))
        return {
            "generated_at": utc_now(),
            "candidate_id": str(candidate),
            "state": "BLOCKED",
            "changed_paths": [],
            "gates": [gate.as_dict() for gate in gates],
            "value_delta_summary": "",
        }
    assert manifest is not None

    source_path = Path(args.formal_root or manifest.get("source_skill", {}).get("path", "")).expanduser().resolve()
    candidate_manifest_path = Path(str(manifest.get("candidate", {}).get("path", candidate))).expanduser().resolve()
    gates.append(Gate("manifest", "pass" if manifest.get("schema_version") == 3 else "fail", f"schema_version={manifest.get('schema_version')!r}"))
    gates.append(candidate_path_gate(candidate, candidate_manifest_path, bool(getattr(args, "allow_mirror", False))))
    gates.append(Gate("candidate_isolation", "fail" if path_is_inside(candidate, source_path) else "pass", f"candidate={candidate}; source/formal={source_path}"))

    scope = manifest.get("scope") if isinstance(manifest.get("scope"), dict) else {}
    changes = scope.get("changes")
    gates.append(Gate("scope_changes", "pass" if isinstance(changes, list) and bool(changes) else "fail", "scope.changes must be non-empty"))
    gates.append(out_of_scope_gate(scope))

    validation = manifest.get("validation") if isinstance(manifest.get("validation"), dict) else {}
    promotion_mode = validation.get("promotion_mode")
    gates.append(Gate("promotion_mode", "pass" if promotion_mode == "none" else "fail", f"promotion_mode={promotion_mode!r}; automation must stop before promotion"))
    gates.append(value_delta_gate(validation))

    source_files = manifest.get("source_skill", {}).get("files", {})
    candidate_files = collect_hashes(candidate)
    changed = [rel for rel in changed_paths(source_files, candidate_files) if not is_metadata_path(rel)]
    gates.append(Gate("changed_paths", "pass" if changed else "fail", f"{len(changed)} non-metadata changed path(s)"))
    gates.append(apply_check(candidate, candidate / "PATCH.diff", source_path))

    review_gate, review_ready = review_state(validation)
    gates.append(review_gate)
    room_gate = room_health(args.room_health_url)
    if room_gate:
        gates.append(room_gate)

    fail_count = sum(1 for gate in gates if gate.status == "fail")
    if fail_count:
        state = "BLOCKED"
    elif review_ready:
        state = "USER_DECISION_REQUIRED"
    else:
        state = "REVIEW_REQUIRED"

    value_delta = validation.get("value_delta") if isinstance(validation.get("value_delta"), dict) else {}
    return {
        "generated_at": utc_now(),
        "candidate_id": str(manifest.get("candidate_id") or candidate.name),
        "candidate_path": str(candidate),
        "source_or_formal_path": str(source_path),
        "state": state,
        "changed_paths": changed,
        "gates": [gate.as_dict() for gate in gates],
        "value_delta_summary": str(value_delta.get("summary") or ""),
        "automation_boundary": "Stops at USER_DECISION_REQUIRED; promotion requires user explicit approval.",
    }


def run(args: argparse.Namespace) -> int:
    report = build_report(args)
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "loop_report.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not args.json_only:
        packet_path = output_dir / "PROMOTION_DECISION_PACKET.md"
        packet_path.write_text(markdown_packet(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["state"] != "BLOCKED" else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--candidate", required=True)
    run_parser.add_argument("--output-dir", required=True)
    run_parser.add_argument("--formal-root")
    run_parser.add_argument("--room-health-url")
    run_parser.add_argument("--allow-mirror", action="store_true")
    run_parser.add_argument("--no-room", action="store_true")
    run_parser.add_argument("--json-only", action="store_true")
    run_parser.set_defaults(func=run)
    args = parser.parse_args()
    if getattr(args, "no_room", False):
        args.room_health_url = None
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
