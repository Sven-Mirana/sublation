#!/usr/bin/env python3
"""Run lightweight Auditor checks for a skill-sublation candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


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
    valid_cross_reviewers = {"none", "hermes", "codex", "both", "user-waived"}
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

    return errors, warnings


def strict_checks(root: Path, manifest: dict | None) -> list[dict]:
    if not isinstance(manifest, dict):
        return [
            check("strict_manifest_available", False, "manifest required for strict checks"),
        ]

    residual_labels = residual_candidate_label_lines(root)
    patch_format_errors = patch_diff_format_errors(root / "PATCH.diff")
    runtime_changes = spec_patch_runtime_changes(manifest, root)
    promoted_manifest = is_promoted_manifest(manifest)
    stale_paths = [] if promoted_manifest else stale_baseline_paths(manifest)
    post_promotion_drift = post_promotion_drift_paths(manifest) if promoted_manifest else []
    consistency_errors = manifest_consistency_errors(manifest)
    relationship_errors = relationship_consistency_errors(manifest)
    external_eval_errors = external_evaluation_errors(manifest, root)
    rights_errors, rights_warnings = rights_provenance_findings(manifest)
    safety_errors, safety_warnings = post_promotion_safety_findings(manifest)

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
