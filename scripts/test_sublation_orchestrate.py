#!/usr/bin/env python3
"""End-to-end fixture for the configured one-shot worker runner."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import sublation_orchestrate
import sublation_promote
import sublation_receipt
import sublation_run


WORKER_SOURCE = r'''#!/usr/bin/env python3
import json
import hashlib
import os
import sys
from pathlib import Path

request_path, response_path, candidate_path = map(Path, sys.argv[1:4])
expected_actor = sys.argv[4]
request = json.loads(request_path.read_text(encoding="utf-8"))
task = request["task"]
assert task["assigned_actor"] == expected_actor
assert task["item"]["formal_target_redacted"] is True
assert task["item"]["target_path"] == request["source_snapshot"]["path"]
assert "SUBLATION_PARENT_SECRET" not in os.environ
source_path = Path(request["source_snapshot"]["path"])
assert (source_path / "LINK.txt").is_symlink()
assert os.readlink(source_path / "LINK.txt") == "shared.txt"
phase = task["phase"]
if phase in {"audit", "independent_verify", "boundary_review", "aggregate"}:
    snapshot = request["candidate_snapshot"]
    assert snapshot is not None
    candidate_snapshot_path = Path(snapshot["path"])
    assert task["item"]["candidate_path"] == str(candidate_snapshot_path)
    assert task["item"]["candidate_path_redacted"] is True
    assert (candidate_snapshot_path / "LINK.txt").is_symlink()
    assert os.readlink(candidate_snapshot_path / "LINK.txt") == "candidate-data.txt"
with response_path.with_suffix(".worker.log").open("a", encoding="utf-8") as handle:
    handle.write(phase + "\n")
statuses = {
    "observe": "OBSERVED",
    "candidate": "CANDIDATE_READY",
    "audit": "AUDIT_PASSED",
    "independent_verify": "VERIFY_PASSED",
    "boundary_review": "REVIEW_PASSED",
    "aggregate": "APPROVAL_READY",
}
result = {
    "step_status": "pass",
    "item_status": statuses[phase],
    "evidence": [],
    "blockers": [],
}
if phase == "candidate":
    candidate_path.mkdir(parents=True, exist_ok=True)
    (candidate_path / "PATCH.diff").write_text(
        "diff --git a/SKILL.md b/SKILL.md\n"
        "--- a/SKILL.md\n"
        "+++ b/SKILL.md\n"
        "@@ -1 +1,2 @@\n"
        " before\n"
        "+after\n",
        encoding="utf-8",
    )
    (candidate_path / "candidate-data.txt").write_text("candidate\n", encoding="utf-8")
    (candidate_path / "LINK.txt").symlink_to("candidate-data.txt")
    result["candidate_path"] = str(candidate_path)
if phase == "aggregate":
    result.update({
        "candidate_id": "fixture/one-shot-candidate",
        "summary": "保留原能力并加入一条经过三方复核的 fixture 变更。",
        "disposition": "promotion",
    })
response_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
'''

DELIVERY_SOURCE = r'''#!/usr/bin/env python3
import json
import hashlib
import sys
from pathlib import Path

request_path, response_path, capture_path = map(Path, sys.argv[1:4])
request = json.loads(request_path.read_text(encoding="utf-8"))
messages = json.loads(capture_path.read_text(encoding="utf-8")) if capture_path.exists() else {}
key = request["idempotency_key"]
if key not in messages:
    messages[key] = Path(request["report_path"]).read_text(encoding="utf-8")
    capture_path.write_text(json.dumps(messages, ensure_ascii=False), encoding="utf-8")
report_bytes = Path(request["report_path"]).read_bytes()
report_body_hash = "sha256:" + hashlib.sha256(report_bytes).hexdigest()
response_path.write_text(
    json.dumps({
        "message_ref": f"fixture-{key}",
        "sender_actor": "hermes",
        "report_body_hash": report_body_hash,
        "delivery_text_hash": "sha256:" + hashlib.sha256(report_bytes).hexdigest(),
    }),
    encoding="utf-8",
)
'''

PATCH_TEXT = (
    "diff --git a/SKILL.md b/SKILL.md\n"
    "--- a/SKILL.md\n"
    "+++ b/SKILL.md\n"
    "@@ -1 +1,2 @@\n"
    " before\n"
    "+after\n"
)


class SublationOrchestrateTests(unittest.TestCase):
    PRINCIPALS = {
        "codex": "openai-codex-test",
        "claude-code": "anthropic-claude-test",
        "hermes": "hermes-test",
    }

    def worker(self, actor: str, argv: list[str]) -> dict[str, object]:
        write_roots = [str(self.candidate_root)] if actor == "codex" else []
        read_roots: list[str] = []
        network_access = False
        return {
            "argv": argv,
            "timeout_seconds": 30,
            "cwd": str(self.tmp),
            "principal_id": self.PRINCIPALS[actor],
            "write_roots": write_roots,
            "read_roots": read_roots,
            "network_access": network_access,
            "adapter_fingerprint": sublation_run.sha256(
                {
                    "argv": argv,
                    "cwd": str(self.tmp),
                    "write_roots": write_roots,
                    "read_roots": read_roots,
                    "network_access": network_access,
                }
            ),
        }

    def worker_phase_count(self, run_dir: Path, phase: str) -> int:
        return sum(
            path.read_text(encoding="utf-8").splitlines().count(phase)
            for path in (run_dir / "worker-io").glob("*/*.worker.log")
        )

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="sublation-orchestrate-test-"))
        self.formal = self.tmp / "formal" / "fixture-skill"
        self.formal.mkdir(parents=True)
        (self.formal / "SKILL.md").write_text("before\n", encoding="utf-8")
        (self.formal / "shared.txt").write_text("shared\n", encoding="utf-8")
        (self.formal / "LINK.txt").symlink_to("shared.txt")
        self.candidate = self.tmp / "candidates" / "fixture-candidate"
        self.candidate_root = self.candidate.parent
        self.candidate_root.mkdir(parents=True)
        self.worker_script = self.tmp / "fixture_worker.py"
        self.worker_script.write_text(WORKER_SOURCE, encoding="utf-8")
        self.workers = {
            actor: self.worker(
                actor,
                [
                    sys.executable,
                    str(self.worker_script),
                    "{request}",
                    "{response}",
                    str(self.candidate),
                    actor,
                ],
            )
            for actor in ("codex", "claude-code", "hermes")
        }
        self.delivery_script = self.tmp / "fixture_delivery.py"
        self.delivery_script.write_text(DELIVERY_SOURCE, encoding="utf-8")
        self.delivery_capture = self.candidate_root / "delivered.json"
        self.delivery = {
            "actor": "hermes",
            "channel": "quadchat",
            "authorized_reply_senders": ["user"],
            "argv": [
                sys.executable,
                str(self.delivery_script),
                "{request}",
                "{response}",
                str(self.delivery_capture),
            ],
            "timeout_seconds": 30,
            "cwd": str(self.tmp),
            "write_roots": [str(self.candidate_root)],
            "read_roots": [],
            "network_access": False,
        }

    def test_task_lease_must_exceed_worker_timeout(self) -> None:
        run_dir = sublation_run.start_run(
            "把现有技能 sublation 一下吧",
            self.tmp / "runs",
            [{"name": "fixture", "path": str(self.formal.parent)}],
            "unsafe-lease",
        )
        with self.assertRaisesRegex(ValueError, "lease must exceed worker timeout"):
            sublation_orchestrate.run_until_wait(
                run_dir,
                self.workers,
                delivery=self.delivery,
                lease_seconds=30,
            )

    def test_write_root_overlapping_run_is_rejected_before_task_claim(self) -> None:
        run_dir = sublation_run.start_run(
            "把现有技能 sublation 一下吧",
            self.tmp / "runs",
            [{"name": "fixture", "path": str(self.formal.parent)}],
            "overlapping-write-root",
        )
        workers = {actor: dict(worker) for actor, worker in self.workers.items()}
        workers["codex"]["write_roots"] = [str(run_dir)]
        with self.assertRaisesRegex(ValueError, "isolated from the durable run directory"):
            sublation_orchestrate.run_until_wait(run_dir, workers, delivery=self.delivery)
        run = sublation_run.load_run(run_dir)
        self.assertIsNone(run["worker_identities"])
        self.assertEqual(run["tasks"]["A1:observe:r1"]["state"], "PENDING")

    def test_one_sentence_to_report_receipt_and_sandbox_promotion(self) -> None:
        run_dir = sublation_run.start_run(
            "把现有技能 sublation 一下吧",
            self.tmp / "runs",
            [{"name": "fixture", "path": str(self.formal)}],
            "one-shot-e2e",
        )
        result = sublation_orchestrate.run_until_wait(run_dir, self.workers, delivery=self.delivery)
        self.assertEqual(result["worker_steps_executed"], 6)
        self.assertEqual(result["state"], "USER_DECISION_REQUIRED")
        self.assertEqual((self.formal / "SKILL.md").read_text(encoding="utf-8"), "before\n")
        self.assertEqual(result["waiting_for_workers"], [])
        self.assertFalse(result["waiting_for_delivery"])
        messages = json.loads(self.delivery_capture.read_text(encoding="utf-8"))
        self.assertEqual(len(messages), 1)
        report = sublation_run.read_json(run_dir / "report-v1.json")
        message_ref = report["delivery"][0]["message_ref"]
        receipt_evidence = sublation_run.write_receipt_attestation(
            run_dir,
            {
                "adapter_id": "quadchat-local-test",
                "channel": "quadchat",
                "event_id": "approval-message-1",
                "sender_id": "user",
                "in_reply_to": message_ref,
                "message": "准A1",
                "received_at": "2026-07-10T00:00:00+00:00",
                "source_event_hash": sublation_run.sha256("approval-message-1-source"),
                "report_version": report["report_version"],
                "report_hash": report["report_hash"],
                "report_body_hash": report["plain_report_sha256"],
                "scope_revision": report["scope_revision"],
                "approval_code": report["approval_code"],
            },
        )
        receipt = sublation_receipt.apply_receipt(
            run_dir,
            receipt_evidence_path=receipt_evidence,
            report_version=report["report_version"],
            expected_report_hash=report["report_hash"],
            scope_revision=report["scope_revision"],
        )
        self.assertEqual(receipt["approval"]["authorized_scope"], ["A1"])
        self.assertEqual((self.formal / "SKILL.md").read_text(encoding="utf-8"), "before\n")

        promoted = sublation_promote.execute_approved(
            run_dir,
            allowed_targets={"A1": self.formal.resolve()},
            rollback_root=self.tmp / "rollback",
        )
        self.assertEqual(promoted["state"], "OBSERVING")
        self.assertEqual((self.formal / "SKILL.md").read_text(encoding="utf-8"), "before\nafter\n")
        self.assertTrue((self.tmp / "rollback" / "one-shot-e2e" / "A1" / "formal-before" / "SKILL.md").is_file())

    def test_repeated_adapter_failure_closes_as_blocked_via_coordinator(self) -> None:
        failing = self.tmp / "failing_worker.py"
        failing.write_text("raise SystemExit(7)\n", encoding="utf-8")
        workers = dict(self.workers)
        for actor in ("codex", "hermes"):
            workers[actor] = self.worker(
                actor, [sys.executable, str(failing), "{request}", "{response}", actor]
            )
        run_dir = sublation_run.start_run(
            "把现有技能 sublation 一下吧",
            self.tmp / "runs-failure",
            [{"name": "fixture", "path": str(self.formal)}],
            "failure-e2e",
        )
        result = sublation_orchestrate.run_until_wait(
            run_dir,
            workers,
            delivery=self.delivery,
            max_releases=2,
        )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["worker_steps_executed"], 3)
        self.assertTrue(result["latest_report"])
        self.assertIn("worker_exit", (run_dir / "report-v1.md").read_text(encoding="utf-8"))
        self.assertEqual((self.formal / "SKILL.md").read_text(encoding="utf-8"), "before\n")

    def test_worker_is_prevented_from_writing_formal_target(self) -> None:
        malicious = self.tmp / "malicious_worker.py"
        malicious.write_text(
            "from pathlib import Path; import sys; "
            "(Path(sys.argv[3]) / 'SKILL.md').write_text('pwned\\n', encoding='utf-8')\n",
            encoding="utf-8",
        )
        argv = [sys.executable, str(malicious), "{request}", "{response}", str(self.formal)]
        workers = dict(self.workers)
        for actor in ("codex", "hermes"):
            workers[actor] = self.worker(actor, [*argv, actor])
        run_dir = sublation_run.start_run(
            "把现有技能 sublation 一下吧",
            self.tmp / "runs-malicious",
            [{"name": "fixture", "path": str(self.formal)}],
            "malicious-e2e",
        )
        result = sublation_orchestrate.run_until_wait(
            run_dir,
            workers,
            delivery=self.delivery,
            max_releases=1,
        )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual((self.formal / "SKILL.md").read_text(encoding="utf-8"), "before\n")

    def test_worker_is_prevented_from_writing_unrelated_path(self) -> None:
        protected = self.tmp / "unrelated" / "protected.txt"
        protected.parent.mkdir()
        protected.write_text("before\n", encoding="utf-8")
        malicious = self.tmp / "unrelated_writer.py"
        malicious.write_text(
            "from pathlib import Path; import sys; "
            "Path(sys.argv[3]).write_text('pwned\\n', encoding='utf-8')\n",
            encoding="utf-8",
        )
        argv = [sys.executable, str(malicious), "{request}", "{response}", str(protected)]
        workers = dict(self.workers)
        for actor in ("codex", "hermes"):
            workers[actor] = self.worker(actor, [*argv, actor])
        run_dir = sublation_run.start_run(
            "把现有技能 sublation 一下吧",
            self.tmp / "runs-unrelated-writer",
            [{"name": "fixture", "path": str(self.formal)}],
            "unrelated-writer-e2e",
        )
        result = sublation_orchestrate.run_until_wait(
            run_dir,
            workers,
            delivery=self.delivery,
            max_releases=1,
        )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(protected.read_text(encoding="utf-8"), "before\n")

    def test_worker_is_prevented_from_modifying_the_run_ledger(self) -> None:
        malicious = self.tmp / "ledger_writer.py"
        malicious.write_text(
            "from pathlib import Path; import sys; "
            "Path(sys.argv[3]).write_text('{}\\n', encoding='utf-8')\n",
            encoding="utf-8",
        )
        run_dir = sublation_run.start_run(
            "把现有技能 sublation 一下吧",
            self.tmp / "runs-ledger-writer",
            [{"name": "fixture", "path": str(self.formal)}],
            "ledger-writer-e2e",
        )
        argv = [sys.executable, str(malicious), "{request}", "{response}", str(run_dir / "run.json")]
        workers = dict(self.workers)
        for actor in ("codex", "hermes"):
            workers[actor] = self.worker(actor, [*argv, actor])
        result = sublation_orchestrate.run_until_wait(
            run_dir,
            workers,
            delivery=self.delivery,
            max_releases=1,
        )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(sublation_run.load_run(run_dir)["state"], "BLOCKED")

    def test_worker_cannot_read_run_attestation_key(self) -> None:
        reader = self.tmp / "key_reader.py"
        reader.write_text(
            "from pathlib import Path; import sys; Path(sys.argv[3]).read_bytes()\n",
            encoding="utf-8",
        )
        run_dir = sublation_run.start_run(
            "把现有技能 sublation 一下吧",
            self.tmp / "runs-key-reader",
            [{"name": "fixture", "path": str(self.formal)}],
            "key-reader-e2e",
        )
        argv = [
            sys.executable,
            str(reader),
            "{request}",
            "{response}",
            str(sublation_run.control_key_path(run_dir)),
        ]
        workers = dict(self.workers)
        for actor in ("codex", "hermes"):
            workers[actor] = self.worker(actor, [*argv, actor])
        result = sublation_orchestrate.run_until_wait(
            run_dir,
            workers,
            delivery=self.delivery,
            max_releases=1,
        )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertIn("worker_exit", (run_dir / "report-v1.md").read_text(encoding="utf-8"))

    def test_worker_cannot_read_unlisted_host_file(self) -> None:
        protected = self.tmp / "private" / "secret.txt"
        protected.parent.mkdir()
        protected.write_text("host-secret\n", encoding="utf-8")
        reader = self.tmp / "host_file_reader.py"
        reader.write_text(
            "from pathlib import Path; import sys; Path(sys.argv[3]).read_text(encoding='utf-8')\n",
            encoding="utf-8",
        )
        argv = [sys.executable, str(reader), "{request}", "{response}", str(protected)]
        workers = dict(self.workers)
        workers["codex"] = self.worker("codex", [*argv, "codex"])
        run_dir = sublation_run.start_run(
            "把现有技能 sublation 一下吧",
            self.tmp / "runs-host-file-reader",
            [{"name": "fixture", "path": str(self.formal)}],
            "host-file-reader-e2e",
        )
        result = sublation_orchestrate.run_until_wait(
            run_dir,
            workers,
            delivery=self.delivery,
            max_releases=1,
        )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertIn("worker_exit", (run_dir / "report-v1.md").read_text(encoding="utf-8"))
        self.assertEqual(protected.read_text(encoding="utf-8"), "host-secret\n")

    def test_reviewer_cannot_modify_live_candidate(self) -> None:
        malicious = self.tmp / "candidate_writer.py"
        malicious.write_text(
            "from pathlib import Path; import sys; "
            "(Path(sys.argv[3]) / 'PATCH.diff').write_text('tampered\\n', encoding='utf-8')\n",
            encoding="utf-8",
        )
        workers = dict(self.workers)
        workers["claude-code"] = self.worker(
            "claude-code",
            [sys.executable, str(malicious), "{request}", "{response}", str(self.candidate)],
        )
        run_dir = sublation_run.start_run(
            "把现有技能 sublation 一下吧",
            self.tmp / "runs-candidate-writer",
            [{"name": "fixture", "path": str(self.formal)}],
            "candidate-writer-e2e",
        )
        result = sublation_orchestrate.run_until_wait(
            run_dir,
            workers,
            delivery=self.delivery,
            max_releases=1,
        )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual((self.candidate / "PATCH.diff").read_text(encoding="utf-8"), PATCH_TEXT)
        self.assertIn("worker_exit", (run_dir / "report-v1.md").read_text(encoding="utf-8"))

    def test_parent_secret_is_not_inherited_by_workers(self) -> None:
        run_dir = sublation_run.start_run(
            "把现有技能 sublation 一下吧",
            self.tmp / "runs-sanitized-env",
            [{"name": "fixture", "path": str(self.formal)}],
            "sanitized-env-e2e",
        )
        with mock.patch.dict(os.environ, {"SUBLATION_PARENT_SECRET": "must-not-leak"}):
            result = sublation_orchestrate.run_until_wait(
                run_dir,
                self.workers,
                delivery=self.delivery,
            )
        self.assertEqual(result["state"], "USER_DECISION_REQUIRED")

    def test_network_policy_is_fail_closed_unless_explicitly_enabled(self) -> None:
        run_dir = sublation_run.start_run(
            "把现有技能 sublation 一下吧",
            self.tmp / "runs-network-policy",
            [{"name": "fixture", "path": str(self.formal)}],
            "network-policy-e2e",
        )
        run = sublation_run.load_run(run_dir)
        denied = sublation_orchestrate.sandbox_profile(
            run_dir,
            run,
            argv=[sys.executable, str(self.worker_script)],
            network_access=False,
        )
        allowed = sublation_orchestrate.sandbox_profile(
            run_dir,
            run,
            argv=[sys.executable, str(self.worker_script)],
            network_access=True,
        )
        self.assertIn("(deny network*)", denied)
        self.assertNotIn("(deny network*)", allowed)

    def run_in_subprocess(self, run_dir: Path, env_key: str, *, finalize: bool = True) -> subprocess.CompletedProcess[str]:
        script = (
            "from pathlib import Path; import sublation_orchestrate; "
            f"sublation_orchestrate.run_until_wait(Path({str(run_dir)!r}), {self.workers!r}, "
            f"delivery={self.delivery!r}, finalize={finalize!r})"
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).parent)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env[env_key] = "1"
        return subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True)

    def test_crash_before_worker_response_resumes_same_task(self) -> None:
        run_dir = sublation_run.start_run(
            "把现有技能 sublation 一下吧",
            self.tmp / "runs-crash-before",
            [{"name": "fixture", "path": str(self.formal)}],
            "crash-before-response",
        )
        crashed = self.run_in_subprocess(run_dir, "SUBLATION_TEST_CRASH_BEFORE_WORKER_RESPONSE")
        self.assertEqual(crashed.returncode, 93)
        resumed = sublation_orchestrate.run_until_wait(run_dir, self.workers, delivery=self.delivery)
        self.assertEqual(resumed["state"], "USER_DECISION_REQUIRED")
        self.assertEqual(self.worker_phase_count(run_dir, "observe"), 1)

    def test_crash_after_worker_response_reuses_response_without_duplicate_worker(self) -> None:
        run_dir = sublation_run.start_run(
            "把现有技能 sublation 一下吧",
            self.tmp / "runs-crash-after",
            [{"name": "fixture", "path": str(self.formal)}],
            "crash-after-response",
        )
        crashed = self.run_in_subprocess(run_dir, "SUBLATION_TEST_CRASH_AFTER_WORKER_RESPONSE")
        self.assertEqual(crashed.returncode, 94)
        resumed = sublation_orchestrate.run_until_wait(run_dir, self.workers, delivery=self.delivery)
        self.assertEqual(resumed["state"], "USER_DECISION_REQUIRED")
        self.assertEqual(self.worker_phase_count(run_dir, "observe"), 1)

    def test_crash_after_delivery_send_records_exactly_one_message_on_resume(self) -> None:
        run_dir = sublation_run.start_run(
            "把现有技能 sublation 一下吧",
            self.tmp / "runs-delivery-crash",
            [{"name": "fixture", "path": str(self.formal)}],
            "crash-after-delivery",
        )
        sublation_orchestrate.run_until_wait(run_dir, self.workers, finalize=False)
        crashed = self.run_in_subprocess(run_dir, "SUBLATION_TEST_CRASH_AFTER_DELIVERY_SEND")
        self.assertEqual(crashed.returncode, 96)
        resumed = sublation_orchestrate.run_until_wait(run_dir, self.workers, delivery=self.delivery)
        self.assertEqual(resumed["state"], "USER_DECISION_REQUIRED")
        messages = json.loads(self.delivery_capture.read_text(encoding="utf-8"))
        self.assertEqual(len(messages), 1)
        report = sublation_run.read_json(run_dir / "report-v1.json")
        self.assertEqual(len(report["delivery"]), 1)

    def test_crash_after_delivery_report_write_repairs_missing_journal(self) -> None:
        run_dir = sublation_run.start_run(
            "把现有技能 sublation 一下吧",
            self.tmp / "runs-delivery-journal-crash",
            [{"name": "fixture", "path": str(self.formal)}],
            "crash-after-delivery-report-write",
        )
        sublation_orchestrate.run_until_wait(run_dir, self.workers, finalize=False)
        crashed = self.run_in_subprocess(
            run_dir, "SUBLATION_TEST_CRASH_AFTER_DELIVERY_REPORT_WRITE"
        )
        self.assertEqual(crashed.returncode, 98)
        resumed = sublation_orchestrate.run_until_wait(run_dir, self.workers, delivery=self.delivery)
        self.assertEqual(resumed["state"], "USER_DECISION_REQUIRED")
        messages = json.loads(self.delivery_capture.read_text(encoding="utf-8"))
        self.assertEqual(len(messages), 1)
        recovered = [
            entry
            for entry in sublation_run.journal_entries(run_dir)
            if entry.get("type") == "report_delivery_recovered"
        ]
        self.assertEqual(len(recovered), 1)

    def test_second_orchestrator_process_is_rejected_while_lock_is_held(self) -> None:
        run_dir = sublation_run.start_run(
            "把现有技能 sublation 一下吧",
            self.tmp / "runs-concurrent",
            [{"name": "fixture", "path": str(self.formal)}],
            "concurrent-runner",
        )
        ready = self.tmp / "orchestrator-lock-ready"
        script = (
            "import time; from pathlib import Path; import sublation_orchestrate; "
            f"rd=Path({str(run_dir)!r}); ready=Path({str(ready)!r}); "
            "ctx=sublation_orchestrate.orchestrator_lock(rd); ctx.__enter__(); "
            "ready.write_text('ready'); time.sleep(10)"
        )
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).parent), "PYTHONDONTWRITEBYTECODE": "1"}
        holder = subprocess.Popen([sys.executable, "-c", script], env=env)
        try:
            for _ in range(100):
                if ready.exists():
                    break
                time.sleep(0.02)
            self.assertTrue(ready.exists())
            with self.assertRaisesRegex(RuntimeError, "already active"):
                sublation_orchestrate.run_until_wait(run_dir, self.workers, finalize=False)
            self.assertEqual(self.worker_phase_count(run_dir, "observe"), 0)
        finally:
            holder.terminate()
            holder.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
