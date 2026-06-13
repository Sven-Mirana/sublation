"""Strong filesystem-derived validation for source_path_matches_promotion_target.

Problem (canghe-comic class): the manifest field is self-reported. audit.py only
checks `False -> requires target_path_note`; a candidate that declares True (or
leaves it null) passes audit even when the promotion landed in a different
agent's skill root and the production copy was never touched.

This module derives the truth from the filesystem instead of trusting the
declaration. Designed to be called from audit.py post_promotion_safety_findings
with zero new dependencies. Roots are injectable for testing.
"""

from __future__ import annotations

import os

# Formal skill roots per runtime agent. Extend here when a new agent joins.
DEFAULT_RUNTIME_ROOTS = {
    "hermes": "~/.hermes/skills",
    "codex": "~/.codex/skills",
    "claude-code": "~/.claude/skills",
}


def resolve_root_agent(path: str, roots: dict[str, str]) -> str | None:
    """Return which agent's formal root the (realpath-resolved) path falls under."""
    if not path:
        return None
    p = os.path.realpath(os.path.expanduser(path))
    for agent, root in roots.items():
        r = os.path.realpath(os.path.expanduser(root))
        if p == r or p.startswith(r + os.sep):
            return agent
    return None


def strong_path_findings(
    manifest: dict,
    runtime_agent: str | None = None,
    roots: dict[str, str] | None = None,
) -> tuple[list[str], list[str]]:
    """Cross-check declared source_path_matches_promotion_target against disk.

    Returns (errors, warnings) in audit.py convention.

    runtime_agent=None reads SUBLATION_RUNTIME_AGENT from the environment
    (default "hermes") so the audit.py call site needs no os import.
    """
    if runtime_agent is None:
        runtime_agent = os.environ.get("SUBLATION_RUNTIME_AGENT", "hermes")
    roots = roots or DEFAULT_RUNTIME_ROOTS
    errors: list[str] = []
    warnings: list[str] = []

    validation = manifest.get("validation") or {}
    status = validation.get("status")
    promoted = status in {"promoted", "observation_window", "closed"}
    safety = validation.get("post_promotion_safety") or {}
    declared = safety.get("source_path_matches_promotion_target")

    source_path = (manifest.get("source_skill") or {}).get("path") or ""
    target_path = safety.get("promotion_target_path") or ""

    src_agent = resolve_root_agent(source_path, roots)
    tgt_agent = resolve_root_agent(target_path, roots)

    # 1. Declared True must not contradict the filesystem.
    if declared is True and src_agent and tgt_agent and src_agent != tgt_agent:
        errors.append(
            "source_path_matches_promotion_target=True contradicts filesystem: "
            f"source under {src_agent!r} root, target under {tgt_agent!r} root"
        )

    # 2. Promotion target must live under the runtime that performs the audit.
    if tgt_agent and runtime_agent and tgt_agent != runtime_agent:
        errors.append(
            f"promotion target resolves to {tgt_agent!r} root but audit runtime "
            f"is {runtime_agent!r} - cross-root promotion (canghe-comic class)"
        )

    # 3. Promoted candidates must state the target and it must exist on disk.
    if promoted:
        if not target_path:
            warnings.append(
                "promoted candidate missing post_promotion_safety.promotion_target_path; "
                "strong path check cannot verify the production copy"
            )
        elif not os.path.exists(os.path.expanduser(target_path)):
            errors.append(
                f"promotion target path does not exist on disk: {target_path}"
            )
        if declared is None:
            warnings.append(
                "source_path_matches_promotion_target is unset on a promoted "
                "candidate; it must be explicitly evaluated, not skipped"
            )

    # 4. Target outside every known root: likely a typo or a new agent.
    if target_path and tgt_agent is None:
        warnings.append(
            f"promotion target {target_path!r} is outside all known runtime "
            "roots; add the new root to RUNTIME_ROOTS or fix the path"
        )

    return errors, warnings
