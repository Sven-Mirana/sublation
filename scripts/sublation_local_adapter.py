#!/usr/bin/env python3
"""Local worker, delivery, receipt, and ephemeral-config adapters for Sublation."""

from __future__ import annotations

import argparse
import fcntl
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

import sublation_orchestrate
import sublation_run


RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["step_status", "item_status", "evidence", "blockers"],
    "properties": {
        "step_id": {"type": "string"},
        "step_status": {"enum": ["pass", "hold", "fail", "blocked"]},
        "item_status": {"type": "string"},
        "candidate_id": {"type": "string"},
        "candidate_path": {"type": "string"},
        "summary": {"type": "string"},
        "disposition": {"enum": ["promotion", "report_only", "no_op", "blocked"]},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "blockers": {"type": "array", "items": {"type": "string"}},
    },
}


def require_local_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("quadchat adapters only permit a loopback HTTP endpoint")
    if parsed.path.rstrip("/") != "/api/messages":
        raise ValueError("quadchat endpoint must end with /api/messages")
    return endpoint


def executable_works(path: str) -> bool:
    candidate = Path(path).expanduser()
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        return False
    try:
        completed = subprocess.run(
            [str(candidate), "--version"],
            text=True,
            capture_output=True,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def discover_executable(engine: str, override: str | None = None) -> str:
    env_name = f"SUBLATION_{engine.upper().replace('-', '_')}_BIN"
    candidates = [override, os.environ.get(env_name), shutil.which(engine)]
    if engine == "codex":
        candidates.append("/Applications/ChatGPT.app/Contents/Resources/codex")
    for candidate in candidates:
        if candidate and executable_works(str(candidate)):
            return str(Path(str(candidate)).expanduser().resolve())
    raise RuntimeError(f"no working local executable found for {engine}")


def prompt_for_worker(
    request_path: Path,
    request: dict[str, Any],
    *,
    actor: str,
    engine: str,
    candidate_root: Path,
) -> str:
    task = request["task"]
    item = task["item"]
    safe_skill = re.sub(r"[^A-Za-z0-9._-]+", "-", str(item.get("skill_name") or item["item_id"]))
    safe_phase = re.sub(r"[^A-Za-z0-9._-]+", "-", str(task["phase"]))
    candidate_hint = candidate_root / safe_skill / (
        f"{task['run_id']}-{str(task['item_id']).lower()}-{safe_phase}-r{int(task['attempt'])}"
    )
    previous_candidate = str(item.get("candidate_path") or "none")
    builder_phase = task["phase"] in {"candidate", "candidate_rework"}
    contract = json.dumps(RESULT_SCHEMA, ensure_ascii=False, sort_keys=True)
    return (
        f"You are the configured Sublation actor {actor!r} running through engine {engine!r}.\n"
        f"Read the immutable task request at {request_path}. The formal target has been replaced by a source snapshot.\n"
        f"Complete only phase {task['phase']!r} for item {task['item_id']!r}. Never write any configured formal root.\n"
        + (
            f"For candidate construction, use this deterministic candidate path hint: {candidate_hint}.\n"
            f"The previous immutable candidate revision is {previous_candidate}. During candidate_rework, copy its read-only snapshot to the new hint and edit only the new revision.\n"
            if builder_phase
            else f"The candidate path in the request is a read-only immutable snapshot: {previous_candidate}. Do not return candidate_path and do not modify it.\n"
        )
        + "Every positive result must name real evidence files inside the run or candidate directory. "
        "Verifier and reviewer phases must independently read the candidate evidence rather than trust prior summaries.\n"
        "Return exactly one JSON object, no prose or markdown fence, matching this schema:\n"
        f"{contract}\n"
    )


def extract_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        if {"step_status", "item_status"} <= set(value):
            return value
        for key in ("structured_output", "output", "result", "content"):
            nested = value.get(key)
            if nested is None:
                continue
            try:
                return extract_json_object(nested)
            except ValueError:
                pass
        raise ValueError("engine JSON envelope does not contain a worker result")
    if not isinstance(value, str):
        raise ValueError("engine output is neither JSON nor text")
    text = value.strip()
    try:
        return extract_json_object(json.loads(text))
    except (json.JSONDecodeError, ValueError):
        pass
    decoder = json.JSONDecoder()
    matches: list[dict[str, Any]] = []
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            parsed, _end = decoder.raw_decode(text[index:])
            if isinstance(parsed, dict) and {"step_status", "item_status"} <= set(parsed):
                matches.append(parsed)
        except json.JSONDecodeError:
            continue
    if len(matches) != 1:
        raise ValueError("engine output must contain exactly one worker result object")
    return matches[0]


def run_engine(
    engine: str,
    executable: str,
    prompt: str,
    *,
    work_dir: Path,
    access_root: Path,
    candidate_root: Path,
    writable: bool,
    request_path: Path,
    response_path: Path,
    timeout: int,
) -> dict[str, Any]:
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "SUBLATION_REQUEST_PATH": str(request_path),
        "SUBLATION_RESPONSE_PATH": str(response_path),
        "SUBLATION_CANDIDATE_ROOT": str(candidate_root if writable else access_root),
        "SUBLATION_ACCESS_ROOT": str(access_root),
    }
    if engine == "codex":
        schema_path = response_path.with_suffix(".output-schema.json")
        output_path = response_path.with_suffix(".engine-output.json")
        sublation_run.atomic_write_json(schema_path, RESULT_SCHEMA)
        argv = [
            executable,
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--skip-git-repo-check",
            "--sandbox",
            "workspace-write" if writable else "read-only",
            "-C",
            str(work_dir),
            "--add-dir",
            str(access_root),
            "--output-schema",
            str(schema_path),
            "-o",
            str(output_path),
            "--color",
            "never",
            prompt,
        ]
    elif engine == "claude":
        output_path = None
        argv = [
            executable,
            "-p",
            "--safe-mode",
            "--no-chrome",
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(RESULT_SCHEMA, ensure_ascii=False, separators=(",", ":")),
            "--permission-mode",
            "dontAsk",
            "--no-session-persistence",
            "--add-dir",
            str(access_root),
            prompt,
        ]
    elif engine == "hermes":
        output_path = None
        argv = [executable, "--safe-mode", "--oneshot", prompt]
    else:
        raise ValueError(f"unsupported local worker engine: {engine}")
    completed = subprocess.run(
        argv,
        cwd=work_dir,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or "engine exited nonzero").strip().splitlines()
        raise RuntimeError(f"{engine} worker exited {completed.returncode}: " + " | ".join(detail[:6]))
    raw = output_path.read_text(encoding="utf-8") if output_path else completed.stdout
    return extract_json_object(raw)


