#!/usr/bin/env python3
"""Smoke tests for configurable pre-promotion review policies."""

from __future__ import annotations

from copy import deepcopy

from audit import manifest_consistency_errors, pre_promotion_report_findings


def base_manifest() -> dict:
    return {
        "created_by": "codex",
        "created_at": "2026-06-12T00:00:00Z",
        "validation": {
            "status": "approved",
            "auditor_status": "passed",
            "cross_reviewed_by": "all",
            "promotion_mode": "none",
        },
    }


def report(reviewer: str, role: str | None = None, status: str = "approve") -> dict:
    item = {
        "reviewer": reviewer,
        "status": status,
        "focus": "test review",
        "report_path": f"validation/{reviewer}-{role or 'default'}.md",
    }
    if role:
        item["role"] = role
    return item


def findings(manifest: dict) -> tuple[list[str], list[str]]:
    return pre_promotion_report_findings(manifest)


def check(name: str, condition: bool) -> bool:
    print(f"{'PASS' if condition else 'FAIL'} {name}")
    return condition


def main() -> int:
    passed = 0
    failed = 0

    def expect(name: str, condition: bool) -> None:
        nonlocal passed, failed
        if check(name, condition):
            passed += 1
        else:
            failed += 1

    default_ok = base_manifest()
    default_ok["validation"]["pre_promotion_reports"] = [
        report("codex"),
        report("claude-code"),
        report("hermes"),
    ]
    errors, warnings = findings(default_ok)
    expect("default three-agent policy still passes", not errors)
    expect("default cross_reviewed_by all is still manifest-consistent", not manifest_consistency_errors(default_ok))

    default_missing = deepcopy(default_ok)
    default_missing["validation"]["pre_promotion_reports"] = [report("codex"), report("hermes")]
    errors, _ = findings(default_missing)
    expect("default policy still fails when claude-code report is missing", any("claude-code" in error for error in errors))

    configured_ok = base_manifest()
    configured_ok["validation"]["cross_reviewed_by"] = "configured"
    configured_ok["validation"]["review_policy"] = {
        "mode": "configured_multi_agent",
        "coordinator": "agent-a",
        "policy_authorized_by": "user",
        "authorization_message_id": "user-approved-configured-policy",
        "required_roles": ["implementation_audit", "independent_review", "business_boundary"],
        "min_required_reviews": 3,
        "role_assignments": [
            {"role": "implementation_audit", "agent": "opencode", "required": True},
            {"role": "independent_review", "agent": "aider", "required": True},
            {"role": "business_boundary", "agent": "gemini-cli", "required": True},
        ],
    }
    configured_ok["validation"]["pre_promotion_reports"] = [
        report("opencode", "implementation_audit"),
        report("aider", "independent_review"),
        report("gemini-cli", "business_boundary"),
    ]
    errors, _ = findings(configured_ok)
    expect("configured multi-agent substitutes pass by role, not hard-coded names", not errors)

    configured_missing = deepcopy(configured_ok)
    configured_missing["validation"]["pre_promotion_reports"] = [
        report("opencode", "implementation_audit"),
        report("aider", "independent_review"),
    ]
    errors, _ = findings(configured_missing)
    expect("configured policy fails when a required role is missing", any("business_boundary" in error for error in errors))

    single_agent = base_manifest()
    single_agent["validation"]["cross_reviewed_by"] = "configured"
    single_agent["validation"]["review_policy"] = {
        "mode": "single_agent",
        "coordinator": "local-agent",
        "policy_authorized_by": "user",
        "authorization_message_id": "user-approved-single-agent-policy",
        "required_roles": ["combined_review"],
        "min_required_reviews": 1,
        "allow_same_agent_multiple_roles": True,
        "notes": "No independent reviewer is available in this deployment.",
    }
    single_agent["validation"]["pre_promotion_reports"] = [
        report("local-agent", "combined_review"),
    ]
    errors, warnings = findings(single_agent)
    expect("single-agent mode can pass with one honest combined_review", not errors)
    expect("single-agent mode is manifest-consistent with configured cross review", not manifest_consistency_errors(single_agent))

    single_agent_missing_auth = deepcopy(single_agent)
    single_agent_missing_auth["validation"]["review_policy"].pop("policy_authorized_by")
    single_agent_missing_auth["validation"]["review_policy"].pop("authorization_message_id")
    errors, _ = findings(single_agent_missing_auth)
    expect("non-default review_policy requires explicit user authorization", any("policy_authorized_by='user'" in error for error in errors) and any("authorization_message_id" in error for error in errors))

    no_policy = deepcopy(default_ok)
    no_policy["validation"]["cross_reviewed_by"] = "configured"
    errors, _ = findings(no_policy)
    expect("configured cross_reviewed_by requires review_policy", any("requires validation.review_policy" in error for error in errors))

    configured_creator_independent = deepcopy(configured_ok)
    configured_creator_independent["validation"]["review_policy"]["role_assignments"][1]["agent"] = "codex"
    errors, _ = findings(configured_creator_independent)
    expect("configured multi-agent mode rejects candidate creator as independent reviewer", any("candidate creator" in error for error in errors))

    same_agent_multi = deepcopy(configured_ok)
    same_agent_multi["validation"]["review_policy"]["allow_same_agent_multiple_roles"] = True
    same_agent_multi["validation"]["review_policy"]["role_assignments"] = [
        {"role": "implementation_audit", "agent": "local-agent", "required": True},
        {"role": "business_boundary", "agent": "local-agent", "required": True},
    ]
    same_agent_multi["validation"]["review_policy"]["required_roles"] = ["implementation_audit", "business_boundary"]
    same_agent_multi["validation"]["review_policy"]["min_required_reviews"] = 1
    same_agent_multi["validation"]["pre_promotion_reports"] = [
        report("local-agent", "implementation_audit"),
        report("local-agent", "business_boundary"),
    ]
    errors, warnings = findings(same_agent_multi)
    expect("same agent may fill multiple roles only when explicitly allowed", not errors and any("evidence density" in warning for warning in warnings))

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
