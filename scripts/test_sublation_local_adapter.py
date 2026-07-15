#!/usr/bin/env python3
"""Offline tests for the built-in local Sublation adapter package."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import sublation_local_adapter
import sublation_one_shot
import sublation_receipt
import sublation_run


FAKE_ENGINE = r'''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

STYLE = __STYLE__
if "--version" in sys.argv:
    print("fake-" + STYLE + " 1.0")
    raise SystemExit(0)

request_path = Path(os.environ["SUBLATION_REQUEST_PATH"])
candidate_root = Path(os.environ["SUBLATION_CANDIDATE_ROOT"])
request = json.loads(request_path.read_text(encoding="utf-8"))
task = request["task"]
phase = task["phase"]
attempt = int(task["attempt"])
evidence = request_path.parent / (task["task_id"].replace(":", "-") + ".engine-evidence.json")
evidence.write_text(json.dumps({"phase": phase, "actor": task["assigned_actor"]}), encoding="utf-8")
statuses = {
    "observe": "OBSERVED",
    "candidate": "CANDIDATE_READY",
    "candidate_rework": "CANDIDATE_READY",
    "audit": "AUDIT_PASSED",
    "independent_verify": "VERIFY_PASSED",
    "boundary_review": "REVIEW_PASSED",
    "aggregate": "APPROVAL_READY",
}
result = {
    "step_status": "pass",
    "item_status": statuses[phase],
    "evidence": [str(evidence)],
    "blockers": [],
}
if phase == "independent_verify" and attempt == 1 and os.environ.get("SUBLATION_FAKE_HOLD_ONCE") == "1":
    result.update({"step_status": "hold", "item_status": "REWORK_REQUIRED", "blockers": ["fixture rework"]})
candidate = candidate_root / "fixture" / (
    task["run_id"] + "-" + task["item_id"].lower() + "-" + phase + "-r" + str(attempt)
)
if phase in {"candidate", "candidate_rework"}:
    candidate.mkdir(parents=True, exist_ok=True)
    (candidate / "PATCH.diff").write_text(
        "diff --git a/SKILL.md b/SKILL.md\n"
        "--- a/SKILL.md\n"
        "+++ b/SKILL.md\n"
        "@@ -1 +1,2 @@\n"
        " before\n"
        "+after\n",
        encoding="utf-8",
    )
    result["candidate_path"] = str(candidate)
if phase == "aggregate":
    result.update({
        "candidate_id": "fixture/local-one-shot",
        "summary": "A locally orchestrated fixture candidate is ready.",
        "disposition": "promotion",
    })

if STYLE == "codex":
    output = Path(sys.argv[sys.argv.index("-o") + 1])
    output.write_text(json.dumps(result), encoding="utf-8")
elif STYLE == "claude":
    print(json.dumps({"structured_output": result}))
else:
    print("```json\n" + json.dumps(result) + "\n```")
'''


class RoomState:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []
        self.posts = 0


def room_handler(state: RoomState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def send_payload(self, value: dict[str, object]) -> None:
            encoded = json.dumps(value).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:
            self.send_payload({"messages": state.messages})

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            state.posts += 1
            message = {
                "id": f"room-{state.posts}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **payload,
            }
            state.messages.append(message)
            self.send_payload({"message": message})

    return Handler


class SublationOneShotResumeTests(unittest.TestCase):
    def test_resume_requires_the_same_configured_roots(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="sublation-one-shot-resume-test-"))
        first_root = tmp / "first" / "fixture"
        second_root = tmp / "second" / "fixture"
        for root in (first_root, second_root):
            root.mkdir(parents=True)
            (root / "SKILL.md").write_text("fixture\n", encoding="utf-8")
        runs = tmp / "runs"
        intent = "把现有技能 sublation 一下吧"
        first_roots = [{"name": "first", "path": str(first_root.parent)}]
        second_roots = [{"name": "second", "path": str(second_root.parent)}]
        run_dir = sublation_run.start_run(intent, runs, first_roots, "resume-root-binding")
        self.assertEqual(sublation_one_shot.resumable_run(runs, intent, first_roots), run_dir)
        self.assertIsNone(sublation_one_shot.resumable_run(runs, intent, second_roots))


class SublationLocalAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="sublation-local-adapter-test-"))
        self.formal = self.tmp / "skills" / "fixture"
        self.formal.mkdir(parents=True)
        (self.formal / "SKILL.md").write_text("before\n", encoding="utf-8")
        self.candidate_root = self.tmp / "candidates"
        self.executables: dict[str, Path] = {}
        for style in ("codex", "claude", "hermes"):
            path = self.tmp / f"fake-{style}"
            source = FAKE_ENGINE.replace(
                "#!/usr/bin/env python3", f"#!{Path(sys.executable).resolve()}"
            ).replace("__STYLE__", repr(style))
            path.write_text(source, encoding="utf-8")
            path.chmod(0o755)
            self.executables[style] = path
        self.room_state = RoomState()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), room_handler(self.room_state))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}/api/messages"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def one_shot_args(self, run_id: str = "local-one-shot") -> argparse.Namespace:
        return argparse.Namespace(
            intent="把现有技能 sublation 一下吧",
            runs_root=str(self.tmp / "runs"),
            candidate_root=str(self.candidate_root),
            root=[f"fixture={self.formal}"],
            roots_file=None,
            run_id=run_id,
            worker_config=None,
            refresh_adapters=False,
            endpoint=self.endpoint,
            authorized_reply_sender=["user"],
            codex_bin=str(self.executables["codex"]),
            claude_bin=str(self.executables["claude"]),
            hermes_bin=str(self.executables["hermes"]),
            worker_timeout=30,
            delivery_timeout=30,
            max_steps=100,
            lease_seconds=120,
            max_releases=2,
        )

    def test_one_phrase_runs_three_distinct_local_engines_to_one_report(self) -> None:
        result = sublation_one_shot.run_one_shot(self.one_shot_args())
        self.assertEqual(result["state"], "USER_DECISION_REQUIRED")
        self.assertEqual(result["worker_steps_executed"], 6)
        self.assertEqual((self.formal / "SKILL.md").read_text(encoding="utf-8"), "before\n")
        self.assertEqual(self.room_state.posts, 1)
        run_dir = Path(result["run_dir"])
        report = sublation_run.read_json(run_dir / "report-v1.json")
        self.assertRegex(report["approval_code"], r"^SR-[A-F0-9]{8}$")
        self.assertIn(report["approval_code"], self.room_state.messages[0]["text"])
        identities = sublation_run.load_run(run_dir)["worker_identities"]
        self.assertEqual(len({entry["principal_id"] for entry in identities.values()}), 3)
        self.assertEqual(len({entry["adapter_fingerprint"] for entry in identities.values()}), 3)
        self.assertTrue(identities["codex"]["write_roots"])
        self.assertEqual(identities["claude-code"]["write_roots"], [])
        self.assertEqual(identities["hermes"]["write_roots"], [])

    def test_one_shot_reworks_into_a_new_immutable_candidate_revision(self) -> None:
        claude = self.executables["claude"]
        claude.write_text(
            claude.read_text(encoding="utf-8").replace(
                'and os.environ.get("SUBLATION_FAKE_HOLD_ONCE") == "1"',
                "and True",
            ),
            encoding="utf-8",
        )
        result = sublation_one_shot.run_one_shot(self.one_shot_args("local-rework"))
        self.assertEqual(result["state"], "USER_DECISION_REQUIRED")
        self.assertEqual(result["worker_steps_executed"], 9)
        run = sublation_run.load_run(Path(result["run_dir"]))
        candidate_paths = [
            step["candidate_path"]
            for step in run["steps"].values()
            if step.get("candidate_path")
        ]
        self.assertEqual(len(candidate_paths), 2)
        self.assertEqual(len(set(candidate_paths)), 2)
        self.assertTrue(all((Path(path) / "PATCH.diff").is_file() for path in candidate_paths))
        self.assertEqual(self.room_state.posts, 1)

    def test_quadchat_delivery_reuses_marker_after_response_loss(self) -> None:
        run_dir = self.tmp / "delivery-run"
        io_dir = run_dir / "delivery-io"
        report_path = run_dir / "report-v1.md"
        response = io_dir / "response.json"
        request = io_dir / "request.json"
        report_path.parent.mkdir(parents=True)
        report_path.write_text("# Fixture report\n", encoding="utf-8")
        report_body_hash = sublation_run.sha256(report_path.read_bytes())
        sublation_run.atomic_write_json(
            request,
            {
                "protocol": "sublation-delivery-v1",
                "idempotency_key": "fixture-key",
                "response_path": str(response),
                "report_path": str(report_path),
                "report_body_hash": report_body_hash,
            },
        )
        args = argparse.Namespace(
            endpoint=self.endpoint,
            request=str(request),
            response=str(response),
            report=str(report_path),
            actor="hermes",
        )
        sublation_local_adapter.deliver_quadchat(args)
        first = sublation_run.read_json(response)["message_ref"]
        response.unlink()
        sublation_local_adapter.deliver_quadchat(args)
        self.assertEqual(sublation_run.read_json(response)["message_ref"], first)
        self.assertEqual(self.room_state.posts, 1)

    def test_quadchat_delivery_rejects_marker_collision_with_different_text(self) -> None:
        run_dir = self.tmp / "delivery-collision-run"
        io_dir = run_dir / "delivery-io"
        report_path = run_dir / "report-v1.md"
        response = io_dir / "response.json"
        request = io_dir / "request.json"
        report_path.parent.mkdir(parents=True)
        report_path.write_text("# Correct report\n", encoding="utf-8")
        report_body_hash = sublation_run.sha256(report_path.read_bytes())
        sublation_run.atomic_write_json(
            request,
            {
                "protocol": "sublation-delivery-v1",
                "idempotency_key": "collision-key",
                "response_path": str(response),
                "report_path": str(report_path),
                "report_body_hash": report_body_hash,
            },
        )
        self.room_state.messages.append(
            {
                "id": "preexisting-collision",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "speaker": "hermes",
                "audience": "all",
                "kind": "report",
                "text": "[sublation-delivery:collision-key]\n# Different report\n",
            }
        )
        args = argparse.Namespace(
            endpoint=self.endpoint,
            request=str(request),
            response=str(response),
            report=str(report_path),
            actor="hermes",
        )
        with self.assertRaisesRegex(RuntimeError, "different report text"):
            sublation_local_adapter.deliver_quadchat(args)
        self.assertFalse(response.exists())
        self.assertEqual(self.room_state.posts, 0)

    def test_raw_room_event_is_code_bound_and_hmac_attested(self) -> None:
        result = sublation_one_shot.run_one_shot(self.one_shot_args("receipt-one-shot"))
        run_dir = Path(result["run_dir"])
        report = sublation_run.read_json(run_dir / "report-v1.json")
        delivery = report["delivery"][0]
        event = {
            "id": "user-event-1",
            "timestamp": (
                datetime.fromisoformat(delivery["ts"]) + timedelta(seconds=1)
            ).isoformat(),
            "speaker": "user",
            "audience": "all",
            "kind": "message",
            "text": f"{report['approval_code']} 准A1",
        }
        self.room_state.messages.append(event)
        args = argparse.Namespace(run_dir=str(run_dir), event_id=event["id"], endpoint=self.endpoint)
        sublation_local_adapter.attest_quadchat_receipt(args)
        evidence_path = run_dir / "receipt-io" / "user-event-1.attested.json"
        evidence, _record = sublation_run.verify_receipt_attestation(run_dir, evidence_path)
        self.assertEqual(evidence["source_event_hash"], sublation_run.sha256(event))
        receipt = sublation_receipt.apply_receipt(run_dir, receipt_evidence_path=evidence_path)
        self.assertEqual(receipt["approval"]["authorized_scope"], ["A1"])

    def test_receipt_without_latest_approval_code_is_rejected(self) -> None:
        result = sublation_one_shot.run_one_shot(self.one_shot_args("wrong-code-one-shot"))
        run_dir = Path(result["run_dir"])
        report = sublation_run.read_json(run_dir / "report-v1.json")
        event = {
            "id": "user-event-wrong-code",
            "timestamp": (
                datetime.fromisoformat(report["delivery"][0]["ts"]) + timedelta(seconds=1)
            ).isoformat(),
            "speaker": "user",
            "audience": "all",
            "kind": "message",
            "text": "SR-DEADBEEF 全部批准",
        }
        self.room_state.messages.append(event)
        args = argparse.Namespace(run_dir=str(run_dir), event_id=event["id"], endpoint=self.endpoint)
        with self.assertRaisesRegex(ValueError, "approval code"):
            sublation_local_adapter.attest_quadchat_receipt(args)

    def test_receipt_attestation_rejects_tampered_plain_report(self) -> None:
        result = sublation_one_shot.run_one_shot(self.one_shot_args("tampered-report-one-shot"))
        run_dir = Path(result["run_dir"])
        report = sublation_run.read_json(run_dir / "report-v1.json")
        delivery = report["delivery"][0]
        event = {
            "id": "user-event-tampered-report",
            "timestamp": (
                datetime.fromisoformat(delivery["ts"]) + timedelta(seconds=1)
            ).isoformat(),
            "speaker": "user",
            "audience": "all",
            "kind": "message",
            "text": f"{report['approval_code']} 准A1",
        }
        self.room_state.messages.append(event)
        (run_dir / "report-v1.md").write_text("tampered\n", encoding="utf-8")
        args = argparse.Namespace(run_dir=str(run_dir), event_id=event["id"], endpoint=self.endpoint)
        with self.assertRaisesRegex(ValueError, "plain report body differs"):
            sublation_local_adapter.attest_quadchat_receipt(args)


if __name__ == "__main__":
    unittest.main()