def run_worker(args: argparse.Namespace) -> int:
    request_path = Path(args.request).expanduser().resolve()
    response_path = Path(args.response).expanduser().resolve()
    request = sublation_run.read_json(request_path)
    if request.get("protocol") != "sublation-worker-v1":
        raise ValueError("unsupported worker request protocol")
    task = request.get("task")
    if not isinstance(task, dict) or task.get("assigned_actor") != args.actor:
        raise ValueError("worker request actor differs from configured adapter actor")
    if Path(str(request.get("response_path") or "")).expanduser().resolve() != response_path:
        raise ValueError("worker response path differs from the request contract")
    if request_path.parent.parent.name != "worker-io":
        raise ValueError("worker request is not inside a durable Sublation run")
    work_dir = request_path.parent
    candidate_root = Path(args.candidate_root).expanduser().absolute()
    builder_phase = task.get("phase") in {"candidate", "candidate_rework"}
    if builder_phase:
        candidate_root.mkdir(parents=True, exist_ok=True)
        access_root = candidate_root
    else:
        snapshot = request.get("candidate_snapshot")
        access_root = (
            Path(str(snapshot.get("path"))).expanduser().resolve()
            if isinstance(snapshot, dict) and snapshot.get("path")
            else work_dir
        )
    prompt = prompt_for_worker(
        request_path,
        request,
        actor=args.actor,
        engine=args.engine,
        candidate_root=candidate_root,
    )
    result = run_engine(
        args.engine,
        args.executable,
        prompt,
        work_dir=work_dir,
        access_root=access_root,
        candidate_root=candidate_root,
        writable=builder_phase,
        request_path=request_path,
        response_path=response_path,
        timeout=args.timeout,
    )
    validated = sublation_orchestrate.validate_result(task, result)
    sublation_run.atomic_write_json(response_path, validated)
    return 0


def http_json(endpoint: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        endpoint,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, OSError, http.client.HTTPException) as error:
        raise RuntimeError(f"quadchat request failed: {error}") from error
    if not isinstance(data, dict):
        raise ValueError("quadchat response must be a JSON object")
    return data


