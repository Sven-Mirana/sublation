#!/usr/bin/env python3
"""Run lightweight Auditor checks for a skill-sublation candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime, timezone


def check(name: str, passed: bool, detail: str, severity: str = "required") -> dict:
    return {"name": name, "passed": passed, "severity": severity, "detail": detail}


def has_frontmatter(path: Path) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    return text.startswith("---\n") and "\n---\n" in text[4:]


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


def is_metadata_path(rel: str) -> bool:
    return rel in {"manifest.json", "RATIONALE.md", "EVIDENCE.md", "PATCH.diff"} or rel.startswith("validation/")


def changed_paths(left: dict[str, str], right: dict[str, str]) -> list[str]:
    keys = set(left) | set(right)
    return sorted(rel for rel in keys if left.get(rel) != right.get(rel))


def format_paths(paths: list[str], limit: int = 8) -> str:
    if not paths:
        return "0 paths"
    shown = ", ".join(paths[:limit])
    if len(paths) > limit:
        shown += f", ... (+{len(paths) - limit} more)"
    return shown


def added_patch_lines(patch_path: Path) -> list[tuple[int, str]]:
    if not patch_path.exists():
        return []
    lines: list[tuple[int, str]] = []
    for number, line in enumerate(patch_path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if line.startswith("+++") or not line.startswith("+"):
            continue
        lines.append((number, line[1:]))
    return lines


def residual_candidate_label_lines(root: Path) -> list[str]:
    pattern = re.compile(
        r"^\s{0,3}#{1,6}\s+.*(?:（[^）]*(?:候选|candidate)[^）]*）|\([^)]*(?:候选|candidate)[^)]*\))",
        re.IGNORECASE,
    )
    offenders = []
    for line_no, line in added_patch_lines(root / "PATCH.diff"):
        if pattern.search(line):
            offenders.append(f"PATCH.diff:{line_no}: {line.strip()}")
    return offenders


HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@(?: .*)?$")


def patch_diff_format_errors(patch_path: Path) -> list[str]:
    if not patch_path.exists():
        return []
    errors: list[str] = []
    for line_no, line in enumerate(patch_path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not line.startswith("@@"):
            continue
        if HUNK_HEADER_RE.match(line):
            continue
        if line.strip() == "@@":
            errors.append(f"PATCH.diff:{line_no}: bare @@ hunk header is missing line numbers")
        else:
            errors.append(f"PATCH.diff:{line_no}: invalid hunk header: {line}")
    return errors


def patch_apply_check_errors(manifest: dict, patch_path: Path) -> list[str]:
    if not patch_path.exists() or not patch_path.read_text(encoding="utf-8", errors="replace").strip():
        return []
    source_path = manifest.get("source_skill", {}).get("path")
    if not source_path:
        return ["source_skill.path missing; cannot run git apply --check"]
    source = Path(str(source_path)).expanduser()
    if not source.exists() or not source.is_dir():
        return [f"source_skill.path not found; cannot run git apply --check: {source}"]

    def ignore(_dir: str, names: list[str]) -> set[str]:
        # Keep bytecode files in the temp source copy so cleanup patches that
        # delete .pyc/__pycache__ artifacts can be verified by git apply --check.
        return {
            name for name in names
            if name == ".DS_Store"
            or name.endswith((".orig", ".rej"))
        }

    with tempfile.TemporaryDirectory(prefix="sublation-apply-check-") as tmp:
        work = Path(tmp) / "formal-copy"
        shutil.copytree(source, work, ignore=ignore)
        proc = subprocess.run(
            ["git", "-C", str(work), "apply", "--check", str(patch_path.resolve())],
            text=True,
            capture_output=True,
        )
        if proc.returncode == 0:
            return []
        detail = (proc.stderr or proc.stdout or "git apply --check failed").strip().splitlines()
        return detail[:6]


def spec_patch_runtime_changes(manifest: dict, root: Path) -> list[str]:
    if manifest.get("candidate_type") != "spec-patch":
        return []
    source_files = manifest.get("source_skill", {}).get("files", {})
    candidate_files = {
        rel: digest
        for rel, digest in collect_hashes(root).items()
        if not is_metadata_path(rel)
    }
    changed = changed_paths(source_files, candidate_files)
    runtime_prefixes = ("scripts/", "config/", "fixtures/", "schemas/")
    return [
        rel for rel in changed
        if rel.startswith(runtime_prefixes) or rel.endswith((".py", ".pyc"))
    ]


def stale_baseline_paths(manifest: dict) -> list[str]:
    source = manifest.get("source_skill", {})
    source_path = source.get("path")
    source_files = source.get("files", {})
    if not source_path or not isinstance(source_files, dict):
        return ["manifest.source_skill.path/files missing"]
    actual_source = Path(source_path).expanduser()
    if not actual_source.exists() or not actual_source.is_dir():
        return [f"source path unavailable: {actual_source}"]
    return changed_paths(source_files, collect_hashes(actual_source))


def is_promoted_manifest(manifest: dict) -> bool:
    validation = manifest.get("validation", {})
    return bool(validation.get("promoted") or validation.get("status") in {"promoted", "observation_window", "closed"})


def post_promotion_drift_paths(manifest: dict) -> list[str]:
    validation = manifest.get("validation", {})
    formal = validation.get("formal_post_promotion", {})
    formal_path = formal.get("path")
    formal_files = formal.get("files", {})
    if not formal_path or not isinstance(formal_files, dict):
        return ["validation.formal_post_promotion.path/files missing"]
    actual_formal = Path(formal_path).expanduser()
    if not actual_formal.exists() or not actual_formal.is_dir():
        return [f"formal path unavailable: {actual_formal}"]
    return changed_paths(formal_files, collect_hashes(actual_formal))


def formal_post_promotion_check(manifest: dict, promoted_manifest: bool, drift_paths: list[str]) -> dict:
    validation = manifest.get("validation", {})
    status = validation.get("status")
    superseded = bool(status == "superseded" or validation.get("superseded_by"))
    historical_status = status in {"closed", "rejected"} or superseded

    if not promoted_manifest:
        return check("strict_formal_post_promotion_current", True, "not promoted")
    if not drift_paths:
        return check("strict_formal_post_promotion_current", True, "0 paths")
    if historical_status:
        detail = f"{format_paths(drift_paths)}; historical status={status!r} indicates likely later legitimate promotion drift"
        return check("strict_formal_post_promotion_current", False, detail, "warning")
    return check(
        "strict_formal_post_promotion_current",
        False,
        format_paths(drift_paths),
    )


def manifest_consistency_errors(manifest: dict) -> list[str]:
    validation = manifest.get("validation", {})
    errors: list[str] = []
    status = validation.get("status")
    auditor_status = validation.get("auditor_status")
    promotion_mode = validation.get("promotion_mode")
    cross_reviewed_by = validation.get("cross_reviewed_by")
    rejection_reason = validation.get("rejection_reason")
    superseded_by = validation.get("superseded_by")
    promoted = bool(validation.get("promoted") or status in {"promoted", "observation_window", "closed"})

    valid_auditor_statuses = {"passed", "conditional", "failed", "pending"}
    valid_statuses = {"draft", "validated", "review_pending", "approved", "promoted", "observation_window", "closed", "rejected"}
    valid_cross_reviewers = {"none", "hermes", "codex", "both", "claude-code", "all", "configured", "user-waived"}
    if auditor_status not in valid_auditor_statuses:
        errors.append(f"validation.auditor_status invalid: {auditor_status!r}")
    if status not in valid_statuses:
        errors.append(f"validation.status invalid: {status!r}")
    if cross_reviewed_by not in valid_cross_reviewers:
        errors.append(f"validation.cross_reviewed_by invalid: {cross_reviewed_by!r}")
    if validation.get("auditor_passed") is False and promoted:
        errors.append("legacy auditor_passed=false conflicts with promoted status")
    if auditor_status == "failed" and status in {"approved", "promoted", "observation_window", "closed"}:
        errors.append(f"auditor_status=failed conflicts with status={status!r}")
    if status in {"promoted", "observation_window", "closed"}:
        if promotion_mode in {None, "", "none"}:
            errors.append(f"status={status!r} requires non-none promotion_mode")
        if not validation.get("promoted_by") or not validation.get("promoted_at"):
            errors.append(f"status={status!r} requires promoted_by/promoted_at")
    if promotion_mode not in {None, "none", "human_patch", "user_delegated_agent_patch", "rollback"}:
        errors.append(f"validation.promotion_mode invalid: {promotion_mode!r}")
    if status in {"approved", "promoted", "observation_window", "closed"} and cross_reviewed_by == "none":
        errors.append(f"status={status!r} should record cross_reviewed_by or user-waived")
    if status == "rejected":
        if promotion_mode not in {None, "none"}:
            errors.append("status='rejected' requires promotion_mode='none'")
        if validation.get("promoted"):
            errors.append("status='rejected' conflicts with promoted=true")
    if rejection_reason == "obsolete_superseded" and not superseded_by:
        errors.append("rejection_reason='obsolete_superseded' requires superseded_by")
    if superseded_by and status != "rejected":
        errors.append("superseded_by requires status='rejected'")
    return errors


FOUR_PARTY_REPORT_CUTOFF = datetime(2026, 6, 11, 0, 0, 0, tzinfo=timezone.utc)
DEFAULT_REQUIRED_PRE_PROMOTION_REPORTERS = {"claude-code", "codex", "hermes"}
DEFAULT_REQUIRED_REVIEW_ROLES = {"implementation_audit", "independent_review", "business_boundary"}
VALID_REVIEW_POLICY_MODES = {"default_three_agent", "configured_multi_agent", "single_agent", "user_waived"}
VALID_REVIEW_INDEPENDENCE = {"independent", "same_agent", "user", "external", "not_available"}
VALID_PRE_PROMOTION_REPORT_STATUSES = {"approve", "hold", "reject", "info"}


def manifest_created_at_or_after(manifest: dict, cutoff: datetime) -> tuple[bool, str | None]:
    raw = str(manifest.get("created_at") or "")
    if not raw:
        return False, "manifest.created_at missing; four-party pre-promotion gate skipped"
    try:
        created = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False, f"manifest.created_at invalid: {raw!r}; four-party pre-promotion gate skipped"
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return created >= cutoff, None


def nonempty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def configured_required_roles(policy: dict) -> set[str]:
    raw_roles = policy.get("required_roles")
    if isinstance(raw_roles, list) and raw_roles:
        return {str(role).strip() for role in raw_roles if nonempty_str(role)}

    assignments = policy.get("role_assignments")
    if isinstance(assignments, list):
        roles = {
            str(item.get("role")).strip()
            for item in assignments
            if isinstance(item, dict) and item.get("required") is not False and nonempty_str(item.get("role"))
        }
        if roles:
            return roles

    mode = policy.get("mode")
    if mode == "single_agent":
        return {"combined_review"}
    if mode == "user_waived":
        return set()
    return set(DEFAULT_REQUIRED_REVIEW_ROLES)


def review_policy_findings(manifest: dict, validation: dict) -> tuple[dict | None, list[str], list[str]]:
    policy = validation.get("review_policy")
    if policy is None:
        return None, [], []
    if not isinstance(policy, dict):
        return None, ["validation.review_policy must be an object"], []

    errors: list[str] = []
    warnings: list[str] = []
    mode = policy.get("mode")
    if mode not in VALID_REVIEW_POLICY_MODES:
        errors.append(f"validation.review_policy.mode invalid: {mode!r}")
    if mode in {"configured_multi_agent", "single_agent", "user_waived"}:
        if policy.get("policy_authorized_by") != "user":
            errors.append("non-default review_policy.mode requires policy_authorized_by='user'")
        if not (nonempty_str(policy.get("authorization_message_id")) or nonempty_str(policy.get("authorization_report_path"))):
            errors.append("non-default review_policy.mode requires authorization_message_id or authorization_report_path")

    required_roles = policy.get("required_roles")
    if required_roles is not None:
        if not isinstance(required_roles, list) or not required_roles or not all(nonempty_str(role) for role in required_roles):
            errors.append("validation.review_policy.required_roles must be a nonempty string array")
        elif len(set(required_roles)) != len(required_roles):
            errors.append("validation.review_policy.required_roles must not contain duplicates")

    min_required_reviews = policy.get("min_required_reviews")
    if min_required_reviews is not None and (not isinstance(min_required_reviews, int) or min_required_reviews < 1):
        errors.append("validation.review_policy.min_required_reviews must be a positive integer")

    assignments = policy.get("role_assignments")
    agent_roles: dict[str, set[str]] = {}
    if assignments is not None:
        if not isinstance(assignments, list):
            errors.append("validation.review_policy.role_assignments must be an array")
        else:
            for index, item in enumerate(assignments):
                if not isinstance(item, dict):
                    errors.append(f"validation.review_policy.role_assignments[{index}] must be an object")
                    continue
                role = item.get("role")
                agent = item.get("agent")
                if not nonempty_str(role):
                    errors.append(f"validation.review_policy.role_assignments[{index}].role is required")
                if not nonempty_str(agent):
                    errors.append(f"validation.review_policy.role_assignments[{index}].agent is required")
                if "required" in item and not isinstance(item.get("required"), bool):
                    errors.append(f"validation.review_policy.role_assignments[{index}].required must be boolean")
                independence = item.get("independence")
                if independence is not None and independence not in VALID_REVIEW_INDEPENDENCE:
                    errors.append(f"validation.review_policy.role_assignments[{index}].independence invalid: {independence!r}")
                if nonempty_str(role) and nonempty_str(agent) and item.get("required") is not False:
                    agent_roles.setdefault(str(agent).strip(), set()).add(str(role).strip())

    allow_same_agent = bool(policy.get("allow_same_agent_multiple_roles"))
    creator = str(manifest.get("created_by") or "").strip()
    for agent, roles in sorted(agent_roles.items()):
        if mode == "configured_multi_agent" and "implementation_audit" in roles and "independent_review" in roles:
            errors.append(
                f"configured_multi_agent cannot assign implementation_audit and independent_review to the same agent: {agent!r}"
            )
        if mode == "configured_multi_agent" and creator and agent == creator and "independent_review" in roles:
            errors.append(
                f"configured_multi_agent cannot assign independent_review to candidate creator {creator!r}"
            )
        if len(roles) > 1 and not allow_same_agent:
            errors.append(
                f"validation.review_policy assigns multiple required roles to {agent!r} without allow_same_agent_multiple_roles=true"
            )
        elif len(roles) > 1:
            warnings.append(
                f"validation.review_policy assigns multiple required roles to {agent!r}; evidence density is lower than independent cross-agent review"
            )

    if mode == "single_agent" and policy.get("allow_same_agent_multiple_roles") is not True:
        warnings.append("single_agent review_policy should set allow_same_agent_multiple_roles=true and disclose lower evidence density")

    return policy, errors, warnings


def pre_promotion_report_findings(manifest: dict) -> tuple[list[str], list[str]]:
    validation = manifest.get("validation", {})
    status = validation.get("status")
    cross_reviewed_by = validation.get("cross_reviewed_by")
    promoted_or_approved = status in {"approved", "promoted", "observation_window", "closed"}
    created_after_cutoff, created_warning = manifest_created_at_or_after(manifest, FOUR_PARTY_REPORT_CUTOFF)
    if promoted_or_approved and created_warning:
        return [], [created_warning]
    if not promoted_or_approved or not created_after_cutoff:
        return [], []

    policy, policy_errors, policy_warnings = review_policy_findings(manifest, validation)
    mode = policy.get("mode") if policy else None
    if mode == "user_waived" or cross_reviewed_by == "user-waived":
        return policy_errors, policy_warnings

    reports = validation.get("pre_promotion_reports")
    if reports is None:
        return policy_errors + ["validation.pre_promotion_reports missing for post-2026-06-11 promoted/approved candidate"], policy_warnings
    if not isinstance(reports, list):
        return policy_errors + ["validation.pre_promotion_reports must be an array"], policy_warnings

    errors: list[str] = list(policy_errors)
    warnings: list[str] = list(policy_warnings)
    reviewers: set[str] = set()
    latest_required_statuses: dict[str, tuple[int, str]] = {}
    latest_required_reviewers: dict[str, str] = {}

    using_configured_policy = policy is not None and mode != "default_three_agent"
    required_keys = configured_required_roles(policy) if using_configured_policy else set(DEFAULT_REQUIRED_PRE_PROMOTION_REPORTERS)
    key_label = "role" if using_configured_policy else "reviewer"
    approved_required_reviewers: set[str] = set()

    for index, report in enumerate(reports):
        if not isinstance(report, dict):
            errors.append(f"pre_promotion_reports[{index}] must be an object")
            continue
        reviewer = report.get("reviewer")
        role = report.get("role")
        report_status = report.get("status")
        focus = str(report.get("focus") or "").strip()
        if not nonempty_str(reviewer):
            errors.append(f"pre_promotion_reports[{index}].reviewer is required")
            continue
        reviewer = str(reviewer).strip()
        reviewers.add(reviewer)
        role_key = str(role).strip() if nonempty_str(role) else ""
        if using_configured_policy and not role_key:
            errors.append(f"pre_promotion_reports[{index}].role is required when validation.review_policy is configured")
        if role_key and "independence" in report and report.get("independence") not in VALID_REVIEW_INDEPENDENCE:
            errors.append(f"pre_promotion_reports[{index}].independence invalid: {report.get('independence')!r}")
        if report_status not in VALID_PRE_PROMOTION_REPORT_STATUSES:
            errors.append(f"pre_promotion_reports[{index}].status invalid: {report_status!r}")
        else:
            key = role_key if using_configured_policy else reviewer
            if key in required_keys:
                latest_required_statuses[key] = (index, report_status)
                latest_required_reviewers[key] = reviewer
                if report_status == "approve":
                    approved_required_reviewers.add(reviewer)
        if not focus:
            errors.append(f"pre_promotion_reports[{index}].focus is required")
        if (role_key if using_configured_policy else reviewer) in required_keys and not (report.get("message_id") or report.get("report_path")):
            warnings.append(
                f"pre_promotion_reports[{index}] {key_label}={(role_key if using_configured_policy else reviewer)!r} should record message_id or report_path"
            )

    present_required = set(latest_required_statuses)
    missing = sorted(required_keys - present_required)
    if missing:
        errors.append(f"validation.pre_promotion_reports missing required {key_label}s: {', '.join(missing)}")
    latest_non_approvals = [
        f"{key} at pre_promotion_reports[{index}] status={report_status!r}"
        for key, (index, report_status) in sorted(latest_required_statuses.items())
        if report_status != "approve"
    ]
    if latest_non_approvals:
        errors.append(
            "validation.pre_promotion_reports latest required reports must approve before promotion: "
            + "; ".join(latest_non_approvals)
        )
    min_required_reviews = policy.get("min_required_reviews") if policy else None
    if min_required_reviews is None:
        min_required_reviews = 1 if mode == "single_agent" else len(required_keys)
    if not isinstance(min_required_reviews, int) or min_required_reviews < 1:
        min_required_reviews = len(required_keys) or 1
    if len(approved_required_reviewers) < min_required_reviews:
        errors.append(
            f"validation.pre_promotion_reports has {len(approved_required_reviewers)} approving required reviewer(s), below min_required_reviews={min_required_reviews}"
        )
    if cross_reviewed_by == "configured" and policy is None:
        errors.append("validation.cross_reviewed_by='configured' requires validation.review_policy")
    if cross_reviewed_by == "all":
        if using_configured_policy:
            if missing:
                errors.append("validation.cross_reviewed_by='all' requires all configured required roles to report")
        elif reviewers & DEFAULT_REQUIRED_PRE_PROMOTION_REPORTERS != DEFAULT_REQUIRED_PRE_PROMOTION_REPORTERS:
            errors.append(
                "validation.cross_reviewed_by='all' requires default claude-code, codex, hermes agent pre_promotion_reports when no review_policy is configured"
            )

    return errors, warnings


DECISION_HISTORY_TRANSITION_UNTIL = datetime(2026, 9, 11, 0, 0, 0, tzinfo=timezone.utc)
VALID_DECISION_HISTORY_PHASES = {
    "candidate_revision",
    "pre_promotion_review",
    "promotion",
    "observation_window",
    "closure",
}
VALID_DECISION_TRIGGER_KINDS = {
    "report",
    "audit",
    "smoke_test",
    "user_decision",
    "observation",
    "external_paper",
    "manual_review",
}
VALID_DECISION_ACTION_KINDS = {"revision", "audit", "smoke_test", "report", "observation", "no_change"}
VALID_DECISION_OUTCOMES = {"resolved", "held", "rejected", "approved", "deferred", "observed"}
VALID_REPRODUCTION_STATUS = {"passed", "pending", "failed", "not_required"}
VALID_REPRODUCTION_METHODS = {"audit", "fixture", "smoke_test", "manual_review", "mixed"}
VALID_REJECTED_ALTERNATIVE_SCOPES = {"design_fork", "spec_patch", "absorption", "review_conflict", "routing"}
VALID_SENSITIVE_CONTEXT_CLASSES = {
    "credential_path",
    "cookie_path",
    "login_session",
    "page_body",
    "user_data",
    "contract_data",
    "private_chat",
    "other",
}


def string_array(value: object, *, min_items: int = 0) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= min_items
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def post_rule_promoted_or_approved(manifest: dict) -> bool:
    validation = manifest.get("validation", {})
    status = validation.get("status")
    promoted_or_approved = status in {"approved", "promoted", "observation_window", "closed"}
    created_after_cutoff, _ = manifest_created_at_or_after(manifest, FOUR_PARTY_REPORT_CUTOFF)
    return promoted_or_approved and created_after_cutoff


def decision_history_findings(manifest: dict) -> tuple[list[str], list[str]]:
    validation = manifest.get("validation", {})
    history = validation.get("decision_history")
    errors: list[str] = []
    warnings: list[str] = []

    if history is None:
        if post_rule_promoted_or_approved(manifest):
            target = warnings if datetime.now(timezone.utc) < DECISION_HISTORY_TRANSITION_UNTIL else errors
            target.append("validation.decision_history missing for post-rule promoted/approved candidate")
        return errors, warnings
    if not isinstance(history, list):
        return ["validation.decision_history must be an array"], []

    seen_ids: set[str] = set()
    for index, event in enumerate(history):
        prefix = f"decision_history[{index}]"
        if not isinstance(event, dict):
            errors.append(f"{prefix} must be an object")
            continue

        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id.strip():
            errors.append(f"{prefix}.event_id is required")
        elif event_id in seen_ids:
            errors.append(f"{prefix}.event_id duplicates {event_id!r}")
        else:
            seen_ids.add(event_id)

        if event.get("phase") not in VALID_DECISION_HISTORY_PHASES:
            errors.append(f"{prefix}.phase invalid: {event.get('phase')!r}")

        trigger = event.get("trigger")
        if not isinstance(trigger, dict):
            errors.append(f"{prefix}.trigger must be an object")
        else:
            if trigger.get("kind") not in VALID_DECISION_TRIGGER_KINDS:
                errors.append(f"{prefix}.trigger.kind invalid: {trigger.get('kind')!r}")
            if not isinstance(trigger.get("id"), str) or not trigger.get("id", "").strip():
                errors.append(f"{prefix}.trigger.id is required")
            if not nonempty_str(trigger.get("by")):
                errors.append(f"{prefix}.trigger.by is required")

        if not isinstance(event.get("diagnosis"), str) or not event.get("diagnosis", "").strip():
            errors.append(f"{prefix}.diagnosis is required")

        action = event.get("action")
        if not isinstance(action, dict):
            errors.append(f"{prefix}.action must be an object")
        else:
            if action.get("kind") not in VALID_DECISION_ACTION_KINDS:
                errors.append(f"{prefix}.action.kind invalid: {action.get('kind')!r}")
            if not isinstance(action.get("summary"), str) or not action.get("summary", "").strip():
                errors.append(f"{prefix}.action.summary is required")
            if "changed_paths" in action and not string_array(action.get("changed_paths")):
                errors.append(f"{prefix}.action.changed_paths must be a string array")

        if not string_array(event.get("evidence"), min_items=1):
            errors.append(f"{prefix}.evidence must be a non-empty string array")

        outcome = event.get("outcome")
        if not isinstance(outcome, dict):
            errors.append(f"{prefix}.outcome must be an object")
        else:
            if outcome.get("status") not in VALID_DECISION_OUTCOMES:
                errors.append(f"{prefix}.outcome.status invalid: {outcome.get('status')!r}")
            if not isinstance(outcome.get("summary"), str) or not outcome.get("summary", "").strip():
                errors.append(f"{prefix}.outcome.summary is required")

    return errors, warnings


def independent_reproduction_findings(manifest: dict) -> tuple[list[str], list[str]]:
    validation = manifest.get("validation", {})
    reproduction = validation.get("independent_reproduction")
    errors: list[str] = []
    warnings: list[str] = []

    if reproduction is None:
        if post_rule_promoted_or_approved(manifest):
            errors.append("validation.independent_reproduction missing for post-rule promoted/approved candidate")
        return errors, warnings
    if not isinstance(reproduction, dict):
        return ["validation.independent_reproduction must be an object"], []

    status = reproduction.get("status")
    if status not in VALID_REPRODUCTION_STATUS:
        errors.append(f"independent_reproduction.status invalid: {status!r}")
        return errors, warnings

    promoted_or_approved = post_rule_promoted_or_approved(manifest)
    if promoted_or_approved and status in {"pending", "failed"}:
        errors.append(f"independent_reproduction.status={status!r} blocks promotion")
    if status == "not_required":
        if not isinstance(reproduction.get("not_required_reason"), str) or not reproduction.get("not_required_reason", "").strip():
            errors.append("independent_reproduction.status='not_required' requires not_required_reason")
        if promoted_or_approved:
            warnings.append("independent_reproduction.not_required before promotion should be rare and explicitly reviewed")

    performed_by = reproduction.get("performed_by", [])
    if performed_by is not None:
        if not isinstance(performed_by, list) or any(not nonempty_str(actor) for actor in performed_by):
            errors.append("independent_reproduction.performed_by must be a string array of agent ids")
        elif status == "passed":
            author = str(manifest.get("created_by") or "")
            non_author = [actor for actor in performed_by if actor != author]
            if not non_author:
                errors.append("independent_reproduction.status='passed' requires at least one non-author performer")

    method = reproduction.get("method")
    if method is not None and method not in VALID_REPRODUCTION_METHODS:
        errors.append(f"independent_reproduction.method invalid: {method!r}")
    if status in {"passed", "failed"} and not string_array(reproduction.get("evidence"), min_items=1):
        errors.append(f"independent_reproduction.status={status!r} requires non-empty evidence")
    if "limitations" in reproduction and not string_array(reproduction.get("limitations")):
        errors.append("independent_reproduction.limitations must be a string array")

    return errors, warnings


def rejected_alternatives_findings(manifest: dict) -> tuple[list[str], list[str]]:
    alternatives = manifest.get("validation", {}).get("rejected_alternatives")
    if alternatives is None:
        return [], []
    if not isinstance(alternatives, list):
        return ["validation.rejected_alternatives must be an array"], []

    errors: list[str] = []
    for index, item in enumerate(alternatives):
        prefix = f"rejected_alternatives[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for field in ("alternative", "reason_rejected", "retained_learning"):
            if not isinstance(item.get(field), str) or not item.get(field, "").strip():
                errors.append(f"{prefix}.{field} is required")
        if item.get("scope") not in VALID_REJECTED_ALTERNATIVE_SCOPES:
            errors.append(f"{prefix}.scope invalid: {item.get('scope')!r}")
        if "evidence" in item and not string_array(item.get("evidence")):
            errors.append(f"{prefix}.evidence must be a string array")
    return errors, []


def redacted_reporting_findings(manifest: dict) -> tuple[list[str], list[str]]:
    reporting = manifest.get("redacted_reporting")
    if reporting is None:
        return [], []
    if not isinstance(reporting, dict):
        return ["redacted_reporting must be an object"], []

    errors: list[str] = []
    warnings: list[str] = []
    for field in ("shareable_evidence", "local_only_evidence"):
        if not string_array(reporting.get(field)):
            errors.append(f"redacted_reporting.{field} must be a string array")

    classes = reporting.get("sensitive_context_classes")
    if not isinstance(classes, list) or any(item not in VALID_SENSITIVE_CONTEXT_CLASSES for item in classes):
        errors.append("redacted_reporting.sensitive_context_classes contains invalid values")

    shareable = set(reporting.get("shareable_evidence") or [])
    local_only = set(reporting.get("local_only_evidence") or [])
    overlap = sorted(shareable & local_only)
    if overlap:
        warnings.append("redacted_reporting evidence appears in both shareable and local_only: " + ", ".join(overlap))
    return errors, warnings


def relationship_consistency_errors(manifest: dict) -> list[str]:
    relationships = manifest.get("relationships")
    if relationships is None:
        return []
    if not isinstance(relationships, dict):
        return ["relationships must be an object when present"]

    errors: list[str] = []
    pattern = relationships.get("sublation_pattern")
    valid_patterns = {"single_skill_patch", "cross_skill_absorption", "skill_merge_plan", "skill_split_plan"}
    if pattern not in valid_patterns:
        errors.append(f"relationships.sublation_pattern invalid: {pattern!r}")

    target = relationships.get("target_skill")
    if not isinstance(target, dict):
        errors.append("relationships.target_skill must be an object")
        target_name = None
        target_path = None
    else:
        target_name = target.get("name")
        target_path = target.get("path")
        if not target_name:
            errors.append("relationships.target_skill.name is required")
        if not target_path:
            errors.append("relationships.target_skill.path is required")

    donors = relationships.get("donor_skills", [])
    if donors is None:
        donors = []
    if not isinstance(donors, list):
        errors.append("relationships.donor_skills must be an array")
        donors = []

    if pattern == "cross_skill_absorption" and not donors:
        errors.append("cross_skill_absorption requires at least one donor skill")

    donor_names: set[str] = set()
    for index, donor in enumerate(donors):
        prefix = f"relationships.donor_skills[{index}]"
        if not isinstance(donor, dict):
            errors.append(f"{prefix} must be an object")
            continue
        name = donor.get("name")
        path = donor.get("path")
        absorbed = donor.get("absorbed_capability")
        if not name:
            errors.append(f"{prefix}.name is required")
        if name in donor_names:
            errors.append(f"{prefix}.name duplicates donor {name!r}")
        if name:
            donor_names.add(name)
        if not path:
            errors.append(f"{prefix}.path is required")
        if pattern == "cross_skill_absorption" and not absorbed:
            errors.append(f"{prefix}.absorbed_capability is required for cross_skill_absorption")
        if target_name and name == target_name:
            errors.append(f"{prefix}.name must differ from target_skill.name")
        if target_path and path == target_path:
            errors.append(f"{prefix}.path must differ from target_skill.path")

    return errors


ACTIVE_DECISION_STATUSES = {"draft", "validated", "review_pending", "approved"}
HISTORICAL_STATUSES = {"promoted", "observation_window", "closed", "rejected"}


def external_evaluation_errors(manifest: dict, root: Path) -> list[str]:
    evaluations = manifest.get("external_evaluations")
    if evaluations is None:
        return []
    if not isinstance(evaluations, list):
        return ["external_evaluations must be an array"]

    errors: list[str] = []
    allowed_modes = {"read_only_scorecard", "proposal_only", "dry_run"}
    for index, item in enumerate(evaluations):
        prefix = f"external_evaluations[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        evaluator = item.get("evaluator")
        target = item.get("target")
        mode = item.get("mode")
        report_path = item.get("report_path")
        formal_modified = item.get("formal_skill_modified")

        if not evaluator:
            errors.append(f"{prefix}.evaluator is required")
        if target != "candidate":
            errors.append(f"{prefix}.target must be 'candidate'")
        if mode not in allowed_modes:
            errors.append(f"{prefix}.mode invalid: {mode!r}")
        if formal_modified is not False:
            errors.append(f"{prefix}.formal_skill_modified must be false")
        if not isinstance(report_path, str) or not report_path:
            errors.append(f"{prefix}.report_path is required")
            continue
        path = Path(report_path)
        if path.is_absolute():
            errors.append(f"{prefix}.report_path must be relative to the candidate root")
            continue
        resolved = (root / path).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            errors.append(f"{prefix}.report_path must stay inside the candidate root")
            continue
        if not resolved.exists():
            errors.append(f"{prefix}.report_path does not exist: {report_path}")

    return errors


def rights_provenance_findings(manifest: dict) -> tuple[list[str], list[str]]:
    relationships = manifest.get("relationships")
    if not isinstance(relationships, dict):
        return [], []
    pattern = relationships.get("sublation_pattern")
    donors = relationships.get("donor_skills") or []
    if pattern not in {"cross_skill_absorption", "skill_merge_plan"} or not donors:
        return [], []

    validation = manifest.get("validation", {})
    status = validation.get("status")
    errors: list[str] = []
    warnings: list[str] = []
    target = warnings if status in HISTORICAL_STATUSES else errors
    rights = manifest.get("rights_provenance")
    if not isinstance(rights, dict):
        target.append("rights_provenance is required for cross-skill donor relationships")
        return errors, warnings

    donor_rights = rights.get("donor_rights")
    if not isinstance(donor_rights, list) or not donor_rights:
        target.append("rights_provenance.donor_rights must include at least one donor rights record")
        return errors, warnings

    rights_by_name = {
        item.get("skill_name"): item
        for item in donor_rights
        if isinstance(item, dict) and item.get("skill_name")
    }
    required_fields = ("license", "provenance", "absorbed_material", "expression_copied", "permission_basis")
    for donor in donors:
        if not isinstance(donor, dict):
            continue
        name = donor.get("name")
        if not name:
            continue
        record = rights_by_name.get(name)
        if not isinstance(record, dict):
            target.append(f"rights_provenance missing donor rights for {name!r}")
            continue
        for field in required_fields:
            value = record.get(field)
            if field == "expression_copied":
                if not isinstance(value, bool):
                    target.append(f"rights_provenance donor {name!r} requires boolean {field}")
            elif not value:
                target.append(f"rights_provenance donor {name!r} requires {field}")

    return errors, warnings


def post_promotion_safety_findings(manifest: dict) -> tuple[list[str], list[str]]:
    validation = manifest.get("validation", {})
    status = validation.get("status")
    promoted = status in {"promoted", "observation_window", "closed"}
    safety = validation.get("post_promotion_safety")
    if safety is None:
        if status == "closed":
            return [], ["validation.post_promotion_safety missing on closed candidate"]
        return [], []
    if not isinstance(safety, dict):
        return ["validation.post_promotion_safety must be an object"], []

    errors: list[str] = []
    warnings: list[str] = []
    rollback_ready = safety.get("rollback_ready")
    target_path_verified = safety.get("target_path_verified")
    source_matches = safety.get("source_path_matches_promotion_target")
    smoke = safety.get("business_smoke_test")
    fallback_verified = safety.get("fallback_verified")
    old_retained = safety.get("old_capability_retained")

    if promoted and rollback_ready is not True:
        errors.append("post_promotion_safety.rollback_ready must be true after promotion")
    if promoted and target_path_verified is not True:
        errors.append("post_promotion_safety.target_path_verified must be true after promotion")
    if source_matches is False and not safety.get("target_path_note"):
        errors.append("source_path_matches_promotion_target=false requires target_path_note")

    if smoke is not None and not isinstance(smoke, dict):
        errors.append("post_promotion_safety.business_smoke_test must be an object")
    elif isinstance(smoke, dict):
        smoke_status = smoke.get("status")
        evidence = smoke.get("evidence")
        if smoke_status not in {"passed", "pending", "failed", "not_required"}:
            errors.append(f"business_smoke_test.status invalid: {smoke_status!r}")
        if smoke_status == "failed":
            errors.append("business_smoke_test.status=failed blocks promotion closure")
        if status == "closed" and smoke_status not in {"passed", "not_required"}:
            errors.append("closed candidates require business_smoke_test.status passed or not_required")
        if smoke_status == "passed" and not evidence:
            errors.append("business_smoke_test.status=passed requires evidence")
    elif status == "closed":
        errors.append("closed candidates require business_smoke_test")

    if status == "closed" and fallback_verified is False:
        errors.append("closed candidates cannot have fallback_verified=false")
    if status == "closed" and old_retained is False:
        errors.append("closed candidates cannot have old_capability_retained=false")

    formal = validation.get("formal_post_promotion", {})
    relationships = manifest.get("relationships", {})
    target = relationships.get("target_skill", {}) if isinstance(relationships, dict) else {}
    target_path = target.get("path") if isinstance(target, dict) else None
    formal_path = formal.get("path") if isinstance(formal, dict) else None
    if target_path and formal_path and target_path != formal_path:
        warnings.append(
            f"relationships.target_skill.path differs from formal_post_promotion.path: {target_path!r} != {formal_path!r}"
        )

    try:
        from strong_path_check import strong_path_findings

        sp_errors, sp_warnings = strong_path_findings(manifest)
        errors.extend(sp_errors)
        warnings.extend(sp_warnings)
    except ImportError:
        warnings.append("strong_path_check module not installed; cross-root promotion check skipped")

    return errors, warnings


VALUE_DELTA_GATE_CUTOFF = datetime(2026, 6, 1, 14, 0, 0, tzinfo=timezone.utc)


def manifest_created_after_value_gate(manifest: dict) -> bool:
    raw = str(manifest.get("created_at") or "")
    if not raw:
        return False
    try:
        created = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return created >= VALUE_DELTA_GATE_CUTOFF


def nonempty_string_list(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, str) and item.strip() for item in value)


def value_delta_findings(manifest: dict) -> tuple[list[str], list[str]]:
    validation = manifest.get("validation", {})
    status = validation.get("status")
    promoted_or_approved = status in {"approved", "promoted", "observation_window", "closed"}
    value_delta = validation.get("value_delta")
    enforce = manifest_created_after_value_gate(manifest) and promoted_or_approved

    if value_delta is None:
        if enforce:
            return ["validation.value_delta missing for post-gate promoted/approved candidate"], []
        return [], []
    if not isinstance(value_delta, dict):
        return ["validation.value_delta must be an object"], []

    errors: list[str] = []
    warnings: list[str] = []
    delta_status = value_delta.get("status")
    if delta_status not in {"positive_delta", "not_applicable", "unproven", "regressed"}:
        errors.append(f"value_delta.status invalid: {delta_status!r}")
        return errors, warnings

    if promoted_or_approved and delta_status in {"unproven", "regressed"}:
        errors.append(f"value_delta.status={delta_status!r} blocks promotion")

    if delta_status == "positive_delta":
        if not nonempty_string_list(value_delta.get("positive_delta_categories")):
            errors.append("value_delta.positive_delta requires non-empty positive_delta_categories")
        for field in ("summary", "fallback_or_rollback", "observation_acceptance"):
            if not isinstance(value_delta.get(field), str) or not value_delta.get(field).strip():
                errors.append(f"value_delta.positive_delta requires {field}")
        if not nonempty_string_list(value_delta.get("evidence")):
            errors.append("value_delta.positive_delta requires non-empty evidence")
        if not isinstance(value_delta.get("regression_risks"), list):
            errors.append("value_delta.regression_risks must be an array")
    elif delta_status == "not_applicable":
        if not value_delta.get("not_applicable_reason"):
            errors.append("value_delta.status='not_applicable' requires not_applicable_reason")
        if promoted_or_approved:
            warnings.append("value_delta.not_applicable after approval/promotion should be rare and explicitly reviewed")

    old_retained = value_delta.get("old_capability_retained")
    capability_reduction = value_delta.get("capability_reduction")
    user_note = str(value_delta.get("user_approval_note") or "").strip()
    backward_compat = manifest.get("backward_compat")

    if promoted_or_approved and old_retained is False and not user_note:
        errors.append("value_delta.old_capability_retained=false requires explicit user_approval_note before promotion")
    if promoted_or_approved and (backward_compat is False or capability_reduction is True) and not user_note:
        errors.append("backward_compat=false or capability_reduction=true requires value_delta.user_approval_note")
    if capability_reduction is not None and not isinstance(capability_reduction, bool):
        errors.append("value_delta.capability_reduction must be boolean when present")
    if old_retained is not None and not isinstance(old_retained, bool):
        errors.append("value_delta.old_capability_retained must be boolean when present")

    return errors, warnings


def empirical_scorecard_findings(manifest: dict) -> tuple[list[str], list[str]]:
    validation = manifest.get("validation", {})
    scorecard = validation.get("empirical_scorecard")
    if scorecard is None:
        return [], []
    if not isinstance(scorecard, dict):
        return ["validation.empirical_scorecard must be an object"], []

    errors: list[str] = []
    warnings: list[str] = []
    status = scorecard.get("status")
    valid_statuses = {"measured", "not_applicable", "not_measured"}
    valid_decisions = {
        "improved",
        "neutral",
        "regressed",
        "blocked",
        "accepted_by_review",
        "not_applicable",
        "deferred",
    }
    if status not in valid_statuses:
        errors.append(f"empirical_scorecard.status invalid: {status!r}")
        return errors, warnings

    if status == "measured":
        required = (
            "metric_name",
            "baseline_score",
            "candidate_score",
            "higher_is_better",
            "fixture_or_dataset",
            "evaluator",
            "regression_checks",
            "decision",
        )
        for field in required:
            if field not in scorecard:
                errors.append(f"empirical_scorecard.status='measured' requires {field}")
        for field in ("baseline_score", "candidate_score"):
            if field in scorecard and not isinstance(scorecard.get(field), (int, float)):
                errors.append(f"empirical_scorecard.{field} must be numeric")
        if "higher_is_better" in scorecard and not isinstance(scorecard.get("higher_is_better"), bool):
            errors.append("empirical_scorecard.higher_is_better must be boolean")
        checks = scorecard.get("regression_checks")
        if "regression_checks" in scorecard and (
            not isinstance(checks, list) or not checks or not all(isinstance(item, str) and item for item in checks)
        ):
            errors.append("empirical_scorecard.regression_checks must be a non-empty string array")
        decision = scorecard.get("decision")
        if decision not in valid_decisions:
            errors.append(f"empirical_scorecard.decision invalid: {decision!r}")
        elif decision in {"regressed", "blocked"}:
            errors.append(f"empirical_scorecard.decision={decision!r} blocks promotion")

    if status == "not_applicable":
        if not scorecard.get("not_applicable_reason"):
            errors.append("empirical_scorecard.status='not_applicable' requires not_applicable_reason")
        decision = scorecard.get("decision")
        if decision not in {None, "not_applicable", "accepted_by_review"}:
            warnings.append("not_applicable scorecards should not carry an improvement decision")

    if status == "not_measured":
        if not scorecard.get("not_measured_reason"):
            errors.append("empirical_scorecard.status='not_measured' requires not_measured_reason")
        validation_status = validation.get("status")
        if validation_status in {"approved", "promoted", "observation_window", "closed"}:
            warnings.append(
                "empirical_scorecard.status='not_measured' after approval/promotion needs explicit human review"
            )

    return errors, warnings


def strict_checks(root: Path, manifest: dict | None) -> list[dict]:
    if not isinstance(manifest, dict):
        return [
            check("strict_manifest_available", False, "manifest required for strict checks"),
        ]

    residual_labels = residual_candidate_label_lines(root)
    patch_format_errors = patch_diff_format_errors(root / "PATCH.diff")
    patch_apply_errors = patch_apply_check_errors(manifest, root / "PATCH.diff")
    runtime_changes = spec_patch_runtime_changes(manifest, root)
    promoted_manifest = is_promoted_manifest(manifest)
    stale_paths = [] if promoted_manifest else stale_baseline_paths(manifest)
    post_promotion_drift = post_promotion_drift_paths(manifest) if promoted_manifest else []
    consistency_errors = manifest_consistency_errors(manifest)
    relationship_errors = relationship_consistency_errors(manifest)
    external_eval_errors = external_evaluation_errors(manifest, root)
    rights_errors, rights_warnings = rights_provenance_findings(manifest)
    safety_errors, safety_warnings = post_promotion_safety_findings(manifest)
    scorecard_errors, scorecard_warnings = empirical_scorecard_findings(manifest)
    value_delta_errors, value_delta_warnings = value_delta_findings(manifest)
    pre_report_errors, pre_report_warnings = pre_promotion_report_findings(manifest)
    decision_history_errors, decision_history_warnings = decision_history_findings(manifest)
    reproduction_errors, reproduction_warnings = independent_reproduction_findings(manifest)
    rejected_alternative_errors, rejected_alternative_warnings = rejected_alternatives_findings(manifest)
    redaction_errors, redaction_warnings = redacted_reporting_findings(manifest)

    return [
        check(
            "strict_no_residual_candidate_labels",
            not residual_labels,
            format_paths(residual_labels),
        ),
        check(
            "strict_patch_diff_format",
            not patch_format_errors,
            format_paths(patch_format_errors),
        ),
        check(
            "strict_patch_apply_check",
            not patch_apply_errors,
            format_paths(patch_apply_errors),
        ),
        check(
            "strict_spec_patch_scope",
            not runtime_changes,
            format_paths(runtime_changes),
        ),
        check(
            "strict_source_baseline_current",
            not stale_paths,
            "skipped after promotion; formal_post_promotion checked" if promoted_manifest else format_paths(stale_paths),
        ),
        formal_post_promotion_check(manifest, promoted_manifest, post_promotion_drift),
        check(
            "strict_manifest_consistency",
            not consistency_errors,
            "; ".join(consistency_errors) if consistency_errors else "manifest validation fields are self-consistent",
        ),
        check(
            "strict_relationships_consistency",
            not relationship_errors,
            "; ".join(relationship_errors) if relationship_errors else "relationships metadata is self-consistent or absent",
        ),
        check(
            "strict_external_evaluations",
            not external_eval_errors,
            "; ".join(external_eval_errors) if external_eval_errors else "external evaluator metadata is self-consistent or absent",
        ),
        check(
            "strict_rights_provenance",
            not rights_errors,
            "; ".join(rights_errors) if rights_errors else "rights/provenance metadata is present when required",
        ),
        check(
            "strict_rights_provenance_legacy",
            not rights_warnings,
            "; ".join(rights_warnings) if rights_warnings else "no legacy rights/provenance gaps",
            "warning",
        ),
        check(
            "strict_post_promotion_safety",
            not safety_errors,
            "; ".join(safety_errors) if safety_errors else "post-promotion safety metadata is self-consistent or absent",
        ),
        check(
            "strict_post_promotion_safety_legacy",
            not safety_warnings,
            "; ".join(safety_warnings) if safety_warnings else "no post-promotion safety warnings",
            "warning",
        ),
        check(
            "strict_empirical_scorecard",
            not scorecard_errors,
            "; ".join(scorecard_errors) if scorecard_errors else "empirical scorecard metadata is self-consistent or absent",
        ),
        check(
            "strict_empirical_scorecard_review",
            not scorecard_warnings,
            "; ".join(scorecard_warnings) if scorecard_warnings else "no empirical scorecard review warnings",
            "warning",
        ),
        check(
            "strict_value_delta_gate",
            not value_delta_errors,
            "; ".join(value_delta_errors) if value_delta_errors else "value-delta metadata is self-consistent or not required for this candidate",
        ),
        check(
            "strict_value_delta_gate_review",
            not value_delta_warnings,
            "; ".join(value_delta_warnings) if value_delta_warnings else "no value-delta review warnings",
            "warning",
        ),
        check(
            "strict_pre_promotion_reports",
            not pre_report_errors,
            "; ".join(pre_report_errors) if pre_report_errors else "pre-promotion report metadata is self-consistent or not required",
        ),
        check(
            "strict_pre_promotion_reports_review",
            not pre_report_warnings,
            "; ".join(pre_report_warnings) if pre_report_warnings else "no pre-promotion report warnings",
            "warning",
        ),
        check(
            "strict_decision_history",
            not decision_history_errors,
            "; ".join(decision_history_errors) if decision_history_errors else "decision-history metadata is self-consistent or not required",
        ),
        check(
            "strict_decision_history_review",
            not decision_history_warnings,
            "; ".join(decision_history_warnings) if decision_history_warnings else "no decision-history review warnings",
            "warning",
        ),
        check(
            "strict_independent_reproduction",
            not reproduction_errors,
            "; ".join(reproduction_errors) if reproduction_errors else "independent reproduction metadata is self-consistent or not required",
        ),
        check(
            "strict_independent_reproduction_review",
            not reproduction_warnings,
            "; ".join(reproduction_warnings) if reproduction_warnings else "no independent reproduction review warnings",
            "warning",
        ),
        check(
            "strict_rejected_alternatives",
            not rejected_alternative_errors,
            "; ".join(rejected_alternative_errors) if rejected_alternative_errors else "rejected alternatives metadata is self-consistent or absent",
        ),
        check(
            "strict_rejected_alternatives_review",
            not rejected_alternative_warnings,
            "; ".join(rejected_alternative_warnings) if rejected_alternative_warnings else "no rejected alternatives review warnings",
            "warning",
        ),
        check(
            "strict_redacted_reporting",
            not redaction_errors,
            "; ".join(redaction_errors) if redaction_errors else "redacted reporting metadata is self-consistent or absent",
        ),
        check(
            "strict_redacted_reporting_review",
            not redaction_warnings,
            "; ".join(redaction_warnings) if redaction_warnings else "no redacted reporting review warnings",
            "warning",
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate_path")
    parser.add_argument("--json", action="store_true", help="print JSON only")
    parser.add_argument("--strict", dest="strict", action="store_true", default=True,
                        help="run strict content-quality checks (default)")
    parser.add_argument("--no-strict", dest="strict", action="store_false",
                        help="skip strict content-quality checks")
    args = parser.parse_args()

    root = Path(args.candidate_path).expanduser().resolve()
    manifest_path = root / "manifest.json"
    manifest = None
    manifest_error = ""
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            manifest_error = str(exc)

    validation = manifest.get("validation", {}) if isinstance(manifest, dict) else {}
    promoted = bool(validation.get("promoted") or validation.get("status") in {"promoted", "observation_window", "closed"})
    pyc_files = [p for p in root.rglob("*") if "__pycache__" in p.parts or p.suffix == ".pyc"] if root.exists() else []

    path_text = str(root)
    candidate_like_path = "/sublation/candidates/" in path_text or "/candidates/" in path_text
    formal_skill_path = "/.hermes/skills/" in path_text

    checks = [
        check("candidate_exists", root.exists() and root.is_dir(), str(root)),
        check("skill_frontmatter", has_frontmatter(root / "SKILL.md"), "SKILL.md has YAML frontmatter"),
        check("manifest_valid_json", manifest is not None, manifest_error or "manifest.json parses"),
        check("manifest_schema_version", isinstance(manifest, dict) and manifest.get("schema_version") in (2, 3), "schema_version is 2 or 3"),
        check("candidate_not_formal_path", candidate_like_path and not formal_skill_path, "candidate lives in a candidate root, not an active formal skill path"),
        check("rationale_present", (root / "RATIONALE.md").exists(), "RATIONALE.md exists", "recommended"),
        check("evidence_present", (root / "EVIDENCE.md").exists(), "EVIDENCE.md exists", "recommended"),
        check("patch_present", (root / "PATCH.diff").exists(), "PATCH.diff exists", "recommended"),
        check("no_bytecode_artifacts", not pyc_files, f"{len(pyc_files)} bytecode artifacts found"),
        check(
            "promotion_record_complete",
            not promoted or bool(validation.get("promoted_by") and validation.get("promoted_at")),
            "promoted candidates record promoted_by/promoted_at",
        ),
    ]
    if args.strict:
        checks.extend(strict_checks(root, manifest))

    failed_required = [item for item in checks if item["severity"] == "required" and not item["passed"]]
    failed_recommended = [item for item in checks if item["severity"] != "required" and not item["passed"]]
    status = "failed" if failed_required else "conditional" if failed_recommended else "passed"

    result = {
        "schema_version": 1,
        "candidate_path": str(root),
        "auditor_status": status,
        "strict": args.strict,
        "checks": checks,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"auditor_status: {status}")
        for item in checks:
            mark = "PASS" if item["passed"] else "WARNING" if item["severity"] == "warning" else "FAIL"
            print(f"- {mark} {item['name']}: {item['detail']}")

    return 2 if status == "failed" else 1 if status == "conditional" else 0


if __name__ == "__main__":
    raise SystemExit(main())
