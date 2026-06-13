"""Self-test: reproduces the canghe-comic incident and verifies the strong check
catches what the current self-reported boolean misses. Run:
    python3 test_strong_path_check.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from strong_path_check import strong_path_findings


def make_roots(base):
    roots = {
        "hermes": os.path.join(base, "hermes-skills"),
        "codex": os.path.join(base, "codex-skills"),
        "claude-code": os.path.join(base, "claude-skills"),
    }
    for r in roots.values():
        os.makedirs(r, exist_ok=True)
    return roots


def manifest(status, declared, source, target):
    return {
        "validation": {
            "status": status,
            "post_promotion_safety": {
                "source_path_matches_promotion_target": declared,
                "promotion_target_path": target,
            },
        },
        "source_skill": {"path": source},
    }


def run():
    passed = failed = 0

    def check(name, cond):
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"PASS {name}")
        else:
            failed += 1
            print(f"FAIL {name}")

    with tempfile.TemporaryDirectory() as base:
        roots = make_roots(base)
        codex_skill = os.path.join(roots["codex"], "canghe-comic")
        hermes_skill = os.path.join(roots["hermes"], "canghe-comic")
        os.makedirs(codex_skill)
        os.makedirs(hermes_skill)

        # Scenario 1: canghe-comic incident. Candidate built from the Codex copy,
        # promoted into the Codex root, but declared True and audited by Hermes.
        # Current audit.py: passes silently. Strong check: 2 errors.
        m = manifest("promoted", True, codex_skill, codex_skill)
        errs, warns = strong_path_findings(m, runtime_agent="hermes", roots=roots)
        check("canghe-comic class caught as cross-root error",
              any("cross-root promotion" in e for e in errs))

        # Scenario 2: declared True but source and target in different roots.
        m = manifest("promoted", True, codex_skill, hermes_skill)
        errs, warns = strong_path_findings(m, runtime_agent="hermes", roots=roots)
        check("declared True contradicting filesystem caught",
              any("contradicts filesystem" in e for e in errs))

        # Scenario 3: honest same-root promotion passes clean.
        m = manifest("promoted", True, hermes_skill, hermes_skill)
        errs, warns = strong_path_findings(m, runtime_agent="hermes", roots=roots)
        check("honest same-root promotion has no errors", errs == [])

        # Scenario 4: promoted but target path deleted/never created.
        ghost = os.path.join(roots["hermes"], "ghost-skill")
        m = manifest("promoted", True, hermes_skill, ghost)
        errs, warns = strong_path_findings(m, runtime_agent="hermes", roots=roots)
        check("missing target on disk caught",
              any("does not exist on disk" in e for e in errs))

        # Scenario 5: promoted with field left null -> warning, not silence.
        m = manifest("promoted", None, hermes_skill, hermes_skill)
        errs, warns = strong_path_findings(m, runtime_agent="hermes", roots=roots)
        check("null declaration on promoted candidate warns",
              any("must be explicitly evaluated" in w for w in warns))

        # Scenario 6: target outside all known roots -> warning.
        outside = os.path.join(base, "random-place", "skill")
        os.makedirs(outside)
        m = manifest("promoted", True, hermes_skill, outside)
        errs, warns = strong_path_findings(m, runtime_agent="hermes", roots=roots)
        check("target outside known roots warns",
              any("outside all known runtime roots" in w for w in warns))

        # Scenario 7: draft candidate with relative/descriptive source -> silent.
        m = manifest("review_pending", None, "candidate consumes other output", "")
        errs, warns = strong_path_findings(m, runtime_agent="hermes", roots=roots)
        check("draft with descriptive source stays silent", errs == [] and warns == [])

        # Scenario 8: runtime_agent=None reads SUBLATION_RUNTIME_AGENT from the
        # environment, so the audit.py call site needs no os import (Codex
        # review finding, 2026-06-11).
        m = manifest("promoted", True, codex_skill, codex_skill)
        prev = os.environ.get("SUBLATION_RUNTIME_AGENT")
        os.environ["SUBLATION_RUNTIME_AGENT"] = "hermes"
        try:
            errs, warns = strong_path_findings(m, roots=roots)
        finally:
            if prev is None:
                os.environ.pop("SUBLATION_RUNTIME_AGENT", None)
            else:
                os.environ["SUBLATION_RUNTIME_AGENT"] = prev
        check("env fallback resolves runtime agent and catches cross-root",
              any("cross-root promotion" in e for e in errs))

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