@contextmanager
def transport_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def deliver_quadchat(args: argparse.Namespace) -> int:
    endpoint = require_local_endpoint(args.endpoint)
    request_path = Path(args.request).expanduser().resolve()
    response_path = Path(args.response).expanduser().resolve()
    report_path = Path(args.report).expanduser().resolve()
    request = sublation_run.read_json(request_path)
    if request.get("protocol") != "sublation-delivery-v1":
        raise ValueError("unsupported delivery request protocol")
    if Path(str(request.get("response_path") or "")).expanduser().resolve() != response_path:
        raise ValueError("delivery response path differs from the request contract")
    if Path(str(request.get("report_path") or "")).expanduser().resolve() != report_path:
        raise ValueError("delivery report path differs from the request contract")
    key = str(request["idempotency_key"])
    marker = f"[sublation-delivery:{key}]"
    report_bytes = report_path.read_bytes()
    report_body_hash = sublation_run.sha256(report_bytes)
    if request.get("report_body_hash") != report_body_hash:
        raise ValueError("delivery report body hash differs from the request contract")
    text = marker + "\n" + report_bytes.decode("utf-8")
    delivery_text_hash = sublation_run.sha256(text.encode("utf-8"))
    lock_path = request_path.parent / f"{key}.transport.lock"
    with transport_lock(lock_path):
        messages = http_json(endpoint).get("messages", [])
        matches = [
            item
            for item in messages
            if isinstance(item, dict)
            and item.get("speaker") == args.actor
            and item.get("kind") == "report"
            and str(item.get("text") or "").startswith(marker)
        ]
        if len(matches) > 1:
            raise RuntimeError("quadchat contains duplicate messages for one delivery idempotency key")
        if matches:
            message = matches[0]
            if str(message.get("text") or "") != text:
                raise RuntimeError(
                    "quadchat idempotency marker already exists with different report text"
                )
        else:
            posted = http_json(
                endpoint,
                method="POST",
                payload={"speaker": args.actor, "audience": "all", "kind": "report", "text": text},
            )
            message = posted.get("message")
            if not isinstance(message, dict):
                raise ValueError("quadchat delivery response lacks a message object")
        message_ref = str(message.get("id") or "").strip()
        if not message_ref:
            raise ValueError("quadchat delivery response lacks a message id")
        sublation_run.atomic_write_json(
            response_path,
            {
                "message_ref": message_ref,
                "sender_actor": args.actor,
                "report_body_hash": report_body_hash,
                "delivery_text_hash": delivery_text_hash,
            },
        )
    return 0


def parse_channel_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("channel event timestamp must include a timezone")
    return parsed


def attest_quadchat_receipt(args: argparse.Namespace) -> int:
    endpoint = require_local_endpoint(args.endpoint)
    run_dir = Path(args.run_dir).expanduser().resolve()
    run = sublation_run.load_run(run_dir)
    latest = run.get("latest_report")
    if not isinstance(latest, dict):
        raise ValueError("run has no finalized report")
    report = sublation_run.read_json(run_dir / f"report-v{int(latest['report_version'])}.json")
    if report.get("report_hash") != sublation_run.report_hash(report):
        raise ValueError("latest report hash verification failed")
    plain_report = sublation_run.verify_plain_report(run_dir, report)
    deliveries = [
        item
        for item in report.get("delivery", [])
        if isinstance(item, dict) and item.get("channel") == "quadchat"
    ]
    if len(deliveries) != 1:
        raise ValueError("receipt attestation requires exactly one quadchat delivery")
    delivery = deliveries[0]
    if delivery.get("report_body_hash") != plain_report["sha256"]:
        raise ValueError("quadchat delivery body hash differs from the finalized plain report")
    messages = http_json(endpoint).get("messages", [])
    delivered_messages = [
        item
        for item in messages
        if isinstance(item, dict) and item.get("id") == delivery.get("message_ref")
    ]
    if len(delivered_messages) != 1:
        raise ValueError("quadchat delivered report message was not found exactly once")
    delivered_message = delivered_messages[0]
    if (
        delivered_message.get("speaker") != delivery.get("sender_actor")
        or sublation_run.sha256(str(delivered_message.get("text") or "").encode("utf-8"))
        != delivery.get("delivery_text_hash")
    ):
        raise ValueError("quadchat delivered report text differs from the durable delivery binding")
    matches = [item for item in messages if isinstance(item, dict) and item.get("id") == args.event_id]
    if len(matches) != 1:
        raise ValueError("quadchat receipt event id was not found exactly once")
    event = matches[0]
    sender = str(event.get("speaker") or "")
    if sender not in delivery.get("authorized_reply_senders", []):
        raise ValueError("quadchat receipt sender is not authorized for this report")
    message = str(event.get("text") or "").strip()
    approval_code = str(report.get("approval_code") or "")
    if not approval_code or approval_code.casefold() not in message.casefold():
        raise ValueError("quadchat receipt does not contain the latest report approval code")
    if parse_channel_timestamp(str(event.get("timestamp") or "")) <= parse_channel_timestamp(
        str(delivery.get("ts") or "")
    ):
        raise ValueError("quadchat receipt predates the report delivery")
    path = sublation_run.write_receipt_attestation(
        run_dir,
        {
            "adapter_id": f"quadchat-local-v1:{urlparse(endpoint).netloc}",
            "channel": "quadchat",
            "event_id": str(event["id"]),
            "sender_id": sender,
            "in_reply_to": str(delivery["message_ref"]),
            "message": message,
            "received_at": str(event["timestamp"]),
            "source_event_hash": sublation_run.sha256(event),
            "report_version": report["report_version"],
            "report_hash": report["report_hash"],
            "report_body_hash": report["plain_report_sha256"],
            "scope_revision": report["scope_revision"],
            "approval_code": approval_code,
        },
    )
    print(json.dumps({"receipt_evidence": str(path)}, ensure_ascii=False))
    return 0


