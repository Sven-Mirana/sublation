#!/usr/bin/env python3
"""Fixture tests for loop_engineering.py."""

from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import loop_engineering


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class LoopEngineeringTests(unittest.TestCase):
    def make_candidate(self, reviews: list[dict] | None, value_delta: dict | None) -> tuple[Path, Path]:
        tmp = Path(tempfile.mkdtemp(prefix="loop-v3-test-"))
        source = tmp / "formal"
        candidate = tmp / "candidate"
        write(source / "SKILL.md", "# Formal\n")
        write(candidate / "SKILL.md", "# Formal\n\nSee `references/loop-engineering-v3-automation.md`.\n")
        write(candidate / "references/loop-engineering-v3-automation.md", "# Ref\n")
        write(candidate / "scripts/loop_engineering.py", "# script\n")
        patch = """diff --git a/SKILL.md b/SKILL.md
--- a/SKILL.md
+++ b/SKILL.md
@@ -1 +1,3 @@
 # Formal
+
+See `references/loop-engineering-v3-automation.md`.
diff --git a/references/loop-engineering-v3-automation.md b/references/loop-engineering-v3-automation.md
new file mode 100644
--- /dev/null
+++ b/references/loop-engineering-v3-automation.md
@@ -0,0 +1 @@
+# Ref
diff --git a/scripts/loop_engineering.py b/scripts/loop_engineering.py
new file mode 100644
--- /dev/null
+++ b/scripts/loop_engineering.py
@@ -0,0 +1 @@
+# script
"""
        write(candidate / "PATCH.diff", patch)
        source_files = loop_engineering.collect_hashes(source)
        manifest = {
            "schema_version": 3,
            "candidate_id": "skill-sublation/test-loop-v3",
            "candidate_type": "tooling",
            "created_by": "codex",
            "source_skill": {
                "path": str(source),
                "tree_hash": loop_engineering.tree_hash(source),
                "files": source_files,
            },
            "candidate": {
                "path": str(candidate),
                "tree_hash": loop_engineering.tree_hash(candidate),
                "files": loop_engineering.collect_hashes(candidate),
            },
            "scope": {
                "changes": ["Add loop automation gate."],
                "out_of_scope": [
                    "No formal skill write.",
                    "No promotion without approval.",
                    "No credential or login work.",
                    "No live scraping or live validation.",
                    "No optimizer, iterative, sync, or load_skill usage.",
                ],
            },
            "validation": {
                "auditor_status": "conditional",
                "cross_reviewed_by": "none",
                "promotion_mode": "none",
                "status": "review_pending",
                "value_delta": value_delta,
                "review_policy": {
                    "mode": "configured_multi_agent",
                    "required_roles": ["builder_evidence", "independent_verifier", "reviewer_historian"],
                },
                "pre_promotion_reports": reviews,
            },
        }
        write(candidate / "manifest.json", json.dumps(manifest, indent=2))
        return source, candidate

    def run_report(self, candidate: Path) -> dict:
        args = Namespace(
            candidate=str(candidate),
            output_dir=str(candidate / "validation" / "loop-v3"),
            formal_root=None,
            room_health_url=None,
            allow_mirror=False,
            no_room=True,
            json_only=False,
        )
        return loop_engineering.build_report(args)

    def test_review_required_before_cross_review(self) -> None:
        value_delta = {
            "status": "positive_delta",
            "summary": "Automates evidence gates.",
            "evidence": ["Produces a decision packet."],
            "fallback_or_rollback": "Do not promote.",
        }
        _source, candidate = self.make_candidate(reviews=[], value_delta=value_delta)
        report = self.run_report(candidate)
        self.assertEqual(report["state"], "REVIEW_REQUIRED")

    def test_user_decision_required_after_approvals(self) -> None:
        value_delta = {
            "status": "positive_delta",
            "summary": "Automates evidence gates.",
            "evidence": ["Produces a decision packet."],
            "fallback_or_rollback": "Do not promote.",
        }
        reviews = [
            {"reviewer": "codex", "role": "builder_evidence", "status": "approve", "focus": "builder"},
            {"reviewer": "claude-code", "role": "independent_verifier", "status": "approve", "focus": "verifier"},
            {"reviewer": "hermes", "role": "reviewer_historian", "status": "approve", "focus": "reviewer"},
        ]
        _source, candidate = self.make_candidate(reviews=reviews, value_delta=value_delta)
        report = self.run_report(candidate)
        self.assertEqual(report["state"], "USER_DECISION_REQUIRED")

    def test_missing_value_delta_blocks(self) -> None:
        reviews = [
            {"reviewer": "codex", "role": "builder_evidence", "status": "approve", "focus": "builder"},
            {"reviewer": "claude-code", "role": "independent_verifier", "status": "approve", "focus": "verifier"},
            {"reviewer": "hermes", "role": "reviewer_historian", "status": "approve", "focus": "reviewer"},
        ]
        _source, candidate = self.make_candidate(reviews=reviews, value_delta=None)
        report = self.run_report(candidate)
        self.assertEqual(report["state"], "BLOCKED")

    def test_mirror_candidate_path_passes_when_significant_files_match(self) -> None:
        value_delta = {
            "status": "positive_delta",
            "summary": "Automates evidence gates.",
            "evidence": ["Produces a decision packet."],
            "fallback_or_rollback": "Do not promote.",
        }
        _source, candidate = self.make_candidate(reviews=[], value_delta=value_delta)
        mirror = candidate.parent / "shared-mirror"
        for path in candidate.rglob("*"):
            if not path.is_file():
                continue
            target = mirror / path.relative_to(candidate)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
        args = Namespace(
            candidate=str(mirror),
            output_dir=str(mirror / "validation" / "loop-v3"),
            formal_root=None,
            room_health_url=None,
            allow_mirror=False,
            no_room=True,
            json_only=False,
        )
        report = loop_engineering.build_report(args)
        candidate_path_gate = next(gate for gate in report["gates"] if gate["name"] == "candidate_path")
        self.assertEqual(candidate_path_gate["status"], "pass")
        self.assertEqual(report["state"], "REVIEW_REQUIRED")


if __name__ == "__main__":
    unittest.main()
