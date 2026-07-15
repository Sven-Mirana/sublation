#!/usr/bin/env python3
"""Execute only receipt-authorized Sublation patches with rollback evidence."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import sublation_run
import sublation_receipt


APPROVAL_BINDING_FIELDS = (
    "item_id",
    "target",
    "target_path",
    "source_tree_hash",
    "candidate_id",
    "candidate_path",
    "candidate_tree_hash",
    "patch_path",
    "patch_hash",
    "target_baseline_hash",
    "summary",
    "disposition",
    "approval_required",
)


def parse_allowed_target(raw: str) -> tuple[str, Path]:
    item_id, separator, path = raw.partition("=")
    item_id = item_id.strip().upper()
    if not separator or not item_id or not path.strip():
        raise ValueError("allowed targets must use A_ID=PATH")
    if not item_id.startswith("A") or not item_id[1:].isdigit():
        raise ValueError(f"invalid approval item id: {item_id}")
    return item_id, Path(path).expanduser().resolve()


def path_is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def run_git_apply(root: Path, patch: Path, *, check: bool = False) -> subprocess.CompletedProcess[str]:
    command = ["git", "-C", str(root), "apply"]
    if check:
        command.append("--check")
    command.append(str(patch))
    return subprocess.run(command, text=True, capture_output=True)


def require_apply(root: Path, patch: Path, *, check: bool = False) -> None:
    result = run_git_apply(root, patch, check=check)
    if result.returncode:
        detail = (result.stderr or result.stdout or "git apply failed").strip().splitlines()
        raise ValueError("; ".join(detail[:6]))


def verify_report_item_bindings(report: dict[str, Any], run: dict[str, Any]) -> None:
    report_items = report.get("approval_items")
    if not isinstance(report_items, list):
        raise ValueError("latest report approval_items must be an array")
    for snapshot in report_items:
        if not isinstance(snapshot, dict):
            raise ValueError("latest report contains a malformed approval item")
        expected_hash = snapshot.get("approval_snapshot_hash")
        hash_payload = dict(snapshot)
        hash_payload.pop("approval_snapshot_hash", None)
        if expected_hash != sublation_run.sha256(hash_payload):
            raise ValueError(f"approval item snapshot hash failed: {snapshot.get('item_id')}")
        run_item = sublation_run.find_item(run, str(snapshot.get("item_id") or ""))
        current = {
            key: (
                sublation_run.tree_hash(Path(str(run_item["candidate_path"])).expanduser().resolve())
                if key == "candidate_tree_hash" and run_item.get("candidate_path")
                else run_item.get(key)
            )
            for key in APPROVAL_BINDING_FIELDS
        }
        expected = {key: snapshot.get(key) for key in APPROVAL_BINDING_FIELDS}
        if current != expected:
            raise ValueError(f"run item changed after the approved report: {snapshot.get('item_id')}")


def load_current_approval(
    run_dir: Path, run: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = run_dir / "approval.json"
    if not path.exists():
        raise ValueError("approval.json missing; promotion is not authorized")
    approval = sublation_run.read_json(path)
    latest = run.get("latest_report")
    if not isinstance(latest, dict):
        raise ValueError("latest report missing")
    for field in ("report_version", "report_hash", "scope_revision"):
        if approval.get(field) != latest.get(field):
            raise ValueError(f"approval is stale for latest {field}")
    report_path = run_dir / f"report-v{int(latest['report_version'])}.json"
    report = sublation_run.read_json(report_path)
    sublation_run.verify_plain_report(run_dir, report)
    if approval.get("report_body_hash") != report.get("plain_report_sha256"):
        raise ValueError("approval is stale for latest report_body_hash")
    verify_report_item_bindings(report, run)
    evidence_findings = sublation_run.evidence_integrity_findings(run_dir, run)
    if evidence_findings:
        raise ValueError("approval evidence changed after report: " + "; ".join(evidence_findings))
    events = approval.get("events")
    if not isinstance(events, list) or not events:
        raise ValueError("approval has no user receipt evidence")
    cache_events: dict[str, dict[str, Any]] = {}
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("approval event must be an object")
        event_id = str(event.get("event_id") or "")
        if not event_id or event_id in cache_events:
            raise ValueError("approval events need unique event_id")
        cache_events[event_id] = event
    item_ids = [str(item["item_id"]) for item in report.get("approval_items", [])]
    decisions = approval.get("decisions")
    if not isinstance(decisions, dict) or set(decisions) != set(item_ids):
        raise ValueError("approval decision set differs from latest report")
    durable_entries = sublation_run.verified_journal_entries(run_dir)
    journal_receipts = [
        entry.get("payload", {})
        for entry in durable_entries
        if entry.get("type") == "approval_receipt_recorded"
        and entry.get("payload", {}).get("report_version") == report["report_version"]
        and entry.get("payload", {}).get("report_hash") == report["report_hash"]
        and entry.get("payload", {}).get("report_body_hash") == report["plain_report_sha256"]
        and entry.get("payload", {}).get("scope_revision") == report["scope_revision"]
    ]
    journal_event_ids = [str(payload.get("event_id") or "") for payload in journal_receipts]
    if (
        not journal_event_ids
        or len(journal_event_ids) != len(set(journal_event_ids))
        or set(journal_event_ids) != set(cache_events)
    ):
        raise ValueError("approval cache event set differs from the durable receipt journal")
    delivery_journal = [
        entry.get("payload", {})
        for entry in durable_entries
        if entry.get("type") in {"report_delivered", "report_delivery_recovered"}
    ]
    replay = {
        item_id: {"decision": "pending", "event_id": None, "execution": "not_authorized"}
        for item_id in item_ids
    }
    ordered_events: list[dict[str, Any]] = []
    for journal in journal_receipts:
        event_id = str(journal.get("event_id") or "")
        event = cache_events[event_id]
        ordered_events.append(event)
        in_reply_to = str(event.get("in_reply_to") or "")
        if not in_reply_to:
            raise ValueError("approval events need exact in_reply_to binding")
        receipt_record = event.get("receipt_evidence")
        if not isinstance(receipt_record, dict):
            raise ValueError(f"approval event lacks attested receipt evidence: {event_id}")
        receipt_path = Path(str(receipt_record.get("path") or "")).expanduser().resolve()
        receipt_evidence, verified_record = sublation_run.verify_receipt_attestation(run_dir, receipt_path)
        if receipt_record != verified_record:
            raise ValueError(f"approval receipt evidence hash drifted: {event_id}")
        expected_receipt_fields = {
            "channel": event.get("channel"),
            "event_id": event_id,
            "sender_id": event.get("sender_id"),
            "in_reply_to": in_reply_to,
            "message": event.get("message"),
            "report_version": report["report_version"],
            "report_hash": report["report_hash"],
            "report_body_hash": report["plain_report_sha256"],
            "scope_revision": report["scope_revision"],
            "approval_code": report["approval_code"],
            "adapter_id": event.get("adapter_id"),
            "source_event_hash": event.get("source_event_hash"),
        }
        if any(receipt_evidence.get(key) != value for key, value in expected_receipt_fields.items()):
            raise ValueError(f"approval receipt evidence fields drifted: {event_id}")
        expected_signature = str(receipt_evidence.get("attestation_mac") or "")
        if event.get("event_signature") != expected_signature:
            raise ValueError(f"approval event signature failed: {event_id}")
        if not sublation_receipt.delivery_matches(
            report,
            str(event.get("channel") or ""),
            in_reply_to,
            str(event.get("sender_id") or ""),
        ):
            raise ValueError(f"approval event delivery binding failed: {event_id}")
        delivery = next(
            (
                item
                for item in report.get("delivery", [])
                if item.get("channel") == event.get("channel")
                and item.get("message_ref") == in_reply_to
            ),
            None,
        )
        expected_delivery_actor = run["review_policy"]["roles"]["coordinator"]
        if not isinstance(delivery, dict) or delivery.get("sender_actor") != expected_delivery_actor:
            raise ValueError(f"approval delivery was not sent by the report coordinator: {event_id}")
        adapter_evidence = delivery.get("adapter_evidence")
        if not isinstance(adapter_evidence, dict):
            raise ValueError(f"approval delivery lacks adapter evidence: {event_id}")
        adapter_path = Path(str(adapter_evidence.get("path") or "")).expanduser().resolve()
        if (
            not adapter_path.is_file()
            or not sublation_run.path_is_inside(adapter_path, run_dir.resolve())
            or adapter_evidence.get("sha256") != sublation_run.sha256(adapter_path.read_bytes())
        ):
            raise ValueError(f"approval delivery adapter evidence failed: {event_id}")
        adapter_payload = sublation_run.read_json(adapter_path)
        expected_adapter_payload = {
            "message_ref": delivery.get("message_ref"),
            "sender_actor": delivery.get("sender_actor"),
            "report_body_hash": delivery.get("report_body_hash"),
            "delivery_text_hash": delivery.get("delivery_text_hash"),
        }
        if any(adapter_payload.get(key) != value for key, value in expected_adapter_payload.items()):
            raise ValueError(f"approval delivery adapter fields drifted: {event_id}")
        if delivery.get("report_body_hash") != report.get("plain_report_sha256"):
            raise ValueError(f"approval delivery body hash differs from the report: {event_id}")
        expected_delivery_fields = {
            "report_version": report["report_version"],
            "report_hash": report["report_hash"],
            "channel": delivery["channel"],
            "message_ref": delivery["message_ref"],
            "sender_actor": delivery["sender_actor"],
            "idempotency_key": delivery["idempotency_key"],
            "adapter_evidence": adapter_evidence,
            "report_body_hash": delivery["report_body_hash"],
            "delivery_text_hash": delivery["delivery_text_hash"],
            "authorized_reply_senders": delivery["authorized_reply_senders"],
        }
        if not any(
            all(entry.get(key) == value for key, value in expected_delivery_fields.items())
            for entry in delivery_journal
        ):
            raise ValueError(f"approval delivery is absent from the durable journal: {event_id}")
        parsed = sublation_receipt.parse_decisions(str(event.get("message") or ""), item_ids)
        if event.get("parsed") != parsed:
            raise ValueError(f"approval event parsed decisions drifted: {event_id}")
        journal_fields = {
            "event_signature": expected_signature,
            "channel": event.get("channel"),
            "sender_id": event.get("sender_id"),
            "in_reply_to": in_reply_to,
            "report_version": report["report_version"],
            "report_hash": report["report_hash"],
            "report_body_hash": report["plain_report_sha256"],
            "scope_revision": report["scope_revision"],
            "decisions": parsed,
            "receipt_evidence": receipt_record,
            "adapter_id": event.get("adapter_id"),
            "source_event_hash": event.get("source_event_hash"),
        }
        if not isinstance(journal, dict) or any(journal.get(key) != value for key, value in journal_fields.items()):
            raise ValueError(f"approval event is absent or inconsistent in the durable journal: {event_id}")
        for item_id, decision in parsed.items():
            replay[item_id] = {
                "decision": decision,
                "event_id": event_id,
                "execution": "pending" if decision == "approve" else "not_authorized",
            }
    approval["events"] = ordered_events
    execution_replay = {
        item_id: {"execution": "pending"}
        for item_id, entry in replay.items()
        if entry["decision"] == "approve"
    }
    report_item_hashes = {
        str(item["item_id"]): item.get("approval_snapshot_hash")
        for item in report.get("approval_items", [])
    }
    for entry in durable_entries:
        event_type = str(entry.get("type") or "")
        if not event_type.startswith("promotion_"):
            continue
        payload = entry.get("payload", {})
        item_id = str(payload.get("item_id") or "")
        if item_id not in execution_replay:
            continue
        if payload.get("report_version") != report["report_version"]:
            continue
        expected_promotion_binding = {
            "report_hash": report["report_hash"],
            "report_body_hash": report["plain_report_sha256"],
            "scope_revision": report["scope_revision"],
            "approval_snapshot_hash": report_item_hashes[item_id],
        }
        if any(payload.get(key) != value for key, value in expected_promotion_binding.items()):
            raise ValueError(f"promotion journal binding differs from the current report: {item_id}")
        current = execution_replay[item_id]
        if event_type == "promotion_started":
            if current["execution"] not in {"pending", "running"}:
                raise ValueError(f"promotion journal restarts a terminal item: {item_id}")
            execution_replay[item_id] = {
                "execution": "running",
                "started_at": entry.get("timestamp"),
                "baseline_tree_hash": payload.get("baseline_tree_hash"),
                "expected_post_hash": payload.get("expected_post_hash"),
                "rollback_path": payload.get("rollback_path"),
            }
        elif event_type in {"promotion_succeeded", "promotion_recovered"}:
            if current["execution"] != "running":
                raise ValueError(f"promotion journal succeeds without a started event: {item_id}")
            execution_replay[item_id] = {
                **current,
                "execution": "succeeded",
                "completed_at": entry.get("timestamp"),
                "post_tree_hash": payload.get("post_tree_hash"),
                "rollback_path": payload.get("rollback_path") or current.get("rollback_path"),
            }
        elif event_type in {"promotion_failed", "promotion_blocked"}:
            if current["execution"] not in {"running", "failed"}:
                raise ValueError(f"promotion journal fails without a started event: {item_id}")
            execution_replay[item_id] = {
                **current,
                "execution": "failed",
                "error": payload.get("error") or payload.get("boundary") or "promotion failed",
            }

    for item_id, expected in replay.items():
        actual = decisions[item_id]
        if not isinstance(actual, dict):
            raise ValueError(f"approval decision is malformed: {item_id}")
        if actual.get("decision") != expected["decision"] or actual.get("event_id") != expected["event_id"]:
            raise ValueError(f"approval decision cannot be reconstructed from receipts: {item_id}")
        if expected["decision"] == "approve":
            decisions[item_id] = {
                "decision": expected["decision"],
                "event_id": expected["event_id"],
                "updated_at": actual.get("updated_at"),
                **execution_replay[item_id],
            }
        elif actual.get("execution") != "not_authorized":
            raise ValueError(f"unapproved item gained execution authority: {item_id}")
    authorized_scope = sorted(item_id for item_id, entry in replay.items() if entry["decision"] == "approve")
    if approval.get("authorized_scope") != authorized_scope:
        raise ValueError("approval authorized_scope cannot be reconstructed from receipts")
    if (
        not isinstance(run.get("approval"), dict)
        or run["approval"].get("authorized_scope") != authorized_scope
        or run["approval"].get("report_body_hash") != report.get("plain_report_sha256")
    ):
        raise ValueError("run approval summary differs from receipt-derived authority")
    return approval, report


def item_by_id(run: dict[str, Any], item_id: str) -> dict[str, Any]:
    return sublation_run.find_item(run, item_id)


def validate_item(
    item: dict[str, Any],
    report_item: dict[str, Any],
    decision: dict[str, Any],
    allowed_targets: dict[str, Path],
) -> tuple[Path, Path, Path]:
    item_id = str(item["item_id"])
    if decision.get("decision") != "approve":
        raise ValueError(f"{item_id} is not approved")
    if item_id not in allowed_targets:
        raise ValueError(f"{item_id} has no explicit allowed-target binding")
    if any(item.get(field) != report_item.get(field) for field in APPROVAL_BINDING_FIELDS if field != "candidate_tree_hash"):
        raise ValueError(f"{item_id} run item differs from the approved report snapshot")
    target = Path(str(report_item.get("target_path") or "")).expanduser().resolve()
    if target != allowed_targets[item_id]:
        raise ValueError(f"{item_id} allowed-target binding differs from run target")
    candidate = Path(str(report_item.get("candidate_path") or "")).expanduser().resolve()
    patch = Path(str(report_item.get("patch_path") or "")).expanduser().resolve()
    if not target.is_dir() or not candidate.is_dir() or not patch.is_file():
        raise ValueError(f"{item_id} target/candidate/patch path is unavailable")
    if patch.parent != candidate or patch.name != "PATCH.diff":
        raise ValueError(f"{item_id} patch must be candidate/PATCH.diff")
    if path_is_inside(candidate, target) or path_is_inside(target, candidate):
        raise ValueError(f"{item_id} candidate and target must be isolated")
    if report_item.get("candidate_tree_hash") != sublation_run.tree_hash(candidate):
        raise ValueError(f"{item_id} candidate tree changed after report")
    if report_item.get("patch_hash") != sublation_run.sha256(patch.read_bytes()):
        raise ValueError(f"{item_id} patch hash changed after report")
    if not report_item.get("target_baseline_hash"):
        raise ValueError(f"{item_id} target baseline hash was not recorded")
    return target, candidate, patch


def expected_post_hash(rollback_copy: Path, patch: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="sublation-promote-expected-") as tmp:
        expected = Path(tmp) / "formal-expected"
        shutil.copytree(rollback_copy, expected, symlinks=True)
        require_apply(expected, patch, check=True)
        require_apply(expected, patch)
        return sublation_run.tree_hash(expected)


def restore_target_from_rollback(target: Path, rollback: Path) -> str:
    baseline_hash = sublation_run.tree_hash(rollback)
    suffix = secrets.token_hex(8)
    staged = target.parent / f".{target.name}.sublation-restore-{suffix}"
    quarantine = target.parent / f".{target.name}.sublation-quarantine-{suffix}"
    if staged.exists() or quarantine.exists():
        raise ValueError("rollback staging path collision")
    shutil.copytree(rollback, staged, symlinks=True)
    try:
        if sublation_run.tree_hash(staged) != baseline_hash:
            raise ValueError("staged rollback tree differs from rollback evidence")
        target.rename(quarantine)
        try:
            staged.rename(target)
        except Exception:
            quarantine.rename(target)
            raise
        shutil.rmtree(quarantine)
    finally:
        if staged.exists():
            shutil.rmtree(staged)
    restored_hash = sublation_run.tree_hash(target)
    if restored_hash != baseline_hash:
        raise ValueError("formal target rollback verification failed")
    return restored_hash


def persist_execution(
    run_dir: Path,
    run: dict[str, Any],
    approval: dict[str, Any],
    report_item: dict[str, Any],
    *,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    payload = {
        **payload,
        "report_version": approval["report_version"],
        "report_hash": approval["report_hash"],
        "report_body_hash": approval["report_body_hash"],
        "scope_revision": approval["scope_revision"],
        "approval_snapshot_hash": report_item["approval_snapshot_hash"],
    }
    approval["updated_at"] = sublation_run.utc_now()
    run["approval"] = {
        "path": str(run_dir / "approval.json"),
        "report_version": approval["report_version"],
        "report_hash": approval["report_hash"],
        "report_body_hash": approval["report_body_hash"],
        "scope_revision": approval["scope_revision"],
        "state": run["state"],
        "authorized_scope": approval.get("authorized_scope", []),
    }
    run["revision"] = int(run.get("revision", 0)) + 1
    run["updated_at"] = sublation_run.utc_now()
    sublation_run.commit_run(run_dir, run, event_type, payload)
    sublation_run.atomic_write_json(run_dir / "approval.json", approval)


def derive_post_execution_state(approval: dict[str, Any]) -> str:
    decisions = list(approval.get("decisions", {}).values())
    approved = [entry for entry in decisions if entry.get("decision") == "approve"]
    if any(entry.get("execution") in {"pending", "running"} for entry in approved):
        return "APPROVED_PENDING_EXECUTION"
    if any(entry.get("execution") == "failed" for entry in approved):
        return "PARTIAL"
    if approved and all(entry.get("execution") == "succeeded" for entry in approved):
        if all(entry.get("decision") == "approve" for entry in decisions):
            return "OBSERVING"
        return "USER_DECISION_REQUIRED"
    return "USER_DECISION_REQUIRED"


def execute_one(
    run_dir: Path,
    run: dict[str, Any],
    approval: dict[str, Any],
    item_id: str,
    report_item: dict[str, Any],
    allowed_targets: dict[str, Path],
    rollback_root: Path,
) -> dict[str, Any]:
    item = item_by_id(run, item_id)
    decision = approval["decisions"].get(item_id)
    if not isinstance(decision, dict):
        raise ValueError(f"approval decision missing for {item_id}")
    target, _candidate, patch = validate_item(item, report_item, decision, allowed_targets)
    if decision.get("execution") == "succeeded":
        current_hash = sublation_run.tree_hash(target)
        recorded_post_hash = str(decision.get("post_tree_hash") or "")
        if not recorded_post_hash or current_hash != recorded_post_hash:
            raise ValueError(f"{item_id} formal target drifted after recorded promotion success")
        rollback_path = Path(str(decision.get("rollback_path") or "")).expanduser().resolve()
        if not rollback_path.is_dir() or sublation_run.tree_hash(rollback_path) != str(
            report_item["target_baseline_hash"]
        ):
            raise ValueError(f"{item_id} rollback evidence is missing or drifted after promotion")
        expected_state = derive_post_execution_state(approval)
        if run.get("state") != expected_state:
            run["state"] = expected_state
            persist_execution(
                run_dir,
                run,
                approval,
                report_item,
                event_type="promotion_state_recovered",
                payload={"item_id": item_id, "post_tree_hash": decision.get("post_tree_hash")},
            )
        return {"item_id": item_id, "idempotent": True, "status": "succeeded"}

    rollback_dir = (rollback_root.expanduser().resolve() / run["run_id"] / item_id / "formal-before").resolve()
    expected_parent = rollback_root.expanduser().resolve() / run["run_id"] / item_id
    if rollback_dir.parent != expected_parent.resolve():
        raise ValueError("rollback path escaped its item directory")
    if path_is_inside(rollback_dir, target) or path_is_inside(target, rollback_dir):
        raise ValueError("rollback path and formal target must be isolated")

    baseline_hash = str(report_item["target_baseline_hash"])
    current_hash = sublation_run.tree_hash(target)
    execution = decision.get("execution")
    expected_hash = decision.get("expected_post_hash")
    if execution == "running" and expected_hash:
        if current_hash == expected_hash:
            decision["execution"] = "succeeded"
            decision["completed_at"] = sublation_run.utc_now()
            decision["post_tree_hash"] = current_hash
            run["state"] = derive_post_execution_state(approval)
            persist_execution(
                run_dir,
                run,
                approval,
                report_item,
                event_type="promotion_recovered",
                payload={"item_id": item_id, "post_tree_hash": current_hash, "rollback_path": str(rollback_dir)},
            )
            return {"item_id": item_id, "idempotent": True, "status": "succeeded", "recovered": True}
        if current_hash != baseline_hash:
            rollback_hash = sublation_run.tree_hash(rollback_dir) if rollback_dir.is_dir() else None
            if rollback_hash != baseline_hash:
                raise ValueError(f"{item_id} cannot recover: rollback evidence is missing or drifted")
            restored_hash = restore_target_from_rollback(target, rollback_dir)
            decision["execution"] = "failed"
            decision["error"] = "target differs from both recorded baseline and expected post-promotion hash"
            run["state"] = "PARTIAL"
            persist_execution(
                run_dir,
                run,
                approval,
                report_item,
                event_type="promotion_blocked",
                payload={
                    "item_id": item_id,
                    "current_tree_hash": current_hash,
                    "rolled_back": True,
                    "restored_tree_hash": restored_hash,
                    "boundary": "Unexpected partial state was restored from rollback evidence.",
                },
            )
            raise ValueError(decision["error"])

    if current_hash != baseline_hash:
        raise ValueError(f"{item_id} target baseline drifted before promotion")
    if rollback_dir.exists():
        if sublation_run.tree_hash(rollback_dir) != baseline_hash:
            raise ValueError(f"{item_id} existing rollback does not match recorded baseline")
    else:
        rollback_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(target, rollback_dir, symlinks=True)
    expected_hash = expected_post_hash(rollback_dir, patch)

    decision.update(
        {
            "execution": "running",
            "started_at": sublation_run.utc_now(),
            "baseline_tree_hash": baseline_hash,
            "expected_post_hash": expected_hash,
            "rollback_path": str(rollback_dir),
        }
    )
    run["state"] = "APPROVED_PENDING_EXECUTION"
    persist_execution(
        run_dir,
        run,
        approval,
        report_item,
        event_type="promotion_started",
        payload={
            "item_id": item_id,
            "target": str(target),
            "patch_hash": report_item["patch_hash"],
            "baseline_tree_hash": baseline_hash,
            "expected_post_hash": expected_hash,
            "rollback_path": str(rollback_dir),
            "authorization_event_ids": [event["event_id"] for event in approval.get("events", [])],
        },
    )

    try:
        require_apply(target, patch, check=True)
        require_apply(target, patch)
        post_hash = sublation_run.tree_hash(target)
        if post_hash != expected_hash:
            raise ValueError("post-promotion tree hash differs from sandbox-reproduced expected hash")
        if os.environ.get("SUBLATION_TEST_CRASH_AFTER_APPLY") == "1":
            os._exit(92)
    except Exception as exc:
        rolled_back = False
        restored_hash: str | None = None
        restore_error: str | None = None
        if sublation_run.tree_hash(target) != baseline_hash:
            try:
                restored_hash = restore_target_from_rollback(target, rollback_dir)
                rolled_back = True
            except Exception as rollback_exc:
                restore_error = str(rollback_exc)
        decision["execution"] = "failed"
        decision["error"] = str(exc) + (f"; rollback failed: {restore_error}" if restore_error else "")
        run["state"] = "PARTIAL"
        persist_execution(
            run_dir,
            run,
            approval,
            report_item,
            event_type="promotion_failed",
            payload={
                "item_id": item_id,
                "error": decision["error"],
                "rollback_path": str(rollback_dir),
                "rolled_back": rolled_back,
                "restored_tree_hash": restored_hash,
            },
        )
        raise

    decision["execution"] = "succeeded"
    decision["completed_at"] = sublation_run.utc_now()
    decision["post_tree_hash"] = post_hash
    run["state"] = derive_post_execution_state(approval)
    persist_execution(
        run_dir,
        run,
        approval,
        report_item,
        event_type="promotion_succeeded",
        payload={
            "item_id": item_id,
            "target": str(target),
            "post_tree_hash": post_hash,
            "rollback_path": str(rollback_dir),
        },
    )
    return {
        "item_id": item_id,
        "idempotent": False,
        "status": "succeeded",
        "post_tree_hash": post_hash,
        "rollback_path": str(rollback_dir),
    }


def execute_approved(
    run_dir: Path,
    *,
    allowed_targets: dict[str, Path],
    rollback_root: Path,
    item_ids: list[str] | None = None,
) -> dict[str, Any]:
    with sublation_run.locked_run(run_dir):
        run = sublation_run.load_run(run_dir)
        approval, report = load_current_approval(run_dir, run)
        authorized = list(approval.get("authorized_scope", []))
        selected = [item.upper() for item in item_ids] if item_ids else authorized
        unauthorized = sorted(set(selected) - set(authorized))
        if unauthorized:
            raise ValueError("requested promotion includes unauthorized items: " + ", ".join(unauthorized))
        if not selected:
            raise ValueError("approval contains no authorized promotion items")
        report_items = {str(item["item_id"]): item for item in report.get("approval_items", [])}
        results = [
            execute_one(
                run_dir,
                run,
                approval,
                item_id,
                report_items[item_id],
                allowed_targets,
                rollback_root,
            )
            for item_id in selected
        ]
        return {"run_id": run["run_id"], "state": run["state"], "results": results}


def command_execute(args: argparse.Namespace) -> int:
    allowed = dict(parse_allowed_target(raw) for raw in args.allowed_target)
    result = execute_approved(
        Path(args.run_dir),
        allowed_targets=allowed,
        rollback_root=Path(args.rollback_root),
        item_ids=args.item,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    execute = sub.add_parser("execute", help="apply only receipt-authorized patches")
    execute.add_argument("--run-dir", required=True)
    execute.add_argument("--rollback-root", required=True)
    execute.add_argument("--allowed-target", action="append", default=[], required=True, help="exact A_ID=PATH binding")
    execute.add_argument("--item", action="append", help="approved item id; defaults to all authorized items")
    execute.set_defaults(func=command_execute)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
