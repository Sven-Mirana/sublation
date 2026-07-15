#!/usr/bin/env python3
"""Sandbox-only end-to-end tests for receipt-gated promotion execution."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sublation_promote
import sublation_receipt
import sublation_run


PATCH = """diff --git a/SKILL.md b/SKILL.md
--- a/SKILL.md
+++ b/SKILL.md
@@ -1 +1,2 @@
 before
+after
"""


class SublationPromoteTests(unittest.TestCase):
    IDENTITIES = {
        "codex": {"principal_id": "openai-codex-test", "adapter_fingerprint": "sha256:codex-test"},
        "claude-code": {
            "principal_id": "anthropic-claude-test",
            "adapter_fingerprint": "sha256:claude-test",
        },
        "hermes": {"principal_id": "hermes-test", "adapter_fingerprint": "sha256:hermes-test"},
    }

    def evidence(self, label: str) -> str:
        path = self.run_dir / "evidence" / f"{label}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'{{"label": "{label}"}}\n', encoding="utf-8")
        return str(path)

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="sublation-promote-test-"))
        self.formal = self.tmp / "sandbox-skills" / "alpha"
        self.formal.mkdir(parents=True)
        (self.formal / "SKILL.md").write_text("before\n", encoding="utf-8")
        (self.formal / "shared.txt").write_text("shared\n", encoding="utf-8")
        (self.formal / "LINK.txt").symlink_to("shared.txt")
        self.candidate = self.tmp / "candidates" / "alpha-candidate"
        self.candidate.mkdir(parents=True)
        (self.candidate / "PATCH.diff").write_text(PATCH, encoding="utf-8")
        roots = [{"name": "alpha", "path": str(self.formal)}]
        self.run_dir = sublation_run.start_run(
            "把现有技能 sublation 一下吧",
            self.tmp / "runs",
            roots,
            "promote-run",
        )
        sublation_run.bind_worker_identities(
            self.run_dir,
            {
                actor: {
                    **identity,
                    "write_roots": [str(self.candidate.parent)] if actor == "codex" else [],
                }
                for actor, identity in self.IDENTITIES.items()
            },
        )
        candidate_tree_hash = sublation_run.tree_hash(self.candidate)
        phases = (
            ("codex", "observe", "OBSERVED"),
            ("codex", "candidate", "CANDIDATE_READY"),
            ("codex", "audit", "AUDIT_PASSED"),
            ("claude-code", "independent_verify", "VERIFY_PASSED"),
            ("hermes", "boundary_review", "REVIEW_PASSED"),
        )
        for index, (actor, phase, status) in enumerate(phases, start=1):
            task = sublation_run.claim_task(self.run_dir, actor, 120, "A1")
            assert task is not None
            sublation_run.record_step(
                self.run_dir,
                step_id=f"phase-{index}",
                item_id="A1",
                actor=actor,
                phase=phase,
                step_status="pass",
                item_status=status,
                candidate_path=str(self.candidate) if status == "CANDIDATE_READY" else None,
                evidence=[self.evidence(f"phase-{index}-{phase}")],
                task_id=task["task_id"],
                lease_token=task["lease"]["token"],
                executor_principal=self.IDENTITIES[actor]["principal_id"],
                adapter_fingerprint=self.IDENTITIES[actor]["adapter_fingerprint"],
                candidate_tree_hash=(candidate_tree_hash if phase != "observe" else None),
            )
        final_task = sublation_run.claim_task(self.run_dir, "hermes", 120, "A1")
        assert final_task is not None
        sublation_run.record_step(
            self.run_dir,
            step_id="approval-ready",
            item_id="A1",
            actor="hermes",
            phase="aggregate",
            step_status="pass",
            item_status="APPROVAL_READY",
            candidate_id="alpha/candidate-1",
            disposition="promotion",
            summary="Add the sandbox fixture line.",
            evidence=[self.evidence("approval-ready")],
            task_id=final_task["task_id"],
            lease_token=final_task["lease"]["token"],
            executor_principal=self.IDENTITIES["hermes"]["principal_id"],
            adapter_fingerprint=self.IDENTITIES["hermes"]["adapter_fingerprint"],
            candidate_tree_hash=candidate_tree_hash,
        )
        self.report = sublation_run.finalize_report(self.run_dir)
        report_body_hash = self.report["plain_report_sha256"]
        delivery_text_hash = sublation_run.sha256(
            f"[SUBLATION FINAL REPORT report-message]\n{report_body_hash}"
        )
        delivery_evidence_path = self.run_dir / "evidence" / "delivery-report-message.json"
        sublation_run.atomic_write_json(
            delivery_evidence_path,
            {
                "message_ref": "report-message",
                "sender_actor": "hermes",
                "report_body_hash": report_body_hash,
                "delivery_text_hash": delivery_text_hash,
            },
        )
        sublation_run.record_delivery(
            self.run_dir,
            "quadchat",
            "report-message",
            ["user"],
            sender_actor="hermes",
            idempotency_key="promote-report-message",
            adapter_evidence_path=str(delivery_evidence_path),
            report_body_hash=report_body_hash,
            delivery_text_hash=delivery_text_hash,
        )

    def receipt(self, message: str, event_id: str) -> dict:
        evidence = sublation_run.write_receipt_attestation(
            self.run_dir,
            {
                "adapter_id": "quadchat-local-test",
                "channel": "quadchat",
                "event_id": event_id,
                "sender_id": "user",
                "in_reply_to": "report-message",
                "message": message,
                "received_at": "2026-07-10T00:00:00+00:00",
                "source_event_hash": sublation_run.sha256(f"{event_id}-source"),
                "report_version": self.report["report_version"],
                "report_hash": self.report["report_hash"],
                "report_body_hash": self.report["plain_report_sha256"],
                "scope_revision": self.report["scope_revision"],
                "approval_code": self.report["approval_code"],
            },
        )
        return sublation_receipt.apply_receipt(
            self.run_dir,
            receipt_evidence_path=evidence,
        )

    def approve(self) -> dict:
        return self.receipt("准A1", "user-approval")

    def test_no_receipt_means_no_write(self) -> None:
        with self.assertRaisesRegex(ValueError, "approval.json missing"):
            sublation_promote.execute_approved(
                self.run_dir,
                allowed_targets={"A1": self.formal.resolve()},
                rollback_root=self.tmp / "rollbacks",
            )
        self.assertEqual((self.formal / "SKILL.md").read_text(encoding="utf-8"), "before\n")

    def test_forged_authorized_scope_is_rejected_without_formal_write(self) -> None:
        self.approve()
        approval_path = self.run_dir / "approval.json"
        approval = sublation_run.read_json(approval_path)
        approval["authorized_scope"] = []
        sublation_run.atomic_write_json(approval_path, approval)
        with self.assertRaisesRegex(ValueError, "authorized_scope cannot be reconstructed"):
            sublation_promote.execute_approved(
                self.run_dir,
                allowed_targets={"A1": self.formal.resolve()},
                rollback_root=self.tmp / "rollbacks",
            )
        self.assertEqual((self.formal / "SKILL.md").read_text(encoding="utf-8"), "before\n")

    def test_forged_decision_is_rejected_without_formal_write(self) -> None:
        self.approve()
        approval_path = self.run_dir / "approval.json"
        approval = sublation_run.read_json(approval_path)
        approval["decisions"]["A1"]["decision"] = "reject"
        approval["decisions"]["A1"]["execution"] = "not_authorized"
        sublation_run.atomic_write_json(approval_path, approval)
        with self.assertRaisesRegex(ValueError, "decision cannot be reconstructed"):
            sublation_promote.execute_approved(
                self.run_dir,
                allowed_targets={"A1": self.formal.resolve()},
                rollback_root=self.tmp / "rollbacks",
            )
        self.assertEqual((self.formal / "SKILL.md").read_text(encoding="utf-8"), "before\n")

    def test_receipts_are_replayed_in_durable_journal_order_not_cache_order(self) -> None:
        self.receipt("准A1", "event-approve")
        self.receipt("A1驳回", "event-reject")
        approval_path = self.run_dir / "approval.json"
        approval = sublation_run.read_json(approval_path)
        approval["events"] = list(reversed(approval["events"]))
        sublation_run.atomic_write_json(approval_path, approval)
        rebuilt, _report = sublation_promote.load_current_approval(
            self.run_dir, sublation_run.load_run(self.run_dir)
        )
        self.assertEqual(
            [event["event_id"] for event in rebuilt["events"]],
            ["event-approve", "event-reject"],
        )
        self.assertEqual(rebuilt["decisions"]["A1"]["decision"], "reject")

    def test_forged_succeeded_cache_cannot_skip_actual_promotion(self) -> None:
        self.approve()
        approval_path = self.run_dir / "approval.json"
        approval = sublation_run.read_json(approval_path)
        approval["decisions"]["A1"].update(
            {
                "execution": "succeeded",
                "post_tree_hash": sublation_run.tree_hash(self.formal),
                "rollback_path": str(self.tmp / "forged-rollback"),
            }
        )
        sublation_run.atomic_write_json(approval_path, approval)
        result = sublation_promote.execute_approved(
            self.run_dir,
            allowed_targets={"A1": self.formal.resolve()},
            rollback_root=self.tmp / "rollbacks",
        )
        self.assertFalse(result["results"][0]["idempotent"])
        self.assertEqual((self.formal / "SKILL.md").read_text(encoding="utf-8"), "before\nafter\n")

    def test_forged_event_missing_from_journal_is_rejected_without_formal_write(self) -> None:
        self.approve()
        approval_path = self.run_dir / "approval.json"
        approval = sublation_run.read_json(approval_path)
        forged = dict(approval["events"][0])
        forged["event_id"] = "forged-user-approval"
        approval["events"].append(forged)
        sublation_run.atomic_write_json(approval_path, approval)
        with self.assertRaisesRegex(ValueError, "event set differs from the durable receipt journal"):
            sublation_promote.execute_approved(
                self.run_dir,
                allowed_targets={"A1": self.formal.resolve()},
                rollback_root=self.tmp / "rollbacks",
            )
        self.assertEqual((self.formal / "SKILL.md").read_text(encoding="utf-8"), "before\n")

    def test_wrong_target_binding_is_rejected(self) -> None:
        self.approve()
        with self.assertRaisesRegex(ValueError, "differs from run target"):
            sublation_promote.execute_approved(
                self.run_dir,
                allowed_targets={"A1": (self.tmp / "wrong").resolve()},
                rollback_root=self.tmp / "rollbacks",
            )
        self.assertEqual((self.formal / "SKILL.md").read_text(encoding="utf-8"), "before\n")

    def test_rollback_root_inside_formal_target_is_rejected(self) -> None:
        self.approve()
        with self.assertRaisesRegex(ValueError, "must be isolated"):
            sublation_promote.execute_approved(
                self.run_dir,
                allowed_targets={"A1": self.formal.resolve()},
                rollback_root=self.formal / "rollbacks",
            )
        self.assertEqual((self.formal / "SKILL.md").read_text(encoding="utf-8"), "before\n")

    def test_patch_drift_after_report_is_rejected(self) -> None:
        self.approve()
        (self.candidate / "PATCH.diff").write_text(PATCH + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "changed after the approved report"):
            sublation_promote.execute_approved(
                self.run_dir,
                allowed_targets={"A1": self.formal.resolve()},
                rollback_root=self.tmp / "rollbacks",
            )
        self.assertEqual((self.formal / "SKILL.md").read_text(encoding="utf-8"), "before\n")

    def test_run_item_rebinding_after_report_is_rejected(self) -> None:
        self.approve()
        replacement = self.tmp / "candidates" / "replacement"
        replacement.mkdir(parents=True)
        replacement_patch = replacement / "PATCH.diff"
        replacement_patch.write_text(PATCH, encoding="utf-8")
        with sublation_run.locked_run(self.run_dir):
            run = sublation_run.load_run(self.run_dir)
            item = run["items"][0]
            item["candidate_id"] = "alpha/rebound"
            item["candidate_path"] = str(replacement)
            item["patch_path"] = str(replacement_patch)
            item["patch_hash"] = sublation_run.sha256(replacement_patch.read_bytes())
            run["revision"] += 1
            run["updated_at"] = sublation_run.utc_now()
            sublation_run.commit_run(
                self.run_dir,
                run,
                "test_run_item_rebound",
                {"item_id": "A1", "candidate_id": "alpha/rebound"},
            )
        with self.assertRaisesRegex(ValueError, "changed after the approved report"):
            sublation_promote.execute_approved(
                self.run_dir,
                allowed_targets={"A1": self.formal.resolve()},
                rollback_root=self.tmp / "rollbacks",
            )
        self.assertEqual((self.formal / "SKILL.md").read_text(encoding="utf-8"), "before\n")

    def test_phase_evidence_drift_after_report_is_rejected(self) -> None:
        self.approve()
        run = sublation_run.load_run(self.run_dir)
        evidence_path = Path(run["steps"]["phase-1"]["evidence"][0]["path"])
        evidence_path.write_text("tampered\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "evidence changed after report"):
            sublation_promote.execute_approved(
                self.run_dir,
                allowed_targets={"A1": self.formal.resolve()},
                rollback_root=self.tmp / "rollbacks",
            )
        self.assertEqual((self.formal / "SKILL.md").read_text(encoding="utf-8"), "before\n")

    def test_approved_patch_writes_only_sandbox_and_is_idempotent(self) -> None:
        approval = self.approve()
        self.assertEqual(approval["approval"]["state"], "APPROVED_PENDING_EXECUTION")
        result = sublation_promote.execute_approved(
            self.run_dir,
            allowed_targets={"A1": self.formal.resolve()},
            rollback_root=self.tmp / "rollbacks",
        )
        self.assertEqual(result["state"], "OBSERVING")
        self.assertEqual((self.formal / "SKILL.md").read_text(encoding="utf-8"), "before\nafter\n")
        rollback = self.tmp / "rollbacks" / "promote-run" / "A1" / "formal-before" / "SKILL.md"
        self.assertEqual(rollback.read_text(encoding="utf-8"), "before\n")
        rollback_link = rollback.parent / "LINK.txt"
        self.assertTrue(rollback_link.is_symlink())
        self.assertEqual(os.readlink(rollback_link), "shared.txt")
        second = sublation_promote.execute_approved(
            self.run_dir,
            allowed_targets={"A1": self.formal.resolve()},
            rollback_root=self.tmp / "rollbacks",
        )
        self.assertTrue(second["results"][0]["idempotent"])
        self.assertEqual(sublation_run.load_run(self.run_dir)["state"], "OBSERVING")
        with sublation_run.locked_run(self.run_dir):
            run = sublation_run.load_run(self.run_dir)
            run["state"] = "APPROVED_PENDING_EXECUTION"
            run["revision"] += 1
            run["updated_at"] = sublation_run.utc_now()
            sublation_run.commit_run(
                self.run_dir,
                run,
                "test_promotion_state_interruption",
                {"item_id": "A1", "state": "APPROVED_PENDING_EXECUTION"},
            )
        repaired = sublation_promote.execute_approved(
            self.run_dir,
            allowed_targets={"A1": self.formal.resolve()},
            rollback_root=self.tmp / "rollbacks",
        )
        self.assertTrue(repaired["results"][0]["idempotent"])
        self.assertEqual(sublation_run.load_run(self.run_dir)["state"], "OBSERVING")

    def test_report_markdown_drift_after_delivery_is_rejected_without_formal_write(self) -> None:
        self.approve()
        (self.run_dir / "report-v1.md").write_text("tampered report\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "plain report body differs"):
            sublation_promote.execute_approved(
                self.run_dir,
                allowed_targets={"A1": self.formal.resolve()},
                rollback_root=self.tmp / "rollbacks",
            )
        self.assertEqual((self.formal / "SKILL.md").read_text(encoding="utf-8"), "before\n")

    def test_post_hash_mismatch_restores_formal_target(self) -> None:
        self.approve()
        baseline_hash = sublation_run.tree_hash(self.formal)
        impossible_hash = "sha256:" + "0" * 64
        with mock.patch.object(sublation_promote, "expected_post_hash", return_value=impossible_hash):
            with self.assertRaisesRegex(ValueError, "post-promotion tree hash differs"):
                sublation_promote.execute_approved(
                    self.run_dir,
                    allowed_targets={"A1": self.formal.resolve()},
                    rollback_root=self.tmp / "rollbacks",
                )
        self.assertEqual(sublation_run.tree_hash(self.formal), baseline_hash)
        self.assertEqual((self.formal / "SKILL.md").read_text(encoding="utf-8"), "before\n")
        self.assertTrue((self.formal / "LINK.txt").is_symlink())
        failed = [
            entry
            for entry in sublation_run.verified_journal_entries(self.run_dir)
            if entry.get("type") == "promotion_failed"
        ]
        self.assertTrue(failed)
        self.assertTrue(failed[-1]["payload"]["rolled_back"])
        self.assertEqual(failed[-1]["payload"]["restored_tree_hash"], baseline_hash)

    def test_recorded_success_is_rejected_after_formal_tree_drift(self) -> None:
        self.approve()
        sublation_promote.execute_approved(
            self.run_dir,
            allowed_targets={"A1": self.formal.resolve()},
            rollback_root=self.tmp / "rollbacks",
        )
        (self.formal / "SKILL.md").write_text("before\nafter\ndrift\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "drifted after recorded promotion success"):
            sublation_promote.execute_approved(
                self.run_dir,
                allowed_targets={"A1": self.formal.resolve()},
                rollback_root=self.tmp / "rollbacks",
            )

    def test_crash_after_apply_recovers_without_double_patch(self) -> None:
        self.approve()
        script = (
            "from pathlib import Path; import sublation_promote; "
            f"sublation_promote.execute_approved(Path({str(self.run_dir)!r}), "
            f"allowed_targets={{'A1': Path({str(self.formal.resolve())!r})}}, "
            f"rollback_root=Path({str(self.tmp / 'rollbacks')!r}))"
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).parent)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["SUBLATION_TEST_CRASH_AFTER_APPLY"] = "1"
        result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 92)
        self.assertEqual((self.formal / "SKILL.md").read_text(encoding="utf-8"), "before\nafter\n")
        recovered = sublation_promote.execute_approved(
            self.run_dir,
            allowed_targets={"A1": self.formal.resolve()},
            rollback_root=self.tmp / "rollbacks",
        )
        self.assertTrue(recovered["results"][0]["idempotent"])
        self.assertTrue(recovered["results"][0]["recovered"])
        self.assertEqual(sublation_run.load_run(self.run_dir)["state"], "OBSERVING")


if __name__ == "__main__":
    unittest.main()
