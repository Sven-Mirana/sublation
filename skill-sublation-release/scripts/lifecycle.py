#!/usr/bin/env python3
"""Inspect and close skill-sublation candidate lifecycle records."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


QUEUE_STATES = {"active", "stale-active"}
ALL_STATES = {
    "queue",
    "active",
    "stale-active",
    "promoted",
    "observation-window",
    "closed",
    "superseded",
    "rejected",
    "legacy",
    "invalid",
    "all",
}
VALID_STATUSES = {"draft", "validated", "review_pending", "approved", "promoted", "observation_window", "closed", "rejected"}
VALID_CROSS_REVIEWERS = {"none", "hermes", "codex", "both", "claude-code", "all", "configured", "user-waived"}
VALID_PROMOTION_MODES = {"none", "human_patch", "user_delegated_agent_patch", "rollback"}
CLOSURE_METADATA_FIELDS = ("closed_at", "closure_reason", "closure_evidence", "closure_reviewed_by", "closure_policy")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_hash(path: Path) -> str:
    return f"sha256:{sha256_bytes(path.read_bytes())}"


def collect_hashes(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    if not root.exists() or not root.is_dir():
        return files
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc" or path.name == ".DS_Store":
            continue
        files[path.relative_to(root).as_posix()] = file_hash(path)
    return files


def changed_paths(left: dict[str, str], right: dict[str, str]) -> list[str]:
    keys = set(left) | set(right)
    return sorted(rel for rel in keys if left.get(rel) != right.get(rel))


def load_manifest(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except Exception as exc:  # noqa: BLE001 - CLI should report malformed manifests.
        return None, str(exc)


def manifest_paths(root: Path) -> list[Path]:
    return sorted(path for path in root.glob("*/*/manifest.json") if path.is_file())


def source_stale(manifest: dict[str, Any]) -> bool:
    source = manifest.get("source_skill", {})
    source_path = source.get("path")
    source_files = source.get("files", {})
    if not source_path or not isinstance(source_files, dict):
        return True
    actual = Path(source_path).expanduser()
    if not actual.exists() or not actual.is_dir():
        return True
    return bool(changed_paths(source_files, collect_hashes(actual)))


def lifecycle_state(manifest: dict[str, Any] | None, error: str = "") -> tuple[str, str]:
    if manifest is None:
        return "invalid", error

    validation = manifest.get("validation")
    if manifest.get("schema_version") != 3 or not isinstance(validation, dict):
        return "legacy", "schema_version is not 3 or validation is missing"

    status = validation.get("status")
    rejection_reason = validation.get("rejection_reason")
    superseded_by = validation.get("superseded_by")

    if rejection_reason == "obsolete_superseded" or superseded_by:
        return "superseded", f"superseded_by={superseded_by or 'missing'}"
    if status == "rejected":
        return "rejected", validation.get("notes", "")
    if status == "observation_window":
        return "observation-window", "status=observation_window"
    if status == "closed":
        return "closed", "status=closed"
    if validation.get("promoted") or status == "promoted":
        return "promoted", f"status={status}"
    if status in {"draft", "validated", "review_pending", "approved"}:
        if source_stale(manifest):
            return "stale-active", "source baseline differs from current formal skill"
        return "active", f"status={status}"
    return "legacy", f"unrecognized validation.status={status!r}"


def candidate_record(path: Path) -> dict[str, Any]:
    manifest, error = load_manifest(path)
    state, reason = lifecycle_state(manifest, error)
    validation = manifest.get("validation", {}) if isinstance(manifest, dict) else {}
    return {
        "candidate_id": manifest.get("candidate_id", path.parent.name) if isinstance(manifest, dict) else path.parent.name,
        "candidate_type": manifest.get("candidate_type", "") if isinstance(manifest, dict) else "",
        "path": str(path.parent),
        "state": state,
        "status": validation.get("status", ""),
        "auditor_status": validation.get("auditor_status", ""),
        "promotion_mode": validation.get("promotion_mode", ""),
        "cross_reviewed_by": validation.get("cross_reviewed_by", ""),
        "promoted_by": validation.get("promoted_by", ""),
        "rejection_reason": validation.get("rejection_reason", ""),
        "superseded_by": validation.get("superseded_by", ""),
        "reason": reason,
    }


def normalize_cross_reviewer(value: Any) -> str:
    text = str(value or "").strip()
    if text in VALID_CROSS_REVIEWERS:
        return text
    lowered = text.lower()
    if "hermes" in lowered:
        return "hermes"
    if "codex" in lowered:
        return "codex"
    return "none"


def infer_candidate_type(manifest: dict[str, Any]) -> tuple[str, str]:
    existing = manifest.get("candidate_type")
    if existing in {"spec-patch", "script-enhance", "infra-fix", "tooling"}:
        return existing, "explicit"

    candidate_id = str(manifest.get("candidate_id", "")).lower()
    scope = manifest.get("scope", {})
    changes = " ".join(scope.get("changes", [])) if isinstance(scope, dict) else ""
    candidate_files = manifest.get("candidate", {}).get("files", {})
    changed_files = " ".join(candidate_files) if isinstance(candidate_files, dict) else ""
    haystack = " ".join([candidate_id, changes.lower(), changed_files.lower()])

    if "cron" in haystack or "workdir" in haystack:
        return "infra-fix", "inferred from cron/workdir wording"
    if "scripts/" in haystack or "script-status" in haystack:
        return "script-enhance", "inferred from script paths or script-status wording"
    if "skill-sublation" in candidate_id:
        return "tooling", "inferred from skill-sublation candidate id"
    return "spec-patch", "default for legacy skill-text candidate"


def infer_promotion_mode(validation: dict[str, Any]) -> str:
    promoted = bool(validation.get("promoted") or validation.get("status") == "promoted")
    if not promoted:
        return "none"
    promoted_by = str(validation.get("promoted_by", "")).lower()
    if "codex" in promoted_by or "agent" in promoted_by:
        return "user_delegated_agent_patch"
    return "human_patch"


def proposed_validation(validation: dict[str, Any]) -> dict[str, Any]:
    promoted = bool(validation.get("promoted") or validation.get("status") == "promoted")
    auditor_passed = validation.get("auditor_passed")
    current_status = validation.get("status")

    if auditor_passed is True:
        auditor_status = "passed"
    elif auditor_passed is False and promoted:
        auditor_status = "conditional"
    else:
        auditor_status = "conditional"

    status = current_status if current_status in VALID_STATUSES else ("observation_window" if promoted else "review_pending")
    if promoted and status == "promoted":
        status = "observation_window"

    result = {
        "auditor_status": auditor_status,
        "cross_reviewed_by": normalize_cross_reviewer(validation.get("cross_reviewed_by")),
        "promotion_mode": infer_promotion_mode(validation),
        "status": status,
        "fixture_assertions_passed": int(validation.get("fixture_assertions_passed") or 0),
        "promoted_by": str(validation.get("promoted_by", "")),
        "promoted_at": str(validation.get("promoted_at", "")),
        "notes": validation.get("promotion_note") or validation.get("auditor_note") or "Legacy manifest migration proposal; verify before writing.",
    }
    return result


def legacy_plan_record(path: Path) -> dict[str, Any]:
    manifest, error = load_manifest(path)
    if manifest is None:
        return {
            "manifest": str(path),
            "state": "invalid",
            "action": "manual_repair",
            "confidence": 0.0,
            "blocked_reasons": [error],
        }

    state, reason = lifecycle_state(manifest, "")
    if state != "legacy":
        return {
            "manifest": str(path),
            "candidate_id": manifest.get("candidate_id", path.parent.name),
            "state": state,
            "action": "skip",
            "confidence": 1.0,
            "blocked_reasons": [],
            "reason": reason,
        }

    validation = manifest.get("validation", {}) if isinstance(manifest.get("validation"), dict) else {}
    candidate_type, type_reason = infer_candidate_type(manifest)
    proposed = proposed_validation(validation)
    blocked_reasons: list[str] = []
    confidence = 0.8

    source_files = manifest.get("source_skill", {}).get("files")
    if not isinstance(source_files, dict):
        blocked_reasons.append("source_skill.files missing; exact rollback hashes cannot be reconstructed")
        confidence -= 0.2
    if validation.get("auditor_passed") is False and validation.get("promoted"):
        blocked_reasons.append("legacy auditor_passed=false conflicts with promoted=true; requires human note")
        confidence -= 0.2
    if proposed["status"] in {"observation_window", "closed"} and (not proposed["promoted_by"] or not proposed["promoted_at"]):
        blocked_reasons.append("promoted record lacks promoted_by/promoted_at")
        confidence -= 0.2

    return {
        "manifest": str(path),
        "candidate_id": manifest.get("candidate_id", path.parent.name),
        "state": "legacy",
        "action": "plan_v3_migration",
        "write_allowed": False,
        "confidence": max(0.0, round(confidence, 2)),
        "current_schema_version": manifest.get("schema_version"),
        "proposed": {
            "schema_version": 3,
            "candidate_type": candidate_type,
            "candidate_type_reason": type_reason,
            "validation": proposed,
        },
        "blocked_reasons": blocked_reasons,
    }


def include_record(record: dict[str, Any], state_filter: str) -> bool:
    state = record["state"]
    if state_filter == "all":
        return True
    if state_filter == "queue":
        return state in QUEUE_STATES
    return state == state_filter


def print_table(records: list[dict[str, Any]]) -> None:
    print("candidate_id\tstate\tstatus\tauditor_status\tpromotion_mode\treason")
    for record in records:
        print(
            "\t".join(
                str(record.get(key, ""))
                for key in ("candidate_id", "state", "status", "auditor_status", "promotion_mode", "reason")
            )
        )


def scan(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    records = [
        record
        for record in (candidate_record(path) for path in manifest_paths(root))
        if include_record(record, args.state)
    ]
    if args.json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
    else:
        print_table(records)
    if args.fail_on_queue and any(record["state"] in QUEUE_STATES for record in records):
        return 2
    return 0


def plan_legacy(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    records = [legacy_plan_record(path) for path in manifest_paths(root)]
    if args.only_legacy:
        records = [record for record in records if record.get("state") in {"legacy", "invalid"}]
    if args.json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
    else:
        print("candidate_id\taction\tconfidence\tblocked_reasons")
        for record in records:
            print(
                "\t".join(
                    [
                        str(record.get("candidate_id", record.get("manifest", ""))),
                        str(record.get("action", "")),
                        str(record.get("confidence", "")),
                        "; ".join(record.get("blocked_reasons", [])),
                    ]
                )
            )
    if args.fail_on_blocked and any(record.get("blocked_reasons") for record in records if record.get("action") == "plan_v3_migration"):
        return 2
    return 0


def parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def utc_timestamp(value: Any) -> datetime | None:
    timestamp = parse_timestamp(value)
    if timestamp is None:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def observation_age_days(validation: dict[str, Any], now: datetime) -> int | None:
    timestamp = utc_timestamp(validation.get("promoted_at") or validation.get("updated_at"))
    if timestamp is None:
        return None
    return max(0, (now - timestamp).days)


def closure_metadata_missing(validation: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for field in CLOSURE_METADATA_FIELDS:
        value = validation.get(field)
        if value in (None, "", []):
            missing.append(field)
    return missing


def closed_record_timestamp(validation: dict[str, Any]) -> datetime | None:
    return utc_timestamp(validation.get("closed_at") or validation.get("updated_at") or validation.get("promoted_at"))


def health_record(
    path: Path,
    warn_after_days: int,
    now: datetime,
    legacy_closed_metadata_before: datetime | None,
) -> list[dict[str, Any]]:
    manifest, error = load_manifest(path)
    if manifest is None:
        return [
            {
                "kind": "invalid_manifest",
                "candidate_id": path.parent.name,
                "manifest": str(path),
                "detail": error,
            }
        ]

    state, _reason = lifecycle_state(manifest)
    validation = manifest.get("validation", {}) if isinstance(manifest.get("validation"), dict) else {}
    candidate_id = manifest.get("candidate_id", path.parent.name)
    issues: list[dict[str, Any]] = []

    if state == "observation-window":
        age_days = observation_age_days(validation, now)
        issues.append(
            {
                "kind": "open_observation_window",
                "candidate_id": candidate_id,
                "manifest": str(path),
                "age_days": age_days,
                "detail": "status=observation_window remains open",
            }
        )
        if age_days is None:
            issues.append(
                {
                    "kind": "observation_window_missing_timestamp",
                    "candidate_id": candidate_id,
                    "manifest": str(path),
                    "age_days": None,
                    "detail": "missing promoted_at/updated_at for age calculation",
                }
            )
        elif age_days >= warn_after_days:
            issues.append(
                {
                    "kind": "aged_observation_window",
                    "candidate_id": candidate_id,
                    "manifest": str(path),
                    "age_days": age_days,
                    "detail": f"open for {age_days} days; threshold={warn_after_days}",
                }
            )

    if state == "closed":
        missing = closure_metadata_missing(validation)
        if missing:
            closed_timestamp = closed_record_timestamp(validation)
            waived = bool(
                legacy_closed_metadata_before is not None
                and closed_timestamp is not None
                and closed_timestamp < legacy_closed_metadata_before
            )
            issues.append(
                {
                    "kind": "waived_closed_missing_closure_metadata" if waived else "closed_missing_closure_metadata",
                    "candidate_id": candidate_id,
                    "manifest": str(path),
                    "missing_fields": missing,
                    "record_timestamp": closed_timestamp.isoformat().replace("+00:00", "Z") if closed_timestamp else None,
                    "severity": "waived" if waived else "issue",
                    "detail": (
                        "pre-policy closed record lacks observation-window closure metadata"
                        if waived else "closed record lacks observation-window closure metadata"
                    ),
                }
            )

    return issues


def health(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    now = datetime.now(timezone.utc)
    legacy_cutoff = None
    if args.waive_legacy_closed_metadata_before:
        legacy_cutoff = utc_timestamp(args.waive_legacy_closed_metadata_before)
        if legacy_cutoff is None:
            raise SystemExit(f"invalid --waive-legacy-closed-metadata-before: {args.waive_legacy_closed_metadata_before}")
    records = [
        issue
        for path in manifest_paths(root)
        for issue in health_record(path, args.warn_after_days, now, legacy_cutoff)
    ]
    issues = [record for record in records if record.get("severity") != "waived"]
    waived_issues = [record for record in records if record.get("severity") == "waived"]
    summary = {
        "total_issues": len(issues),
        "open_observation_windows": sum(1 for issue in issues if issue["kind"] == "open_observation_window"),
        "aged_observation_windows": sum(1 for issue in issues if issue["kind"] == "aged_observation_window"),
        "closed_missing_closure_metadata": sum(1 for issue in issues if issue["kind"] == "closed_missing_closure_metadata"),
        "invalid_manifests": sum(1 for issue in issues if issue["kind"] == "invalid_manifest"),
        "waived_issues": len(waived_issues),
    }
    if args.json:
        payload = {"summary": summary, "issues": issues}
        if args.include_waived:
            payload["waived_issues"] = waived_issues
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("kind\tcandidate_id\tage_days\tdetail")
        printable = issues + (waived_issues if args.include_waived else [])
        for issue in printable:
            print(
                "\t".join(
                    [
                        str(issue.get("kind", "")),
                        str(issue.get("candidate_id", "")),
                        "" if issue.get("age_days") is None else str(issue.get("age_days")),
                        str(issue.get("detail", "")),
                    ]
                )
            )
        if not issues:
            print("ok\t\t\tno observation-window health issues")
    if args.fail_on_issues and issues:
        return 2
    return 0


def close_superseded(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest).expanduser()
    manifest, error = load_manifest(manifest_path)
    if manifest is None:
        raise SystemExit(f"manifest is not valid JSON: {error}")
    validation = manifest.setdefault("validation", {})
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    validation.update(
        {
            "status": "rejected",
            "promotion_mode": "none",
            "rejection_reason": "obsolete_superseded",
            "superseded_by": args.superseded_by,
            "updated_at": now,
            "notes": args.reason,
        }
    )
    if args.cross_reviewed_by:
        validation["cross_reviewed_by"] = args.cross_reviewed_by
    if args.dry_run:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    else:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(manifest_path)
    return 0


def append_note(validation: dict[str, Any], note: str) -> None:
    existing = str(validation.get("notes") or "").strip()
    if not existing:
        validation["notes"] = note
    elif note not in existing:
        validation["notes"] = f"{existing}\n\n{note}"


def close_observation(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest).expanduser()
    manifest, error = load_manifest(manifest_path)
    if manifest is None:
        raise SystemExit(f"manifest is not valid JSON: {error}")

    validation = manifest.setdefault("validation", {})
    status = validation.get("status")
    if status != "observation_window":
        raise SystemExit(f"manifest is not in observation_window: status={status!r}")
    if not validation.get("promoted_by") or not validation.get("promoted_at"):
        raise SystemExit("observation_window closure requires promoted_by/promoted_at")

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    validation.update(
        {
            "status": "closed",
            "updated_at": now,
            "closed_at": now,
            "closure_reason": args.reason,
            "closure_evidence": args.evidence,
            "closure_reviewed_by": args.reviewed_by,
            "closure_policy": "observation-window-closure-policy/v1",
        }
    )
    append_note(validation, f"Observation window closed: {args.reason}")

    if args.dry_run:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    else:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(manifest_path)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    scan_parser = sub.add_parser("scan", help="list candidate lifecycle states")
    scan_parser.add_argument("--root", default="~/.hermes/sublation/candidates")
    scan_parser.add_argument("--state", default="queue", choices=sorted(ALL_STATES))
    scan_parser.add_argument("--json", action="store_true")
    scan_parser.add_argument("--fail-on-queue", action="store_true")
    scan_parser.set_defaults(func=scan)

    plan_parser = sub.add_parser("plan-legacy", help="read-only v3 migration plan for legacy manifests")
    plan_parser.add_argument("--root", default="~/.hermes/sublation/candidates")
    plan_parser.add_argument("--json", action="store_true")
    plan_parser.add_argument("--only-legacy", action="store_true", default=True)
    plan_parser.add_argument("--include-current", dest="only_legacy", action="store_false")
    plan_parser.add_argument("--fail-on-blocked", action="store_true")
    plan_parser.set_defaults(func=plan_legacy)

    health_parser = sub.add_parser("health", help="surface observation-window governance gaps")
    health_parser.add_argument("--root", default="~/.hermes/sublation/candidates")
    health_parser.add_argument("--warn-after-days", type=int, default=7)
    health_parser.add_argument("--waive-legacy-closed-metadata-before")
    health_parser.add_argument("--include-waived", action="store_true")
    health_parser.add_argument("--json", action="store_true")
    health_parser.add_argument("--fail-on-issues", action="store_true")
    health_parser.set_defaults(func=health)

    close_parser = sub.add_parser("close-superseded", help="mark a manifest as superseded without promoting it")
    close_parser.add_argument("manifest")
    close_parser.add_argument("--superseded-by", required=True)
    close_parser.add_argument("--reason", default="Closed without promotion because a later candidate superseded this one.")
    close_parser.add_argument("--cross-reviewed-by", choices=("none", "hermes", "codex", "both", "claude-code", "all", "configured", "user-waived"))
    close_parser.add_argument("--dry-run", action="store_true")
    close_parser.set_defaults(func=close_superseded)

    close_obs_parser = sub.add_parser("close-observation", help="close a promoted candidate observation window")
    close_obs_parser.add_argument("manifest")
    close_obs_parser.add_argument("--reason", required=True)
    close_obs_parser.add_argument("--evidence", action="append", default=[])
    close_obs_parser.add_argument("--reviewed-by", default="none", choices=("none", "hermes", "codex", "both", "claude-code", "all", "configured", "user-waived"))
    close_obs_parser.add_argument("--dry-run", action="store_true")
    close_obs_parser.set_defaults(func=close_observation)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
