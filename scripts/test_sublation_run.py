#!/usr/bin/env python3
"""Fixture tests for the durable one-shot Sublation run ledger."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import sublation_run


class SublationRunTests(unittest.TestCase):
    IDENTITIES = {
        "codex": {"principal_id": "openai-codex-test", "adapter_fingerprint": "sha256:codex-test"},
        "claude-code": {
            "principal_id": "anthropic-claude-test",
            "adapter_fingerprint": "sha256:claude-test",
        },
        "hermes": {"principal_id": "hermes-test", "adapter_fingerprint": "sha256:hermes-test"},
    }

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="sublation-run-test-"))
        self.roots = [
            {"name": "alpha", "path": str(self.tmp / "skills" / "alpha")},
            {"name": "beta", "path": str(self.tmp / "skills" / "beta")},
        ]
        for root in self.roots:
            path = Path(root["path"])
            path.mkdir(parents=True)
            (path / "SKILL.md").write_text("before\n", encoding="utf-8")

    def start(self, intent: str = "把现有技能 sublation 一下吧", run_id: str = "test-run") -> Path:
        run_dir = sublation_run.start_run(intent, self.tmp / "runs", self.roots, run_id)
        sublation_run.bind_worker_identities(
            run_dir,
            {
                actor: {
                    **identity,
                    "write_roots": [str(self.tmp / "candidates")] if actor == "codex" else [],
                }
                for actor, identity in self.IDENTITIES.items()
            },
        )
        return run_dir

    def identity_args(self, actor: str) -> dict[str, str]:
        identity = self.IDENTITIES[actor]
        return {
            "executor_principal": identity["principal_id"],
            "adapter_fingerprint": identity["adapter_fingerprint"],
        }

    def evidence(self, run_dir: Path, label: str) -> str:
        path = run_dir / "evidence" / f"{label}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"label": label}, sort_keys=True) + "\n", encoding="utf-8")
        return str(path)

    def finish_item(
        self,
        run_dir: Path,
        item_id: str,
        status: str,
        disposition: str,
        candidate_id: str | None = None,
    ) -> dict:
        if status == "APPROVAL_READY":
            candidate = self.tmp / "candidates" / item_id
            candidate.mkdir(parents=True, exist_ok=True)
            (candidate / "PATCH.diff").write_text(
                "diff --git a/SKILL.md b/SKILL.md\n--- a/SKILL.md\n+++ b/SKILL.md\n@@ -1 +1,2 @@\n before\n+after\n",
                encoding="utf-8",
            )
            phases = (
                ("codex", "observe", "OBSERVED"),
                ("codex", "candidate", "CANDIDATE_READY"),
                ("codex", "audit", "AUDIT_PASSED"),
                ("claude-code", "independent_verify", "VERIFY_PASSED"),
                ("hermes", "boundary_review", "REVIEW_PASSED"),
            )
            for index, (actor, phase, intermediate) in enumerate(phases, start=1):
                task = sublation_run.claim_task(run_dir, actor, 120, item_id)
                assert task is not None
                sublation_run.record_step(
                    run_dir,
                    step_id=f"{item_id.lower()}-phase-{index}",
                    item_id=item_id,
                    actor=actor,
                    phase=phase,
                    step_status="pass",
                    item_status=intermediate,
                    candidate_path=str(candidate) if intermediate == "CANDIDATE_READY" else None,
                    evidence=[self.evidence(run_dir, f"{item_id}-phase-{index}-{phase}")],
                    task_id=task["task_id"],
                    lease_token=task["lease"]["token"],
                    candidate_tree_hash=(
                        sublation_run.tree_hash(candidate)
                        if phase in {"audit", "independent_verify", "boundary_review", "aggregate"}
                        else None
                    ),
                    **self.identity_args(actor),
                )
            final_actor = "hermes"
            final_phase = "aggregate"
        else:
            task = sublation_run.claim_task(run_dir, "codex", 120, item_id)
            assert task is not None
            final_actor = "codex"
            final_phase = "observe"
        final_task = (
            sublation_run.claim_task(run_dir, final_actor, 120, item_id) if status == "APPROVAL_READY" else task
        )
        assert final_task is not None
        return sublation_run.record_step(
            run_dir,
            step_id=f"{item_id.lower()}-final",
            item_id=item_id,
            actor=final_actor,
            phase=final_phase,
            step_status="blocked" if status == "BLOCKED" else "pass",
            item_status=status,
            disposition=disposition,
            candidate_id=candidate_id,
            summary=f"{item_id} fixture result",
            evidence=[self.evidence(run_dir, f"{item_id}-final-{status.lower()}")],
            task_id=final_task["task_id"],
            lease_token=final_task["lease"]["token"],
            candidate_tree_hash=(
                sublation_run.tree_hash(candidate) if status == "APPROVAL_READY" else None
            ),
            **self.identity_args(final_actor),
        )

    def test_generic_existing_skills_selects_all_roots(self) -> None:
        run_dir = self.start()
        run = sublation_run.load_run(run_dir)
        self.assertEqual(run["scope"]["mode"], "all_roots_incremental")
        self.assertEqual([item["target"] for item in run["items"]], ["alpha", "beta"])
        self.assertEqual([item["item_id"] for item in run["items"]], ["A1", "A2"])
        self.assertEqual(run["inventory"]["counts"]["discovered"], 2)
        self.assertEqual(run["inventory"]["counts"]["changed"], 2)
        self.assertEqual(run["tasks"]["A1:observe:r1"]["assigned_actor"], "codex")

    def test_nested_skills_are_discovered_as_skill_items(self) -> None:
        nested = Path(self.roots[0]["path"]) / "vendor" / "nested-skill"
        nested.mkdir(parents=True)
        (nested / "SKILL.md").write_text("nested\n", encoding="utf-8")
        run_dir = self.start(run_id="nested-run")
        run = sublation_run.load_run(run_dir)
        self.assertEqual(
            [item["target"] for item in run["items"]],
            ["alpha", "alpha:vendor/nested-skill", "beta"],
        )
        self.assertEqual(run["items"][1]["skill_name"], "nested-skill")

    def test_incremental_inventory_skips_unchanged_and_selects_modified(self) -> None:
        first = self.start(run_id="baseline-run")
        self.finish_item(first, "A1", "CLOSED_NOOP", "no_op")
        self.finish_item(first, "A2", "CLOSED_NOOP", "no_op")
        sublation_run.finalize_report(first)

        unchanged = self.start(run_id="unchanged-run")
        unchanged_run = sublation_run.load_run(unchanged)
        self.assertEqual(unchanged_run["items"], [])
        self.assertEqual(unchanged_run["inventory"]["counts"]["unchanged"], 2)
        self.assertEqual(sublation_run.finalize_report(unchanged)["state"], "CLOSED")

        (Path(self.roots[0]["path"]) / "SKILL.md").write_text("changed\n", encoding="utf-8")
        modified = self.start(run_id="modified-run")
        modified_run = sublation_run.load_run(modified)
        self.assertEqual([item["target"] for item in modified_run["items"]], ["alpha"])
        self.assertEqual(modified_run["items"][0]["change_type"], "modified")

    def test_incremental_inventory_detects_removed_skill(self) -> None:
        first = self.start(run_id="remove-baseline")
        self.finish_item(first, "A1", "CLOSED_NOOP", "no_op")
        self.finish_item(first, "A2", "CLOSED_NOOP", "no_op")
        sublation_run.finalize_report(first)
        (Path(self.roots[1]["path"]) / "SKILL.md").unlink()
        removed = self.start(run_id="remove-detected")
        run = sublation_run.load_run(removed)
        self.assertEqual(len(run["items"]), 1)
        self.assertEqual(run["items"][0]["target"], "beta")
        self.assertEqual(run["items"][0]["change_type"], "removed")

    def test_incremental_baseline_is_resolved_per_root_after_narrow_run(self) -> None:
        full = self.start(run_id="per-root-full")
        self.finish_item(full, "A1", "CLOSED_NOOP", "no_op")
        self.finish_item(full, "A2", "CLOSED_NOOP", "no_op")
        sublation_run.finalize_report(full)

        (Path(self.roots[1]["path"]) / "SKILL.md").write_text("beta changed\n", encoding="utf-8")
        narrow = self.start("只把 beta 扬弃一下", "per-root-narrow")
        self.assertEqual([item["target"] for item in sublation_run.load_run(narrow)["items"]], ["beta"])
        self.finish_item(narrow, "A1", "CLOSED_NOOP", "no_op")
        sublation_run.finalize_report(narrow)

        combined = self.start(run_id="per-root-combined")
        run = sublation_run.load_run(combined)
        self.assertEqual(run["items"], [])
        self.assertEqual(set(run["inventory"]["baseline_run_ids"]), {"per-root-full", "per-root-narrow"})

    def test_explicit_root_name_selects_only_that_root(self) -> None:
        run_dir = self.start("只把 beta 扬弃一下", "named-run")
        run = sublation_run.load_run(run_dir)
        self.assertEqual(run["scope"]["mode"], "named_targets")
        self.assertEqual([item["target"] for item in run["items"]], ["beta"])

    def test_intent_without_explicit_sublation_trigger_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "explicitly request sublation/扬弃"):
            self.start("检查一下现有技能", "missing-trigger")

    def test_non_independent_role_configuration_is_rejected(self) -> None:
        actors = {
            "builder": "same-agent",
            "independent_verifier": "same-agent",
            "reviewer": "reviewer",
            "coordinator": "reviewer",
        }
        with self.assertRaisesRegex(ValueError, "must be distinct"):
            sublation_run.start_run(
                "把现有技能 sublation 一下吧",
                self.tmp / "runs",
                self.roots,
                "non-independent",
                role_actors=actors,
            )

    def test_explicit_single_agent_authorization_can_create_run(self) -> None:
        actors = {role: "solo-agent" for role in ("builder", "independent_verifier", "reviewer", "coordinator")}
        run_dir = sublation_run.start_run(
            "把现有技能 sublation 一下吧",
            self.tmp / "runs",
            self.roots,
            "authorized-single-agent",
            role_actors=actors,
            allow_single_agent=True,
        )
        policy = sublation_run.load_run(run_dir)["review_policy"]
        self.assertEqual(policy["mode"], "user_authorized_single_agent")
        self.assertTrue(policy["single_agent_user_authorized"])
        self.assertFalse(policy["independence_required"])

    def test_step_id_is_idempotent_but_conflicts_are_rejected(self) -> None:
        run_dir = self.start()
        evidence = self.evidence(run_dir, "observe-a1")
        first = sublation_run.record_step(
            run_dir,
            step_id="observe-a1",
            item_id="A1",
            actor="codex",
            phase="observe",
            step_status="pass",
            item_status="OBSERVED",
            evidence=[evidence],
        )
        duplicate = sublation_run.record_step(
            run_dir,
            step_id="observe-a1",
            item_id="A1",
            actor="codex",
            phase="observe",
            step_status="pass",
            item_status="OBSERVED",
            evidence=[evidence],
        )
        self.assertFalse(first["idempotent"])
        self.assertTrue(duplicate["idempotent"])
        with self.assertRaisesRegex(ValueError, "collision"):
            sublation_run.record_step(
                run_dir,
                step_id="observe-a1",
                item_id="A1",
                actor="claude-code",
                phase="verify",
                step_status="pass",
            )

    def test_step_status_and_item_status_must_agree(self) -> None:
        run_dir = self.start("只把 alpha 扬弃一下", "status-coupling")
        evidence = [self.evidence(run_dir, "status-coupling")]
        cases = (
            ("observe", "hold", "OBSERVED", "requires step_status=pass"),
            ("audit", "pass", "REWORK_REQUIRED", "requires step_status=hold or fail"),
            ("observe", "pass", "BLOCKED", "requires step_status=blocked or fail"),
        )
        for index, (phase, step_status, item_status, error) in enumerate(cases, start=1):
            with self.subTest(step_status=step_status, item_status=item_status):
                with self.assertRaisesRegex(ValueError, error):
                    sublation_run.record_step(
                        run_dir,
                        step_id=f"mismatch-{index}",
                        item_id="A1",
                        actor="codex",
                        phase=phase,
                        step_status=step_status,
                        item_status=item_status,
                        evidence=evidence,
                    )

    def test_missing_evidence_is_rejected_when_recording(self) -> None:
        run_dir = self.start("只把 alpha 扬弃一下", "missing-evidence")
        with self.assertRaisesRegex(ValueError, "evidence file does not exist"):
            sublation_run.record_step(
                run_dir,
                step_id="missing-evidence-step",
                item_id="A1",
                actor="codex",
                phase="observe",
                step_status="pass",
                item_status="OBSERVED",
                evidence=[str(run_dir / "evidence" / "absent.json")],
            )

    def test_missing_recorded_evidence_blocks_finalize(self) -> None:
        run_dir = self.start("只把 alpha 扬弃一下", "deleted-evidence")
        result = self.finish_item(run_dir, "A1", "CLOSED_NOOP", "no_op")
        evidence_path = Path(result["step"]["evidence"][0]["path"])
        evidence_path.unlink()
        with self.assertRaisesRegex(ValueError, "evidence is missing"):
            sublation_run.finalize_report(run_dir)

    def test_evidence_hash_drift_blocks_finalize(self) -> None:
        run_dir = self.start("只把 alpha 扬弃一下", "drifted-evidence")
        result = self.finish_item(run_dir, "A1", "CLOSED_NOOP", "no_op")
        evidence_path = Path(result["step"]["evidence"][0]["path"])
        evidence_path.write_text("drifted\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "evidence hash drifted"):
            sublation_run.finalize_report(run_dir)

    def test_durable_queue_changes_roles_across_full_candidate_flow(self) -> None:
        run_dir = self.start("只把 alpha 扬弃一下", "queue-flow")
        candidate = self.tmp / "candidates" / "queue-flow"
        candidate.mkdir(parents=True)
        (candidate / "PATCH.diff").write_text(
            "diff --git a/SKILL.md b/SKILL.md\n--- a/SKILL.md\n+++ b/SKILL.md\n@@ -1 +1,2 @@\n before\n+after\n",
            encoding="utf-8",
        )

        phases = [
            ("codex", "observe", "OBSERVED"),
            ("codex", "candidate", "CANDIDATE_READY"),
            ("codex", "audit", "AUDIT_PASSED"),
            ("claude-code", "independent_verify", "VERIFY_PASSED"),
            ("hermes", "boundary_review", "REVIEW_PASSED"),
            ("hermes", "aggregate", "APPROVAL_READY"),
        ]
        for index, (actor, phase, item_status) in enumerate(phases, start=1):
            task = sublation_run.claim_task(run_dir, actor, 120)
            self.assertIsNotNone(task)
            assert task is not None
            self.assertEqual(task["phase"], phase)
            sublation_run.record_task_dispatch(run_dir, task["task_id"], "quadchat", f"message-{index}")
            sublation_run.record_step(
                run_dir,
                step_id=f"queue-step-{index}",
                item_id="A1",
                actor=actor,
                phase=phase,
                step_status="pass",
                item_status=item_status,
                candidate_path=str(candidate) if phase == "candidate" else None,
                candidate_id="alpha/queue-candidate" if phase == "aggregate" else None,
                disposition="promotion" if phase == "aggregate" else None,
                summary="Queue flow candidate is ready." if phase == "aggregate" else None,
                evidence=[self.evidence(run_dir, f"queue-{index}-{phase}")],
                task_id=task["task_id"],
                lease_token=task["lease"]["token"],
                candidate_tree_hash=(
                    sublation_run.tree_hash(candidate)
                    if phase in {"audit", "independent_verify", "boundary_review", "aggregate"}
                    else None
                ),
                **self.identity_args(actor),
            )
        state = sublation_run.status(run_dir)
        self.assertEqual(state["state"], "AGGREGATING")
        self.assertEqual(state["next_actions"], [])
        self.assertEqual(state["task_counts"]["COMPLETED"], 6)
        self.assertEqual(sublation_run.finalize_report(run_dir)["state"], "USER_DECISION_REQUIRED")

    def test_wrong_actor_cannot_claim_another_roles_task(self) -> None:
        run_dir = self.start("只把 alpha 扬弃一下", "wrong-actor")
        self.assertIsNone(sublation_run.claim_task(run_dir, "claude-code", 120))
        claimed = sublation_run.claim_task(run_dir, "codex", 120)
        self.assertEqual(claimed["phase"], "observe")

    def test_expired_task_lease_is_recovered_without_duplicate_task(self) -> None:
        run_dir = self.start("只把 alpha 扬弃一下", "lease-recovery")
        first = sublation_run.claim_task(run_dir, "codex", 30)
        assert first is not None
        with sublation_run.locked_run(run_dir):
            run = sublation_run.load_run(run_dir)
            run["tasks"][first["task_id"]]["lease"]["expires_at"] = "2000-01-01T00:00:00+00:00"
            run["revision"] += 1
            run["updated_at"] = sublation_run.utc_now()
            sublation_run.commit_run(
                run_dir,
                run,
                "test_lease_expired",
                {"task_id": first["task_id"], "expires_at": "2000-01-01T00:00:00+00:00"},
            )
        recovered = sublation_run.claim_task(run_dir, "codex", 30)
        assert recovered is not None
        self.assertEqual(recovered["task_id"], first["task_id"])
        self.assertNotEqual(recovered["lease"]["token"], first["lease"]["token"])
        self.assertEqual(recovered["lease_count"], 2)
        self.assertTrue(sublation_run.verify_journal(run_dir)["valid"])

    def test_repeated_worker_release_escalates_to_coordinator(self) -> None:
        run_dir = self.start("只把 alpha 扬弃一下", "release-escalation")
        actor = "codex"
        for index in range(3):
            task = sublation_run.claim_task(run_dir, actor, 120)
            assert task is not None
            released = sublation_run.release_task(
                run_dir,
                task["task_id"],
                actor,
                task["lease"]["token"],
                f"transient-{index}",
                max_releases=3,
            )
        self.assertEqual(released["state"], "PENDING")
        self.assertEqual(released["role"], "coordinator")
        self.assertEqual(released["assigned_actor"], "hermes")
        coordinator_task = sublation_run.claim_task(run_dir, "hermes", 120)
        self.assertIsNotNone(coordinator_task)
        assert coordinator_task is not None
        with self.assertRaisesRegex(ValueError, "only close an exhausted delegated task as BLOCKED"):
            sublation_run.record_step(
                run_dir,
                step_id="coordinator-cannot-substitute-builder",
                item_id="A1",
                actor="hermes",
                phase="observe",
                step_status="pass",
                item_status="OBSERVED",
                evidence=[self.evidence(run_dir, "coordinator-cannot-substitute-builder")],
                task_id=coordinator_task["task_id"],
                lease_token=coordinator_task["lease"]["token"],
                **self.identity_args("hermes"),
            )

    def test_verifier_failure_queues_candidate_rework_without_user_intervention(self) -> None:
        run_dir = self.start("只把 alpha 扬弃一下", "rework-flow")
        candidate = self.tmp / "candidates" / "rework-flow"
        candidate.mkdir(parents=True)
        (candidate / "PATCH.diff").write_text(
            "diff --git a/SKILL.md b/SKILL.md\n--- a/SKILL.md\n+++ b/SKILL.md\n@@ -1 +1,2 @@\n before\n+after\n",
            encoding="utf-8",
        )
        for index, (phase, item_status) in enumerate(
            (("observe", "OBSERVED"), ("candidate", "CANDIDATE_READY"), ("audit", "AUDIT_PASSED")),
            start=1,
        ):
            task = sublation_run.claim_task(run_dir, "codex", 120, "A1")
            assert task is not None
            sublation_run.record_step(
                run_dir,
                step_id=f"pre-rework-{index}",
                item_id="A1",
                actor="codex",
                phase=phase,
                step_status="pass",
                item_status=item_status,
                candidate_path=str(candidate) if phase == "candidate" else None,
                evidence=[self.evidence(run_dir, f"pre-rework-{index}-{phase}")],
                task_id=task["task_id"],
                lease_token=task["lease"]["token"],
                candidate_tree_hash=(
                    sublation_run.tree_hash(candidate) if phase == "audit" else None
                ),
                **self.identity_args("codex"),
            )
        verify = sublation_run.claim_task(run_dir, "claude-code", 120, "A1")
        assert verify is not None
        sublation_run.record_step(
            run_dir,
            step_id="verify-hold",
            item_id="A1",
            actor="claude-code",
            phase="independent_verify",
            step_status="hold",
            item_status="REWORK_REQUIRED",
            blockers=["fixture finding"],
            evidence=[self.evidence(run_dir, "verify-hold")],
            task_id=verify["task_id"],
            lease_token=verify["lease"]["token"],
            candidate_tree_hash=sublation_run.tree_hash(candidate),
            **self.identity_args("claude-code"),
        )
        rework = sublation_run.claim_task(run_dir, "codex", 120, "A1")
        assert rework is not None
        self.assertEqual(rework["phase"], "candidate_rework")
        reworked_candidate = self.tmp / "candidates" / "rework-flow-r2"
        reworked_candidate.mkdir(parents=True)
        (reworked_candidate / "PATCH.diff").write_bytes((candidate / "PATCH.diff").read_bytes())
        sublation_run.record_step(
            run_dir,
            step_id="candidate-rework-r1",
            item_id="A1",
            actor="codex",
            phase="candidate_rework",
            step_status="pass",
            item_status="CANDIDATE_READY",
            candidate_path=str(reworked_candidate),
            evidence=[self.evidence(run_dir, "candidate-rework-r1")],
            task_id=rework["task_id"],
            lease_token=rework["lease"]["token"],
            **self.identity_args("codex"),
        )
        next_task = sublation_run.claim_task(run_dir, "codex", 120, "A1")
        assert next_task is not None
        self.assertEqual(next_task["task_id"], "A1:audit:r2")
        self.assertEqual(sublation_run.load_run(run_dir)["state"], "WORKING")

    def test_run_id_cannot_escape_runs_root(self) -> None:
        with self.assertRaisesRegex(ValueError, "run id"):
            self.start(run_id="..")

    def test_candidate_path_must_be_inside_bound_write_roots(self) -> None:
        run_dir = self.start(run_id="candidate-write-root")
        observe = sublation_run.claim_task(run_dir, "codex", 120, "A1")
        assert observe is not None
        sublation_run.record_step(
            run_dir,
            step_id="candidate-root-observe",
            item_id="A1",
            actor="codex",
            phase="observe",
            step_status="pass",
            item_status="OBSERVED",
            evidence=[self.evidence(run_dir, "candidate-root-observe")],
            task_id=observe["task_id"],
            lease_token=observe["lease"]["token"],
            **self.identity_args("codex"),
        )
        candidate_task = sublation_run.claim_task(run_dir, "codex", 120, "A1")
        assert candidate_task is not None
        outside = self.tmp / "unbound-candidate"
        outside.mkdir()
        (outside / "PATCH.diff").write_text(
            "diff --git a/SKILL.md b/SKILL.md\n--- a/SKILL.md\n+++ b/SKILL.md\n"
            "@@ -1 +1,2 @@\n before\n+after\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "outside the bound candidate write_roots"):
            sublation_run.record_step(
                run_dir,
                step_id="candidate-root-outside",
                item_id="A1",
                actor="codex",
                phase="candidate",
                step_status="pass",
                item_status="CANDIDATE_READY",
                candidate_path=str(outside),
                evidence=[self.evidence(run_dir, "candidate-root-outside")],
                task_id=candidate_task["task_id"],
                lease_token=candidate_task["lease"]["token"],
                **self.identity_args("codex"),
            )

    def test_run_directory_symlink_is_rejected(self) -> None:
        runs = self.tmp / "runs"
        runs.mkdir(exist_ok=True)
        (runs / "real-run").mkdir()
        (runs / "alias-run").symlink_to("real-run", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "run directory must not be a symlink"):
            sublation_run.start_run(
                "把现有技能 sublation 一下吧", runs, self.roots, "alias-run"
            )

    def test_control_directory_and_key_symlinks_are_rejected(self) -> None:
        runs = self.tmp / "runs"
        linked_run = runs / "linked-control"
        linked_run.mkdir(parents=True)
        outside_control = self.tmp / "outside-control"
        outside_control.mkdir()
        (linked_run / ".control").symlink_to(outside_control, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "control directory must not be a symlink"):
            sublation_run.start_run(
                "把现有技能 sublation 一下吧", runs, self.roots, "linked-control"
            )

        run_dir = self.start(run_id="linked-key")
        key_path = sublation_run.control_key_path(run_dir)
        key_path.unlink()
        outside_key = self.tmp / "outside-key"
        outside_key.write_bytes(b"x" * 32)
        outside_key.chmod(0o600)
        key_path.symlink_to(outside_key)
        with self.assertRaisesRegex(ValueError, "attestation key must be a regular file"):
            sublation_run.load_control_key(run_dir)

    def test_item_cannot_skip_required_review_phases(self) -> None:
        run_dir = self.start()
        with self.assertRaisesRegex(ValueError, "invalid item transition"):
            sublation_run.record_step(
                run_dir,
                step_id="skip-to-approval",
                item_id="A1",
                actor="fixture",
                phase="aggregate",
                step_status="pass",
                item_status="APPROVAL_READY",
                disposition="promotion",
                candidate_id="candidate-1",
                summary="Unsafe skipped candidate",
                evidence=[self.evidence(run_dir, "skip-to-approval")],
            )

    def test_report_requires_terminal_items(self) -> None:
        run_dir = self.start()
        with self.assertRaisesRegex(ValueError, "nonterminal"):
            sublation_run.finalize_report(run_dir)

    def test_approval_report_requires_executable_candidate_evidence(self) -> None:
        run_dir = self.start("只扬弃 alpha", "incomplete-approval")
        for index, status in enumerate(
            ("OBSERVED", "CANDIDATE_READY", "AUDIT_PASSED", "VERIFY_PASSED", "REVIEW_PASSED"),
            start=1,
        ):
            sublation_run.record_step(
                run_dir,
                step_id=f"incomplete-{index}",
                item_id="A1",
                actor="fixture",
                phase=f"phase-{index}",
                step_status="pass",
                item_status=status,
                evidence=[self.evidence(run_dir, f"incomplete-{index}")],
            )
        sublation_run.record_step(
            run_dir,
            step_id="incomplete-final",
            item_id="A1",
            actor="fixture",
            phase="aggregate",
            step_status="pass",
            item_status="APPROVAL_READY",
            candidate_id="alpha/incomplete",
            disposition="promotion",
            summary="Missing executable evidence on purpose.",
            evidence=[self.evidence(run_dir, "incomplete-final")],
        )
        with self.assertRaisesRegex(ValueError, "lack executable evidence"):
            sublation_run.finalize_report(run_dir)

    def test_mixed_promotion_and_noop_generates_one_bound_report(self) -> None:
        run_dir = self.start()
        self.finish_item(run_dir, "A1", "APPROVAL_READY", "promotion", "alpha/candidate-1")
        self.finish_item(run_dir, "A2", "CLOSED_NOOP", "no_op")
        report = sublation_run.finalize_report(run_dir)
        self.assertEqual(report["state"], "USER_DECISION_REQUIRED")
        self.assertEqual([item["item_id"] for item in report["approval_items"]], ["A1"])
        self.assertEqual(report["report_hash"], sublation_run.report_hash(report))
        report_body_hash = report["plain_report_sha256"]
        delivery_text_hash = sublation_run.sha256(b"delivery-message-100")
        adapter_evidence_path = run_dir / "evidence" / "delivery-message-100.json"
        sublation_run.atomic_write_json(
            adapter_evidence_path,
            {
                "message_ref": "message-100",
                "sender_actor": "hermes",
                "report_body_hash": report_body_hash,
                "delivery_text_hash": delivery_text_hash,
            },
        )
        adapter_evidence = str(adapter_evidence_path)
        delivered = sublation_run.record_delivery(
            run_dir,
            "quadchat",
            "message-100",
            ["user"],
            sender_actor="hermes",
            idempotency_key="delivery-message-100",
            adapter_evidence_path=adapter_evidence,
            report_body_hash=report_body_hash,
            delivery_text_hash=delivery_text_hash,
        )
        self.assertEqual(delivered["delivery"][0]["channel"], "quadchat")
        self.assertIn("ts", delivered["delivery"][0])
        self.assertTrue((run_dir / "report-v1.md").exists())
        self.assertTrue(sublation_run.status(run_dir)["journal"]["valid"])
        with self.assertRaisesRegex(ValueError, "identity binding"):
            sublation_run.record_delivery(
                run_dir,
                "quadchat",
                "message-100",
                ["another-sender"],
                sender_actor="hermes",
                idempotency_key="delivery-message-100",
                adapter_evidence_path=adapter_evidence,
                report_body_hash=report_body_hash,
                delivery_text_hash=delivery_text_hash,
            )

    def test_blocked_plus_approvable_is_partial(self) -> None:
        run_dir = self.start()
        self.finish_item(run_dir, "A1", "APPROVAL_READY", "promotion", "alpha/candidate-1")
        self.finish_item(run_dir, "A2", "BLOCKED", "blocked")
        report = sublation_run.finalize_report(run_dir)
        self.assertEqual(report["state"], "PARTIAL")

    def test_finalize_rejects_formal_drift_after_last_worker(self) -> None:
        run_dir = self.start(run_id="finalize-formal-drift")
        self.finish_item(run_dir, "A1", "APPROVAL_READY", "promotion", "alpha/candidate-1")
        self.finish_item(run_dir, "A2", "APPROVAL_READY", "promotion", "beta/candidate-1")
        (Path(self.roots[0]["path"]) / "SKILL.md").write_text("drifted\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "approval target baseline drifted: A1"):
            sublation_run.finalize_report(run_dir)

    def test_rework_uses_immutable_candidate_revisions_without_invalidating_old_evidence(self) -> None:
        run_dir = self.start(run_id="immutable-rework")

        def record(actor: str, phase: str, item_status: str, step_id: str, **kwargs: object) -> None:
            task = sublation_run.claim_task(run_dir, actor, 120, "A1")
            assert task is not None
            current_candidate = sublation_run.find_item(
                sublation_run.load_run(run_dir), "A1"
            ).get("candidate_path")
            sublation_run.record_step(
                run_dir,
                step_id=step_id,
                item_id="A1",
                actor=actor,
                phase=phase,
                step_status="hold" if item_status == "REWORK_REQUIRED" else "pass",
                item_status=item_status,
                evidence=[self.evidence(run_dir, step_id)],
                task_id=task["task_id"],
                lease_token=task["lease"]["token"],
                candidate_tree_hash=(
                    sublation_run.tree_hash(Path(str(current_candidate)))
                    if phase in {"audit", "independent_verify", "boundary_review", "aggregate"}
                    and current_candidate
                    else None
                ),
                **self.identity_args(actor),
                **kwargs,
            )

        record("codex", "observe", "OBSERVED", "rework-observe")
        patch_text = (
            "diff --git a/SKILL.md b/SKILL.md\n--- a/SKILL.md\n+++ b/SKILL.md\n"
            "@@ -1 +1,2 @@\n before\n+after\n"
        )
        first_candidate = self.tmp / "candidates" / "A1-r1"
        first_candidate.mkdir(parents=True)
        (first_candidate / "PATCH.diff").write_text(patch_text, encoding="utf-8")
        record(
            "codex",
            "candidate",
            "CANDIDATE_READY",
            "rework-candidate-r1",
            candidate_path=str(first_candidate),
        )
        record("codex", "audit", "AUDIT_PASSED", "rework-audit-r1")
        record(
            "claude-code",
            "independent_verify",
            "REWORK_REQUIRED",
            "rework-verify-hold",
            blockers=["fixture revision requested"],
        )

        second_candidate = self.tmp / "candidates" / "A1-r2"
        second_candidate.mkdir(parents=True)
        (second_candidate / "PATCH.diff").write_text(patch_text, encoding="utf-8")
        record(
            "codex",
            "candidate_rework",
            "CANDIDATE_READY",
            "rework-candidate-r2",
            candidate_path=str(second_candidate),
        )
        record("codex", "audit", "AUDIT_PASSED", "rework-audit-r2")
        record("claude-code", "independent_verify", "VERIFY_PASSED", "rework-verify-pass")
        record("hermes", "boundary_review", "REVIEW_PASSED", "rework-boundary")
        record(
            "hermes",
            "aggregate",
            "APPROVAL_READY",
            "rework-aggregate",
            candidate_id="fixture/rework-r2",
            disposition="promotion",
            summary="第二个不可变候选 revision 通过复核",
        )
        self.finish_item(run_dir, "A2", "CLOSED_NOOP", "no_op")
        report = sublation_run.finalize_report(run_dir)
        self.assertEqual(report["approval_items"][0]["candidate_path"], str(second_candidate.resolve()))

    def test_report_only_batch_closes_without_user_approval(self) -> None:
        run_dir = self.start()
        self.finish_item(run_dir, "A1", "CLOSED_REPORT_ONLY", "report_only")
        self.finish_item(run_dir, "A2", "CLOSED_NOOP", "no_op")
        report = sublation_run.finalize_report(run_dir)
        self.assertEqual(report["state"], "CLOSED")
        self.assertEqual(report["approval_items"], [])
        rendered = (run_dir / "report-v1.md").read_text(encoding="utf-8")
        self.assertIn("无需回复批准", rendered)
        self.assertNotIn("全部批准", rendered)

    def test_plain_report_discloses_single_agent_mode_without_claiming_three_parties(self) -> None:
        rendered = sublation_run.render_plain_report(
            {
                "run_id": "single-agent-report",
                "report_version": 1,
                "state": "CLOSED",
                "approval_code": "SR-TEST",
                "items": [
                    {
                        "item_id": "A1",
                        "target": "fixture",
                        "status": "CLOSED_NOOP",
                        "summary": "无需变更",
                    }
                ],
                "approval_items": [],
                "review_policy": {"mode": "user_authorized_single_agent"},
            }
        )
        self.assertIn("用户授权的单代理席位", rendered)
        self.assertNotIn("三方已完成", rendered)

    def test_finalize_is_idempotent_for_unchanged_material(self) -> None:
        run_dir = self.start(run_id="idempotent-finalize")
        self.finish_item(run_dir, "A1", "CLOSED_NOOP", "no_op")
        self.finish_item(run_dir, "A2", "CLOSED_REPORT_ONLY", "report_only")
        first = sublation_run.finalize_report(run_dir)
        second = sublation_run.finalize_report(run_dir)
        self.assertEqual(second["report_version"], first["report_version"])
        self.assertEqual(second["report_hash"], first["report_hash"])
        self.assertEqual(len(sublation_run.load_run(run_dir)["reports"]), 1)

    def test_tree_hash_includes_file_mode_and_symlink_identity(self) -> None:
        root = self.tmp / "tree-hash-fixture"
        root.mkdir()
        root.chmod(0o755)
        empty_hash = sublation_run.tree_hash(root)
        root.chmod(0o700)
        self.assertNotEqual(sublation_run.tree_hash(root), empty_hash)
        self.assertNotEqual(sublation_run.tree_hash(self.tmp / "missing-tree"), empty_hash)

        script = root / "script.sh"
        script.write_text("echo ok\n", encoding="utf-8")
        script.chmod(0o644)
        regular_hash = sublation_run.tree_hash(root)
        script.chmod(0o755)
        self.assertNotEqual(sublation_run.tree_hash(root), regular_hash)

        first = root / "first.txt"
        second = root / "second.txt"
        first.write_text("same\n", encoding="utf-8")
        second.write_text("same\n", encoding="utf-8")
        link = root / "current.txt"
        link.symlink_to(first.name)
        first_link_hash = sublation_run.tree_hash(root)
        link.unlink()
        link.symlink_to(second.name)
        self.assertNotEqual(sublation_run.tree_hash(root), first_link_hash)

    def test_same_revision_run_json_tamper_is_rejected(self) -> None:
        run_dir = self.start(run_id="same-revision-tamper")
        run = sublation_run.read_json(run_dir / "run.json")
        run["state"] = "CLOSED"
        sublation_run.atomic_write_json(run_dir / "run.json", run)
        with self.assertRaisesRegex(ValueError, "same revision"):
            sublation_run.load_run(run_dir)

    def test_duplicate_worker_principal_or_adapter_is_rejected(self) -> None:
        run_dir = sublation_run.start_run(
            "把现有技能 sublation 一下吧",
            self.tmp / "runs",
            self.roots,
            "duplicate-identities",
        )
        duplicate = {
            actor: {
                "principal_id": "same",
                "adapter_fingerprint": "sha256:same",
                "write_roots": [str(self.tmp / "candidates")],
            }
            for actor in ("codex", "claude-code", "hermes")
        }
        with self.assertRaisesRegex(ValueError, "distinct principals"):
            sublation_run.bind_worker_identities(run_dir, duplicate)

    def test_journal_tampering_is_detected(self) -> None:
        run_dir = self.start()
        path = run_dir / "journal.jsonl"
        entry = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        entry["payload"]["boundary"] = "tampered"
        path.write_text(json.dumps(entry) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "event_hash"):
            sublation_run.verify_journal(run_dir)

    def test_rehashed_journal_tamper_without_hmac_is_detected(self) -> None:
        run_dir = self.start(run_id="journal-mac-tamper")
        path = run_dir / "journal.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        entry = json.loads(lines[0])
        original_mac = entry.pop("event_mac")
        entry.pop("event_hash")
        entry["payload"]["boundary"] = "tampered-and-rehashed"
        entry["event_hash"] = sublation_run.sha256(entry)
        entry["event_mac"] = original_mac
        lines[0] = json.dumps(entry, sort_keys=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "event_mac"):
            sublation_run.verify_journal(run_dir)

    def test_process_crash_after_journal_recovers_without_duplicate_step(self) -> None:
        run_dir = self.start()
        evidence = self.evidence(run_dir, "crash-step")
        script = (
            "from pathlib import Path; import sublation_run; "
            f"sublation_run.record_step(Path({str(run_dir)!r}), step_id='crash-step', item_id='A1', "
            f"actor='codex', phase='observe', step_status='pass', item_status='OBSERVED', evidence=[{evidence!r}])"
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).parent)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["SUBLATION_TEST_CRASH_AFTER_JOURNAL"] = "1"
        result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 91)
        recovered = sublation_run.record_step(
            run_dir,
            step_id="crash-step",
            item_id="A1",
            actor="codex",
            phase="observe",
            step_status="pass",
            item_status="OBSERVED",
            evidence=[evidence],
        )
        self.assertTrue(recovered["idempotent"])
        self.assertEqual(sublation_run.load_run(run_dir)["items"][0]["status"], "OBSERVED")
        self.assertTrue(sublation_run.verify_journal(run_dir)["valid"])


if __name__ == "__main__":
    unittest.main()
