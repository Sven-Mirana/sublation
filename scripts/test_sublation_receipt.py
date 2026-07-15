#!/usr/bin/env python3
"""Fixture tests for channel-neutral, version-bound approval receipts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import sublation_receipt
import sublation_run


class SublationReceiptTests(unittest.TestCase):
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
        path.write_text(json.dumps({"label": label}, sort_keys=True) + "\n", encoding="utf-8")
        return str(path)

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="sublation-receipt-test-"))
        roots = [
            {"name": "alpha", "path": str(self.tmp / "alpha")},
            {"name": "beta", "path": str(self.tmp / "beta")},
        ]
        for root in roots:
            path = Path(root["path"])
            path.mkdir(parents=True)
            (path / "SKILL.md").write_text("before\n", encoding="utf-8")
        self.run_dir = sublation_run.start_run("把现有技能 sublation 一下吧", self.tmp / "runs", roots, "receipt-run")
        sublation_run.bind_worker_identities(
            self.run_dir,
            {
                actor: {
                    **identity,
                    "write_roots": [str(self.tmp / "candidates")] if actor == "codex" else [],
                }
                for actor, identity in self.IDENTITIES.items()
            },
        )
        for index, item_id in enumerate(("A1", "A2"), start=1):
            candidate = self.tmp / "candidates" / item_id
            candidate.mkdir(parents=True)
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
            for phase_index, (actor, phase, status) in enumerate(phases, start=1):
                task = sublation_run.claim_task(self.run_dir, actor, 120, item_id)
                assert task is not None
                sublation_run.record_step(
                    self.run_dir,
                    step_id=f"{item_id}-phase-{phase_index}",
                    item_id=item_id,
                    actor=actor,
                    phase=phase,
                    step_status="pass",
                    item_status=status,
                    candidate_path=str(candidate) if status == "CANDIDATE_READY" else None,
                    evidence=[self.evidence(f"{item_id}-phase-{phase_index}-{phase}")],
                    task_id=task["task_id"],
                    lease_token=task["lease"]["token"],
                    executor_principal=self.IDENTITIES[actor]["principal_id"],
                    adapter_fingerprint=self.IDENTITIES[actor]["adapter_fingerprint"],
                    candidate_tree_hash=(
                        sublation_run.tree_hash(candidate)
                        if phase in {"audit", "independent_verify", "boundary_review"}
                        else None
                    ),
                )
            final_task = sublation_run.claim_task(self.run_dir, "hermes", 120, item_id)
            assert final_task is not None
            sublation_run.record_step(
                self.run_dir,
                step_id=f"final-{item_id}",
                item_id=item_id,
                actor="hermes",
                phase="aggregate",
                step_status="pass",
                item_status="APPROVAL_READY",
                disposition="promotion",
                candidate_id=f"candidate-{index}",
                summary=f"Candidate {index}",
                evidence=[self.evidence(f"{item_id}-aggregate")],
                task_id=final_task["task_id"],
                lease_token=final_task["lease"]["token"],
                executor_principal=self.IDENTITIES["hermes"]["principal_id"],
                adapter_fingerprint=self.IDENTITIES["hermes"]["adapter_fingerprint"],
                candidate_tree_hash=sublation_run.tree_hash(candidate),
            )
        self.report = sublation_run.finalize_report(self.run_dir)
        report_body_hash = self.report["plain_report_sha256"]
        delivery_text_hash = sublation_run.sha256(b"delivered test report")
        delivery_evidence = self.run_dir / "evidence" / "delivery-report-message-1.json"
        sublation_run.atomic_write_json(
            delivery_evidence,
            {
                "message_ref": "report-message-1",
                "sender_actor": "hermes",
                "report_body_hash": report_body_hash,
                "delivery_text_hash": delivery_text_hash,
            },
        )
        self.report = sublation_run.record_delivery(
            self.run_dir,
            "quadchat",
            "report-message-1",
            ["user"],
            sender_actor="hermes",
            idempotency_key="receipt-report-message-1",
            adapter_evidence_path=str(delivery_evidence),
            report_body_hash=report_body_hash,
            delivery_text_hash=delivery_text_hash,
        )

    def receipt_evidence(self, message: str, event_id: str, **kwargs: object) -> Path:
        payload = {
            "adapter_id": str(kwargs.pop("adapter_id", "quadchat-local-test")),
            "channel": str(kwargs.pop("channel", "quadchat")),
            "event_id": event_id,
            "sender_id": str(kwargs.pop("sender_id", "user")),
            "in_reply_to": str(kwargs.pop("in_reply_to", "report-message-1") or ""),
            "message": message,
            "received_at": "2026-07-10T00:00:00+00:00",
            "source_event_hash": sublation_run.sha256({"event_id": event_id, "message": message}),
            "report_version": kwargs.pop("evidence_report_version", self.report["report_version"]),
            "report_hash": kwargs.pop("evidence_report_hash", self.report["report_hash"]),
            "report_body_hash": kwargs.pop(
                "evidence_report_body_hash", self.report["delivery"][0]["report_body_hash"]
            ),
            "scope_revision": kwargs.pop("evidence_scope_revision", self.report["scope_revision"]),
            "approval_code": kwargs.pop("evidence_approval_code", self.report["approval_code"]),
        }
        if kwargs:
            raise AssertionError(f"unused receipt evidence options: {sorted(kwargs)}")
        return sublation_run.write_receipt_attestation(self.run_dir, payload)

    def apply(self, message: str, event_id: str, **kwargs: object) -> dict:
        receipt_options = {
            key: kwargs.pop(key)
            for key in list(kwargs)
            if key in {
                "adapter_id",
                "channel",
                "sender_id",
                "in_reply_to",
                "evidence_report_version",
                "evidence_report_hash",
                "evidence_report_body_hash",
                "evidence_scope_revision",
                "evidence_approval_code",
            }
        }
        evidence = self.receipt_evidence(message, event_id, **receipt_options)
        return sublation_receipt.apply_receipt(
            self.run_dir,
            receipt_evidence_path=evidence,
            **kwargs,
        )

    def test_unmentioned_items_remain_pending(self) -> None:
        result = self.apply("A1 批准", "user-1")
        decisions = result["approval"]["decisions"]
        self.assertEqual(decisions["A1"]["decision"], "approve")
        self.assertEqual(decisions["A2"]["decision"], "pending")
        self.assertEqual(result["approval"]["state"], "APPROVED_PENDING_EXECUTION")

    def test_all_approve_reaches_pending_execution_not_promotion(self) -> None:
        result = self.apply("全部批准", "user-2")
        self.assertEqual(result["approval"]["state"], "APPROVED_PENDING_EXECUTION")
        self.assertEqual(result["approval"]["authorized_scope"], ["A1", "A2"])
        self.assertIn("never executes promotion", result["approval"]["boundary"])

    def test_negative_approval_phrases_never_authorize(self) -> None:
        chinese_cases = tuple(
            f"A1 {prefix}{action}"
            for action in ("批准", "同意", "通过")
            for prefix in ("未", "没有", "尚未", "不予", "无法", "不能", "不可", "拒绝", "不")
        )
        english_cases = ("A1 not approved", "A1 cannot approve", "A1 unable to approve")
        for message in (*chinese_cases, *english_cases):
            with self.subTest(message=message):
                parsed = sublation_receipt.parse_decisions(message, ["A1"])
                self.assertEqual(parsed, {"A1": "reject"})

    def test_productive_negative_modifiers_never_fall_through_to_approve(self) -> None:
        reject_cases = (
            "不要批准A1",
            "请勿批准A1",
            "不同意批准A1",
            "别批准A1",
            "切勿通过A1",
            "禁止同意A1",
            "A1无须批准",
            "不建议批准A1",
            "不推荐同意A1",
            "A1不考虑通过",
            "千万别批准A1",
            "A1并未批准",
            "please do not approve A1",
            "never approve A1",
            "please don't ever approve A1",
            "we should not currently approve A1",
            "unable right now to approve A1",
        )
        hold_cases = (
            "先不要批准A1",
            "暂缓批准A1",
            "暂时不同意A1",
            "A1先别通过",
            "延后批准A1",
            "暂时考虑批准A1",
            "A1稍后通过",
            "hold approval A1",
            "not yet approved A1",
            "not yet ready to approve A1",
            "approve later A1",
        )
        for message in reject_cases:
            with self.subTest(message=message):
                self.assertEqual(
                    sublation_receipt.parse_decisions(message, ["A1"]),
                    {"A1": "reject"},
                )
        for message in hold_cases:
            with self.subTest(message=message):
                self.assertEqual(
                    sublation_receipt.parse_decisions(message, ["A1"]),
                    {"A1": "hold"},
                )
        for modifier in sublation_receipt.REJECT_ZH_MODIFIERS:
            for action in sublation_receipt.MODIFIED_ZH_ACTIONS:
                message = f"{modifier}{action}A1"
                with self.subTest(message=message):
                    self.assertEqual(
                        sublation_receipt.parse_decisions(message, ["A1"]),
                        {"A1": "reject"},
                    )
        for modifier in sublation_receipt.HOLD_ZH_MODIFIERS:
            for action in sublation_receipt.MODIFIED_ZH_ACTIONS:
                message = f"{modifier}{action}A1"
                with self.subTest(message=message):
                    self.assertEqual(
                        sublation_receipt.parse_decisions(message, ["A1"]),
                        {"A1": "hold"},
                    )
        applied = self.apply("先不要批准A1", "user-productive-negative-e2e")
        self.assertEqual(applied["approval"]["decisions"]["A1"]["decision"], "hold")
        self.assertEqual(applied["approval"]["authorized_scope"], [])
        self.assertEqual(applied["approval"]["state"], "USER_DECISION_REQUIRED")
        self.assertEqual(
            sublation_receipt.parse_decisions("无条件批准A1", ["A1"]),
            {"A1": "approve"},
        )
        self.assertEqual(
            sublation_receipt.parse_decisions("没问题批准A1", ["A1"]),
            {"A1": "approve"},
        )
        self.assertEqual(
            sublation_receipt.parse_decisions("A1不批准 A2批准", ["A1", "A2"]),
            {"A1": "reject", "A2": "approve"},
        )

    def test_negative_all_decision_never_authorizes(self) -> None:
        self.assertEqual(
            sublation_receipt.parse_decisions("全部尚未通过", ["A1", "A2"]),
            {"A1": "reject", "A2": "reject"},
        )
        self.assertEqual(
            sublation_receipt.parse_decisions("全部暂缓批准", ["A1", "A2"]),
            {"A1": "hold", "A2": "hold"},
        )
        self.assertEqual(
            sublation_receipt.parse_decisions("全部不建议批准", ["A1", "A2"]),
            {"A1": "reject", "A2": "reject"},
        )
        self.assertEqual(
            sublation_receipt.parse_decisions("全部以后再批准", ["A1", "A2"]),
            {"A1": "hold", "A2": "hold"},
        )

    def test_chinese_punctuation_and_mixed_decisions(self) -> None:
        result = self.apply("A1：同意；A2：暂缓。", "user-3")
        decisions = result["approval"]["decisions"]
        self.assertEqual(decisions["A1"]["decision"], "approve")
        self.assertEqual(decisions["A2"]["decision"], "hold")

    def test_comma_separated_explicit_decisions_are_directional(self) -> None:
        cases = (
            ("A1 批准，A2 暂缓", {"A1": "approve", "A2": "hold"}),
            ("A2 暂缓，A1 批准", {"A1": "approve", "A2": "hold"}),
            ("A1 暂缓，A2 批准", {"A1": "hold", "A2": "approve"}),
        )
        for message, expected in cases:
            with self.subTest(message=message):
                self.assertEqual(sublation_receipt.parse_decisions(message, ["A1", "A2"]), expected)

    def test_comma_list_inherits_one_unambiguous_action(self) -> None:
        self.assertEqual(
            sublation_receipt.parse_decisions("批准 A1,A3", ["A1", "A2", "A3"]),
            {"A1": "approve", "A3": "approve"},
        )

    def test_item_between_conflicting_actions_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "ambiguous decision"):
            sublation_receipt.parse_decisions("批准 A1 暂缓", ["A1", "A2"])

    def test_short_zh_approve_form_is_supported(self) -> None:
        result = self.apply("准A1、A2", "user-short")
        self.assertEqual(result["approval"]["authorized_scope"], ["A1", "A2"])

    def test_exclusion_expression_is_explicitly_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "exclusion syntax"):
            self.apply("除了A2都批准", "user-exclusion")

    def test_decision_can_be_withdrawn_and_edited(self) -> None:
        self.apply("A1批准，A2批准", "user-4")
        result = self.apply("撤回 A1；A2 改为暂缓", "user-5")
        decisions = result["approval"]["decisions"]
        self.assertEqual(decisions["A1"]["decision"], "pending")
        self.assertEqual(decisions["A2"]["decision"], "hold")

    def test_duplicate_event_is_idempotent_and_conflict_rejected(self) -> None:
        first = self.apply("A1批准", "user-6")
        duplicate = self.apply("A1批准", "user-6")
        self.assertFalse(first["idempotent"])
        self.assertTrue(duplicate["idempotent"])
        with self.assertRaisesRegex(ValueError, "collision"):
            self.apply("A1驳回", "user-6")

    def test_unattested_or_tampered_receipt_evidence_is_rejected(self) -> None:
        evidence = self.receipt_evidence("A1批准", "user-attestation-tamper")
        payload = sublation_run.read_json(evidence)
        payload["message"] = "全部批准"
        sublation_run.atomic_write_json(evidence, payload)
        with self.assertRaisesRegex(ValueError, "MAC verification failed"):
            sublation_receipt.apply_receipt(self.run_dir, receipt_evidence_path=evidence)

    def test_report_body_hash_is_required_bound_and_stored(self) -> None:
        expected = self.report["delivery"][0]["report_body_hash"]
        result = self.apply("A1批准", "user-report-body")
        approval = result["approval"]
        self.assertEqual(approval["report_body_hash"], expected)
        self.assertEqual(approval["events"][0]["report_body_hash"], expected)
        self.assertEqual(sublation_run.load_run(self.run_dir)["approval"]["report_body_hash"], expected)
        journal = [
            entry["payload"]
            for entry in sublation_run.verified_journal_entries(self.run_dir)
            if entry.get("type") == "approval_receipt_recorded"
            and entry.get("payload", {}).get("event_id") == "user-report-body"
        ]
        self.assertEqual(len(journal), 1)
        self.assertEqual(journal[0]["report_body_hash"], expected)

    def test_missing_or_stale_report_body_hash_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "report_body_hash"):
            self.apply("A1批准", "user-missing-report-body", evidence_report_body_hash=None)
        with self.assertRaisesRegex(ValueError, "report_body_hash"):
            self.apply(
                "A1批准",
                "user-stale-report-body",
                evidence_report_body_hash="sha256:stale",
            )

    def test_duplicate_event_does_not_override_later_durable_state(self) -> None:
        self.apply("A1批准", "user-repair")
        with sublation_run.locked_run(self.run_dir):
            run = sublation_run.load_run(self.run_dir)
            run["state"] = "OBSERVING"
            run["revision"] += 1
            run["updated_at"] = sublation_run.utc_now()
            sublation_run.commit_run(
                self.run_dir,
                run,
                "test_later_durable_state",
                {"state": "OBSERVING"},
            )
        duplicate = self.apply("A1批准", "user-repair")
        self.assertTrue(duplicate["idempotent"])
        self.assertEqual(sublation_run.load_run(self.run_dir)["state"], "OBSERVING")

    def test_duplicate_event_rejects_forged_approval_cache(self) -> None:
        self.apply("A1批准", "user-cache-forgery")
        path = self.run_dir / "approval.json"
        approval = sublation_run.read_json(path)
        approval["authorized_scope"] = ["A1", "A2"]
        sublation_run.atomic_write_json(path, approval)
        with self.assertRaisesRegex(ValueError, "authorized_scope cannot be replayed"):
            self.apply("A1批准", "user-cache-forgery")

    def test_crash_after_approval_write_recovers_original_receipt_journal_event(self) -> None:
        receipt = self.receipt_evidence("A1批准", "user-crash")
        script = (
            "from pathlib import Path; import sublation_receipt; "
            f"sublation_receipt.apply_receipt(Path({str(self.run_dir)!r}), "
            f"receipt_evidence_path=Path({str(receipt)!r}))"
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).parent)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["SUBLATION_TEST_CRASH_AFTER_APPROVAL_WRITE"] = "1"
        crashed = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True)
        self.assertEqual(crashed.returncode, 97)
        recovered = self.apply("A1批准", "user-crash")
        self.assertTrue(recovered["idempotent"])
        recorded = [
            entry
            for entry in sublation_run.journal_entries(self.run_dir)
            if entry.get("type") == "approval_receipt_recorded"
            and entry.get("payload", {}).get("event_id") == "user-crash"
        ]
        self.assertEqual(len(recorded), 1)

    def test_unknown_item_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown item"):
            self.apply("A9批准", "user-7")

    def test_wrong_channel_or_reply_binding_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "binding"):
            self.apply("全部批准", "user-8", channel="feishu")
        with self.assertRaisesRegex(ValueError, "binding"):
            self.apply("全部批准", "user-9", in_reply_to="old-message")
        with self.assertRaisesRegex(ValueError, "sender binding"):
            self.apply("全部批准", "user-wrong-sender", sender_id="not-user")

    def test_missing_in_reply_to_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing fields: in_reply_to"):
            self.apply("全部批准", "user-missing-reply", in_reply_to=None)

    def test_stale_report_version_hash_and_scope_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "stale report version"):
            sublation_receipt.apply_receipt(
                self.run_dir,
                receipt_evidence_path=self.receipt_evidence("全部批准", "user-10"),
                report_version=self.report["report_version"] + 1,
            )
        with self.assertRaisesRegex(ValueError, "stale report hash"):
            sublation_receipt.apply_receipt(
                self.run_dir,
                receipt_evidence_path=self.receipt_evidence("全部批准", "user-11"),
                expected_report_hash="sha256:old",
            )
        with self.assertRaisesRegex(ValueError, "stale scope"):
            sublation_receipt.apply_receipt(
                self.run_dir,
                receipt_evidence_path=self.receipt_evidence("全部批准", "user-12"),
                scope_revision=self.report["scope_revision"] + 1,
            )


if __name__ == "__main__":
    unittest.main()