def build_config(args: argparse.Namespace) -> dict[str, Any]:
    run_dir = Path(args.run_dir).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    if not sublation_run.path_is_inside(output, run_dir):
        raise ValueError("ephemeral worker config must be written inside the run directory")
    candidate_root = Path(args.candidate_root).expanduser().resolve()
    candidate_root.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).resolve()
    python = Path(sys.executable).resolve()
    executables = {
        "codex": discover_executable("codex", args.codex_bin),
        "claude-code": discover_executable("claude", args.claude_bin),
        "hermes": discover_executable("hermes", args.hermes_bin),
    }
    engines = {"codex": "codex", "claude-code": "claude", "hermes": "hermes"}
    run = sublation_run.load_run(run_dir)
    builder_actor = str(run["review_policy"]["roles"]["builder"])
    if builder_actor not in executables:
        raise ValueError(f"no local engine mapping for configured builder actor: {builder_actor}")
    workers: dict[str, Any] = {}
    for actor, executable in executables.items():
        workers[actor] = {
            "principal_id": f"{engines[actor]}:{Path(executable).resolve()}",
            "argv": [
                str(python),
                str(script),
                "worker",
                "--actor",
                actor,
                "--engine",
                engines[actor],
                "--executable",
                executable,
                "--candidate-root",
                str(candidate_root),
                "{request}",
                "{response}",
            ],
            "timeout_seconds": args.worker_timeout,
            "cwd": str(run_dir),
            "write_roots": [str(candidate_root)] if actor == builder_actor else [],
            "read_roots": [str(script.parent)],
            "network_access": True,
        }
    config = {
        "workers": workers,
        "delivery": {
            "actor": "hermes",
            "channel": "quadchat",
            "authorized_reply_senders": sorted(set(args.authorized_reply_sender)),
            "argv": [
                str(python),
                str(script),
                "deliver-quadchat",
                "--actor",
                "hermes",
                "--endpoint",
                require_local_endpoint(args.endpoint),
                "{request}",
                "{response}",
                "{report}",
            ],
            "timeout_seconds": args.delivery_timeout,
            "cwd": str(run_dir),
            "write_roots": [],
            "read_roots": [str(script.parent)],
            "network_access": True,
        },
    }
    sublation_run.atomic_write_json(output, config)
    return {"worker_config": str(output), "executables": executables}


def command_config(args: argparse.Namespace) -> int:
    print(json.dumps(build_config(args), ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    worker = sub.add_parser("worker", help="run one local model CLI against a worker request")
    worker.add_argument("--actor", required=True)
    worker.add_argument("--engine", choices=["codex", "claude", "hermes"], required=True)
    worker.add_argument("--executable", required=True)
    worker.add_argument("--candidate-root", required=True)
    worker.add_argument("--timeout", type=int, default=1800)
    worker.add_argument("request")
    worker.add_argument("response")
    worker.set_defaults(func=run_worker)

    deliver = sub.add_parser("deliver-quadchat", help="idempotently post one report to local quadchat")
    deliver.add_argument("--actor", default="hermes")
    deliver.add_argument("--endpoint", default="http://127.0.0.1:8787/api/messages")
    deliver.add_argument("request")
    deliver.add_argument("response")
    deliver.add_argument("report")
    deliver.set_defaults(func=deliver_quadchat)

    attest = sub.add_parser("attest-quadchat-receipt", help="attest one raw local-room user event")
    attest.add_argument("--run-dir", required=True)
    attest.add_argument("--event-id", required=True)
    attest.add_argument("--endpoint", default="http://127.0.0.1:8787/api/messages")
    attest.set_defaults(func=attest_quadchat_receipt)

    config = sub.add_parser("config", help="generate a run-local worker/delivery adapter config")
    config.add_argument("--run-dir", required=True)
    config.add_argument("--candidate-root", required=True)
    config.add_argument("--output", required=True)
    config.add_argument("--endpoint", default="http://127.0.0.1:8787/api/messages")
    config.add_argument("--authorized-reply-sender", action="append", default=["user"])
    config.add_argument("--codex-bin")
    config.add_argument("--claude-bin")
    config.add_argument("--hermes-bin")
    config.add_argument("--worker-timeout", type=int, default=1800)
    config.add_argument("--delivery-timeout", type=int, default=60)
    config.set_defaults(func=command_config)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
