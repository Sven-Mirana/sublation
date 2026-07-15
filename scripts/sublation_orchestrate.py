#!/usr/bin/env python3
"""Run configured Sublation workers against the durable candidate-only queue."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import sublation_run


RESULT_FIELDS = {
    "step_id",
    "step_status",
    "item_status",
    "candidate_id",
    "candidate_path",
    "summary",
    "disposition",
    "evidence",
    "blockers",
}
DELIVERY_RESULT_FIELDS = {
    "message_ref",
    "sender_actor",
    "report_body_hash",
    "delivery_text_hash",
}
SAFE_ENV_KEYS = {"LANG", "LOGNAME", "PATH", "SHELL", "TZ", "USER"}
SYSTEM_READ_ROOTS = (
    "/System",
    "/usr/bin",
    "/usr/lib",
    "/bin",
    "/Library/Frameworks",
    "/private/etc",
    "/private/var/db/dyld",
    "/dev",
)


def normalize_adapter(
    raw: dict[str, Any], label: str, default_cwd: Path, *, require_principal: bool = False
) -> dict[str, Any]:
    argv = raw.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(arg, str) and arg for arg in argv):
        raise ValueError(f"{label} needs a non-empty argv string array")
    timeout = int(raw.get("timeout_seconds", 900))
    if timeout < 1 or timeout > 86400:
        raise ValueError(f"{label} timeout_seconds must be between 1 and 86400")
    cwd = Path(str(raw.get("cwd") or default_cwd)).expanduser().resolve()
    if not cwd.is_dir():
        raise ValueError(f"{label} cwd does not exist: {cwd}")
    raw_write_roots = raw.get("write_roots", [])
    if not isinstance(raw_write_roots, list) or not all(
        isinstance(path, str) and path.strip() for path in raw_write_roots
    ):
        raise ValueError(f"{label} write_roots must be a string array")
    write_roots = sorted(
        {str(Path(path).expanduser().resolve()) for path in raw_write_roots}
    )
    raw_read_roots = raw.get("read_roots", [])
    if not isinstance(raw_read_roots, list) or not all(
        isinstance(path, str) and path.strip() for path in raw_read_roots
    ):
        raise ValueError(f"{label} read_roots must be a string array")
    read_roots = sorted({str(Path(path).expanduser().resolve()) for path in raw_read_roots})
    network_access = raw.get("network_access", False)
    if not isinstance(network_access, bool):
        raise ValueError(f"{label} network_access must be a boolean")
    normalized = {
        "argv": argv,
        "timeout_seconds": timeout,
        "cwd": str(cwd),
        "write_roots": write_roots,
        "read_roots": read_roots,
        "network_access": network_access,
    }
    if require_principal:
        principal = str(raw.get("principal_id") or "").strip()
        if not principal:
            raise ValueError(f"{label} needs principal_id")
        normalized["principal_id"] = principal
        normalized["adapter_fingerprint"] = sublation_run.sha256(
            {
                "argv": argv,
                "cwd": str(cwd),
                "write_roots": write_roots,
                "read_roots": read_roots,
                "network_access": network_access,
            }
        )
    return normalized


def load_orchestrator_config(path: Path) -> dict[str, Any]:
    data = sublation_run.read_json(path.expanduser().resolve())
    workers = data.get("workers")
    if not isinstance(workers, dict) or not workers:
        raise ValueError("worker config needs a non-empty workers object")
    normalized: dict[str, dict[str, Any]] = {}
    for actor, raw in workers.items():
        if not isinstance(raw, dict):
            raise ValueError(f"worker {actor!r} must be an object")
        normalized[str(actor)] = normalize_adapter(
            raw, f"worker {actor!r}", path.parent, require_principal=True
        )
    raw_delivery = data.get("delivery")
    if not isinstance(raw_delivery, dict):
        raise ValueError("worker config needs a delivery object")
    delivery = normalize_adapter(raw_delivery, "delivery adapter", path.parent)
    actor = str(raw_delivery.get("actor") or "").strip()
    channel = str(raw_delivery.get("channel") or "").strip()
    senders = sorted(
        {
            str(sender).strip()
            for sender in raw_delivery.get("authorized_reply_senders", [])
            if str(sender).strip()
        }
    )
    if not actor or not channel or not senders:
        raise ValueError("delivery adapter needs actor, channel, and authorized_reply_senders")
    delivery.update({"actor": actor, "channel": channel, "authorized_reply_senders": senders})
    return {"workers": normalized, "delivery": delivery}


def load_worker_config(path: Path) -> dict[str, dict[str, Any]]:
    return load_orchestrator_config(path)["workers"]


def render_argv(argv: list[str], **values: Path) -> list[str]:
    string_values = {key: str(value) for key, value in values.items()}
    rendered: list[str] = []
    for arg in argv:
        try:
            rendered.append(arg.format_map(string_values))
        except KeyError as error:
            raise ValueError(f"unknown worker argv placeholder: {error.args[0]}") from error
    return rendered


def inferred_runtime_read_roots(argv: list[str]) -> set[Path]:
    roots: set[Path] = set()
    for index, token in enumerate(argv):
        candidate = Path(token).expanduser()
        is_runtime_token = (
            index == 0
            or candidate.suffix in {".py", ".sh"}
            or (index > 0 and argv[index - 1] == "--executable")
        )
        if not is_runtime_token or not candidate.is_absolute() or not candidate.exists():
            continue
        roots.add(candidate.absolute())
        if index == 0:
            roots.add(candidate.absolute().parent)
        resolved = candidate.resolve()
        app_root = next(
            (parent for parent in (resolved, *resolved.parents) if parent.suffix == ".app"),
            None,
        )
        if app_root:
            roots.add(app_root)
            continue
        if resolved.parent.name == "bin" and (resolved.parent.parent / "pyvenv.cfg").is_file():
            roots.add(resolved.parent.parent)
        elif resolved.is_file():
            roots.add(resolved)
        else:
            roots.add(resolved)
    return roots


def runtime_traversal_paths(argv: list[str]) -> set[Path]:
    paths: set[Path] = {Path("/")}
    for index, token in enumerate(argv):
        candidate = Path(token).expanduser()
        if not candidate.is_absolute() or not candidate.exists():
            continue
        if not (
            index == 0
            or candidate.suffix in {".py", ".sh"}
            or (index > 0 and argv[index - 1] == "--executable")
        ):
            continue
        paths.update(candidate.absolute().parents)
        paths.update(candidate.resolve().parents)
    return paths


def sanitized_environment(task_io: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    home = task_io / "home"
    tmp = task_io / "tmp"
    home.mkdir(parents=True, exist_ok=True)
    tmp.mkdir(parents=True, exist_ok=True)
    env = {
        key: value
        for key, value in os.environ.items()
        if key in SAFE_ENV_KEYS or key.startswith("LC_")
    }
    env.update(
        {
            "HOME": str(home),
            "TMPDIR": str(tmp),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    if extra:
        env.update({str(key): str(value) for key, value in extra.items()})
    return env


def sandbox_profile(
    run_dir: Path,
    run: dict[str, Any],
    write_roots: list[str] | None = None,
    read_only_paths: list[Path] | None = None,
    read_roots: list[str] | None = None,
    argv: list[str] | None = None,
    network_access: bool = False,
) -> str:
    formal_paths = {
        str(Path(str(root["path"])).expanduser().resolve())
        for root in run.get("configured_roots", [])
        if root.get("path")
    }
    formal_paths.update(
        str(Path(str(item["target_path"])).expanduser().resolve())
        for item in run.get("items", [])
        if item.get("target_path")
    )
    if not formal_paths:
        raise ValueError("run has no formal paths to isolate")
    allowed_write_paths = {
        str(Path(path).expanduser().resolve()) for path in (write_roots or [])
    }
    for allowed in allowed_write_paths:
        if allowed in {"/", str(Path.home().resolve())}:
            raise ValueError("worker write_roots must not grant a filesystem or home-directory root")
        allowed_path = Path(allowed)
        if any(
            sublation_run.path_is_inside(allowed_path, Path(formal))
            or sublation_run.path_is_inside(Path(formal), allowed_path)
            for formal in formal_paths
        ):
            raise ValueError("worker write_roots must be isolated from every configured formal root")
    explicit_read_paths = {
        Path(path).expanduser().resolve() for path in (read_roots or [])
    }
    for allowed in explicit_read_paths:
        if str(allowed) in {"/", str(Path.home().resolve())}:
            raise ValueError("worker read_roots must not grant a filesystem or home-directory root")
        if any(
            sublation_run.path_is_inside(allowed, Path(formal))
            or sublation_run.path_is_inside(Path(formal), allowed)
            for formal in formal_paths
        ):
            raise ValueError("worker read_roots must not expose a configured formal root")
    allowed_read_paths = {
        *(Path(path).resolve() for path in SYSTEM_READ_ROOTS if Path(path).exists()),
        *(Path(path) for path in allowed_write_paths),
        *explicit_read_paths,
        *inferred_runtime_read_roots(argv or []),
        *(item.expanduser().resolve() for item in (read_only_paths or [])),
    }
    lines = ["(version 1)", "(allow default)", "(deny file-read*)", "(deny file-write*)"]
    if not network_access:
        lines.append("(deny network*)")
    # Runtime path resolution opens each ancestor directory. Literal grants
    # expose directory entries only, never descendant file contents.
    for path in sorted(runtime_traversal_paths(argv or []), key=str):
        escaped = str(path).replace("\\", "\\\\").replace('"', '\\"')
        lines.append(
            f'(allow file-read-metadata file-read-data (literal "{escaped}"))'
        )
    for path in sorted(allowed_read_paths, key=str):
        escaped = str(path).replace("\\", "\\\\").replace('"', '\\"')
        if path.is_dir():
            lines.append(f'(allow file-read* (literal "{escaped}"))')
            lines.append(f'(allow file-read* (subpath "{escaped}"))')
        else:
            lines.append(f'(allow file-read* (literal "{escaped}"))')
    for path in sorted({*allowed_write_paths, "/dev"}):
        escaped = path.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'(allow file-write* (subpath "{escaped}"))')
    for path in sorted(formal_paths):
        escaped = path.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'(deny file-write* (subpath "{escaped}"))')
    for path in sorted({item.expanduser().resolve() for item in (read_only_paths or [])}, key=str):
        escaped = str(path).replace("\\", "\\\\").replace('"', '\\"')
        filter_name = "subpath" if path.is_dir() else "literal"
        lines.append(f'(deny file-write* ({filter_name} "{escaped}"))')
    control = str(sublation_run.control_dir(run_dir))
    escaped_control = control.replace("\\", "\\\\").replace('"', '\\"')
    lines.append(f'(deny file-read* file-write* (subpath "{escaped_control}"))')
    return "\n".join(lines)


def isolated_argv(
    run_dir: Path,
    run: dict[str, Any],
    argv: list[str],
    write_roots: list[str] | None = None,
    read_only_paths: list[Path] | None = None,
    read_roots: list[str] | None = None,
    network_access: bool = False,
) -> list[str]:
    executable = shutil.which("sandbox-exec") if sys.platform == "darwin" else None
    if not executable:
        raise RuntimeError("macOS sandbox-exec is required; refusing unsandboxed worker execution")
    return [
        executable,
        "-p",
        sandbox_profile(
            run_dir,
            run,
            write_roots,
            read_only_paths,
            read_roots,
            argv,
            network_access,
        ),
        *argv,
    ]


def validate_external_write_roots(
    run_dir: Path,
    run: dict[str, Any],
    write_roots: list[str],
    label: str,
) -> None:
    resolved = [Path(path).expanduser().resolve() for path in write_roots]
    if any(
        sublation_run.path_is_inside(path, run_dir)
        or sublation_run.path_is_inside(run_dir, path)
        for path in resolved
    ):
        raise ValueError(f"{label} write_roots must be isolated from the durable run directory")
    sandbox_profile(run_dir, run, [str(path) for path in resolved])


@contextmanager
def orchestrator_lock(run_dir: Path) -> Iterator[None]:
    path = run_dir.expanduser().resolve() / ".orchestrator.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("another orchestrator process is already active for this run") from error
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def validate_result(task: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(result) - RESULT_FIELDS)
    if unknown:
        raise ValueError("worker result has unknown fields: " + ", ".join(unknown))
    if not str(result.get("step_status") or "").strip():
        raise ValueError("worker result requires step_status")
    if result.get("item_status") not in sublation_run.ITEM_STATES:
        raise ValueError("worker result requires a valid item_status")
    if result.get("candidate_path") and task.get("phase") not in {"candidate", "candidate_rework"}:
        raise ValueError("only candidate or candidate_rework workers may return candidate_path")
    for field in ("evidence", "blockers"):
        value = result.get(field, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"worker result {field} must be a string array")
    result.setdefault("step_id", task["task_id"].replace(":", "-") + "-complete")
    result.setdefault("evidence", [])
    result.setdefault("blockers", [])
    return result


def execute_task(
    run_dir: Path,
    task: dict[str, Any],
    worker: dict[str, Any],
    *,
    max_releases: int = 3,
) -> dict[str, Any]:
    io_dir = run_dir / "worker-io"
    io_dir.mkdir(parents=True, exist_ok=True)
    safe_id = str(task["task_id"]).replace(":", "-")
    lease_suffix = str(task["lease"]["token"])[:12]
    task_io = io_dir / f"{safe_id}.{lease_suffix}"
    task_io.mkdir(parents=True, exist_ok=True)
    request_path = task_io / "request.json"
    response_path = task_io / "response.json"
    target = Path(str(task["item"]["target_path"])).expanduser().resolve()
    before_hash = sublation_run.tree_hash(target)
    expected_source_hash = task["item"].get("source_tree_hash")
    if expected_source_hash and before_hash != expected_source_hash:
        sublation_run.release_task(
            run_dir,
            task["task_id"],
            task["assigned_actor"],
            task["lease"]["token"],
            "formal_target_drifted_before_worker",
            retryable=False,
            max_releases=max_releases,
        )
        raise RuntimeError(f"formal target drifted before {task['task_id']}; run blocked")
    snapshot_path = task_io / "source"
    if target.is_dir():
        if snapshot_path.exists():
            if sublation_run.tree_hash(snapshot_path) != before_hash:
                raise RuntimeError(f"existing worker snapshot drifted for {task['task_id']}")
        else:
            shutil.copytree(target, snapshot_path, symlinks=True)
    else:
        snapshot_path.mkdir(parents=True, exist_ok=True)
    snapshot_hash = sublation_run.tree_hash(snapshot_path)
    if snapshot_hash != before_hash or sublation_run.tree_hash(target) != before_hash:
        sublation_run.release_task(
            run_dir,
            task["task_id"],
            task["assigned_actor"],
            task["lease"]["token"],
            "formal_snapshot_is_not_immutable",
            retryable=False,
            max_releases=max_releases,
        )
        raise RuntimeError(f"formal snapshot changed during {task['task_id']}; run blocked")
    worker_task = json.loads(json.dumps(task, ensure_ascii=False))
    worker_task["item"]["target_path"] = str(snapshot_path)
    worker_task["item"]["formal_target_redacted"] = True
    candidate_snapshot: dict[str, str] | None = None
    candidate_live_path: Path | None = None
    candidate_live_hash: str | None = None
    raw_candidate_path = task["item"].get("candidate_path")
    if raw_candidate_path:
        candidate_live_path = Path(str(raw_candidate_path)).expanduser().resolve()
        if not candidate_live_path.is_dir():
            raise RuntimeError(f"candidate revision is unavailable for {task['task_id']}")
        candidate_live_hash = sublation_run.tree_hash(candidate_live_path)
        candidate_snapshot_path = task_io / "candidate"
        if candidate_snapshot_path.exists():
            if sublation_run.tree_hash(candidate_snapshot_path) != candidate_live_hash:
                raise RuntimeError(f"existing candidate snapshot drifted for {task['task_id']}")
        else:
            shutil.copytree(candidate_live_path, candidate_snapshot_path, symlinks=True)
        candidate_snapshot_hash = sublation_run.tree_hash(candidate_snapshot_path)
        if (
            candidate_snapshot_hash != candidate_live_hash
            or sublation_run.tree_hash(candidate_live_path) != candidate_live_hash
        ):
            sublation_run.release_task(
                run_dir,
                task["task_id"],
                task["assigned_actor"],
                task["lease"]["token"],
                "candidate_snapshot_is_not_immutable",
                retryable=False,
                max_releases=max_releases,
            )
            raise RuntimeError(f"candidate snapshot changed during {task['task_id']}; run blocked")
        worker_task["item"]["candidate_path"] = str(candidate_snapshot_path)
        worker_task["item"]["candidate_path_redacted"] = True
        redacted_evidence: list[Any] = []
        for record in worker_task["item"].get("evidence") or []:
            if not isinstance(record, dict) or not record.get("path"):
                redacted_evidence.append(record)
                continue
            evidence_path = Path(str(record["path"])).expanduser().resolve()
            if sublation_run.path_is_inside(evidence_path, candidate_live_path):
                relative = evidence_path.relative_to(candidate_live_path)
                replacement = candidate_snapshot_path / relative
                redacted_evidence.append({**record, "path": str(replacement)})
            else:
                redacted_evidence.append(record)
        worker_task["item"]["evidence"] = redacted_evidence
        candidate_snapshot = {
            "path": str(candidate_snapshot_path),
            "tree_hash": candidate_live_hash,
            "snapshot_tree_hash": candidate_snapshot_hash,
        }
    request = {
        "protocol": "sublation-worker-v1",
        "task": worker_task,
        "source_snapshot": {
            "path": str(snapshot_path),
            "tree_hash": before_hash,
            "snapshot_tree_hash": snapshot_hash,
        },
        "candidate_snapshot": candidate_snapshot,
        "response_path": str(response_path),
        "result_contract": sorted(RESULT_FIELDS),
    }
    sublation_run.atomic_write_json(request_path, request)
    request_hash = sublation_run.sha256(request_path.read_bytes())
    argv = render_argv(worker["argv"], request=request_path, response=response_path)
    configured_write_roots = [Path(path).expanduser().resolve() for path in worker.get("write_roots", [])]
    validate_external_write_roots(
        run_dir,
        sublation_run.load_run(run_dir),
        [str(path) for path in configured_write_roots],
        "configured worker",
    )
    env = sanitized_environment(
        task_io,
        {
            "SUBLATION_CANDIDATE_ONLY": "1",
            "SUBLATION_RUN_ID": str(task["run_id"]),
            "SUBLATION_TASK_ID": str(task["task_id"]),
        },
    )
    completed: subprocess.CompletedProcess[str] | None = None
    if not response_path.is_file():
        if os.environ.get("SUBLATION_TEST_CRASH_BEFORE_WORKER_RESPONSE") == "1":
            os._exit(93)
        try:
            completed = subprocess.run(
                isolated_argv(
                    run_dir,
                    sublation_run.load_run(run_dir),
                    argv,
                    [str(task_io), *(str(path) for path in configured_write_roots)],
                    [
                        request_path,
                        snapshot_path,
                        *([Path(candidate_snapshot["path"])] if candidate_snapshot else []),
                    ],
                    list(worker.get("read_roots") or []),
                    bool(worker.get("network_access")),
                ),
                cwd=task_io,
                env=env,
                text=True,
                capture_output=True,
                timeout=worker["timeout_seconds"],
            )
        except subprocess.TimeoutExpired as error:
            return sublation_run.release_task(
                run_dir,
                task["task_id"],
                task["assigned_actor"],
                task["lease"]["token"],
                f"worker_timeout:{error.timeout}",
                max_releases=max_releases,
            )
    after_hash = sublation_run.tree_hash(target)
    if after_hash != before_hash:
        sublation_run.release_task(
            run_dir,
            task["task_id"],
            task["assigned_actor"],
            task["lease"]["token"],
            "worker_modified_formal_target",
            retryable=False,
            max_releases=max_releases,
        )
        raise RuntimeError(f"worker modified formal target during {task['task_id']}; run blocked")
    if (
        sublation_run.sha256(request_path.read_bytes()) != request_hash
        or sublation_run.tree_hash(snapshot_path) != snapshot_hash
        or (
            candidate_snapshot is not None
            and sublation_run.tree_hash(Path(candidate_snapshot["path"]))
            != candidate_snapshot["snapshot_tree_hash"]
        )
        or (
            candidate_live_path is not None
            and sublation_run.tree_hash(candidate_live_path) != candidate_live_hash
        )
    ):
        sublation_run.release_task(
            run_dir,
            task["task_id"],
            task["assigned_actor"],
            task["lease"]["token"],
            "worker_modified_immutable_task_input",
            retryable=False,
            max_releases=max_releases,
        )
        raise RuntimeError(f"worker modified immutable task input during {task['task_id']}; run blocked")
    if completed is not None and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "worker exited nonzero").strip().splitlines()
        return sublation_run.release_task(
            run_dir,
            task["task_id"],
            task["assigned_actor"],
            task["lease"]["token"],
            "worker_exit:" + " | ".join(detail[:4]),
            max_releases=max_releases,
        )
    if not response_path.is_file():
        return sublation_run.release_task(
            run_dir,
            task["task_id"],
            task["assigned_actor"],
            task["lease"]["token"],
            "worker_response_missing",
            max_releases=max_releases,
        )
    if completed is not None and os.environ.get("SUBLATION_TEST_CRASH_AFTER_WORKER_RESPONSE") == "1":
        os._exit(94)
    try:
        result = validate_result(task, sublation_run.read_json(response_path))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return sublation_run.release_task(
            run_dir,
            task["task_id"],
            task["assigned_actor"],
            task["lease"]["token"],
            f"invalid_worker_response:{error}",
            max_releases=max_releases,
        )
    if task.get("escalated_from_actor") and result.get("item_status") != "BLOCKED":
        prior_error = str(task.get("last_error") or "delegated_worker_exhausted")
        return sublation_run.release_task(
            run_dir,
            task["task_id"],
            task["assigned_actor"],
            task["lease"]["token"],
            prior_error + "; coordinator_must_close_exhausted_delegated_task_as_blocked",
            retryable=False,
            max_releases=max_releases,
        )
    return sublation_run.record_step(
        run_dir,
        step_id=result["step_id"],
        item_id=task["item_id"],
        actor=task["assigned_actor"],
        phase=task["phase"],
        step_status=result["step_status"],
        item_status=result["item_status"],
        candidate_id=result.get("candidate_id"),
        candidate_path=result.get("candidate_path"),
        summary=result.get("summary"),
        disposition=result.get("disposition"),
        evidence=[*result["evidence"], str(response_path)],
        blockers=result["blockers"],
        task_id=task["task_id"],
        lease_token=task["lease"]["token"],
        executor_principal=worker["principal_id"],
        adapter_fingerprint=worker["adapter_fingerprint"],
        candidate_tree_hash=(
            candidate_live_hash
            if task["phase"] in {"audit", "independent_verify", "boundary_review", "aggregate"}
            else None
        ),
    )


def deliver_report(run_dir: Path, report: dict[str, Any], adapter: dict[str, Any]) -> dict[str, Any]:
    run = sublation_run.load_run(run_dir)
    expected_actor = run["review_policy"]["roles"]["coordinator"]
    if adapter["actor"] != expected_actor:
        raise ValueError(f"final report must be delivered by coordinator {expected_actor!r}")
    plain_report = sublation_run.verify_plain_report(run_dir, report)
    for delivery in report.get("delivery", []):
        if delivery.get("channel") == adapter["channel"]:
            evidence = delivery.get("adapter_evidence") or {}
            return sublation_run.record_delivery(
                run_dir,
                str(delivery.get("channel") or ""),
                str(delivery.get("message_ref") or ""),
                list(delivery.get("authorized_reply_senders") or []),
                int(report["report_version"]),
                sender_actor=str(delivery.get("sender_actor") or ""),
                idempotency_key=str(delivery.get("idempotency_key") or ""),
                adapter_evidence_path=str(evidence.get("path") or ""),
                report_body_hash=str(delivery.get("report_body_hash") or ""),
                delivery_text_hash=str(delivery.get("delivery_text_hash") or ""),
            )
    io_dir = run_dir / "delivery-io"
    io_dir.mkdir(parents=True, exist_ok=True)
    key = f"report-v{report['report_version']}-{str(report['report_hash']).split(':')[-1][:16]}"
    request_path = io_dir / f"{key}.request.json"
    response_path = io_dir / f"{key}.response.json"
    markdown_path = run_dir / f"report-v{report['report_version']}.md"
    request = {
        "protocol": "sublation-delivery-v1",
        "idempotency_key": key,
        "run_id": report["run_id"],
        "report_version": report["report_version"],
        "report_hash": report["report_hash"],
        "report_body_hash": plain_report["sha256"],
        "channel": adapter["channel"],
        "report_path": str(markdown_path),
        "response_path": str(response_path),
    }
    sublation_run.atomic_write_json(request_path, request)
    request_hash = sublation_run.sha256(request_path.read_bytes())
    markdown_hash = sublation_run.sha256(markdown_path.read_bytes())
    if not response_path.is_file():
        if os.environ.get("SUBLATION_TEST_CRASH_BEFORE_DELIVERY_SEND") == "1":
            os._exit(95)
        argv = render_argv(
            adapter["argv"],
            request=request_path,
            response=response_path,
            report=markdown_path,
        )
        configured_write_roots = [
            Path(path).expanduser().resolve() for path in adapter.get("write_roots", [])
        ]
        validate_external_write_roots(
            run_dir,
            run,
            [str(path) for path in configured_write_roots],
            "configured delivery",
        )
        completed = subprocess.run(
            isolated_argv(
                run_dir,
                run,
                argv,
                [str(request_path.parent), *(str(path) for path in configured_write_roots)],
                [request_path, markdown_path],
                list(adapter.get("read_roots") or []),
                bool(adapter.get("network_access")),
            ),
            cwd=io_dir,
            env=sanitized_environment(
                io_dir,
                {"SUBLATION_RUN_ID": str(run["run_id"])},
            ),
            text=True,
            capture_output=True,
            timeout=adapter["timeout_seconds"],
        )
        if completed.returncode:
            detail = (completed.stderr or completed.stdout or "delivery adapter failed").strip().splitlines()
            raise RuntimeError("delivery_adapter_exit:" + " | ".join(detail[:4]))
        if not response_path.is_file():
            raise RuntimeError("delivery adapter did not write a response")
        if os.environ.get("SUBLATION_TEST_CRASH_AFTER_DELIVERY_SEND") == "1":
            os._exit(96)
    if (
        sublation_run.sha256(request_path.read_bytes()) != request_hash
        or sublation_run.sha256(markdown_path.read_bytes()) != markdown_hash
        or markdown_hash != plain_report["sha256"]
    ):
        raise RuntimeError("delivery adapter modified immutable report input")
    response = sublation_run.read_json(response_path)
    unknown = sorted(set(response) - DELIVERY_RESULT_FIELDS)
    if unknown:
        raise ValueError("delivery result has unknown fields: " + ", ".join(unknown))
    if response.get("sender_actor") != adapter["actor"] or not str(response.get("message_ref") or "").strip():
        raise ValueError("delivery result needs the configured sender_actor and a message_ref")
    if response.get("report_body_hash") != plain_report["sha256"]:
        raise ValueError("delivery result report_body_hash differs from the finalized report")
    if not str(response.get("delivery_text_hash") or "").strip():
        raise ValueError("delivery result needs delivery_text_hash")
    return sublation_run.record_delivery(
        run_dir,
        adapter["channel"],
        str(response["message_ref"]),
        adapter["authorized_reply_senders"],
        int(report["report_version"]),
        sender_actor=adapter["actor"],
        idempotency_key=key,
        adapter_evidence_path=str(response_path),
        report_body_hash=str(response["report_body_hash"]),
        delivery_text_hash=str(response["delivery_text_hash"]),
    )


def _run_until_wait_locked(
    run_dir: Path,
    workers: dict[str, dict[str, Any]],
    *,
    delivery: dict[str, Any] | None = None,
    max_steps: int = 1000,
    lease_seconds: int = 1800,
    max_releases: int = 3,
    finalize: bool = True,
) -> dict[str, Any]:
    initial_run = sublation_run.load_run(run_dir)
    for actor, worker in workers.items():
        validate_external_write_roots(
            run_dir,
            initial_run,
            list(worker.get("write_roots") or []),
            f"worker {actor!r}",
        )
    if delivery:
        validate_external_write_roots(
            run_dir,
            initial_run,
            list(delivery.get("write_roots") or []),
            "delivery adapter",
        )
    sublation_run.bind_worker_identities(
        run_dir,
        {
            actor: {
                "principal_id": worker["principal_id"],
                "adapter_fingerprint": worker["adapter_fingerprint"],
                "write_roots": list(worker.get("write_roots") or []),
            }
            for actor, worker in workers.items()
        },
    )
    executed = 0
    while executed < max_steps:
        run = sublation_run.load_run(run_dir)
        actors = list(dict.fromkeys(run["review_policy"]["roles"].values()))
        progressed = False
        for actor in actors:
            worker = workers.get(actor)
            if not worker:
                continue
            task = sublation_run.claim_task(run_dir, actor, lease_seconds)
            if not task:
                continue
            execute_task(run_dir, task, worker, max_releases=max_releases)
            executed += 1
            progressed = True
            break
        if not progressed:
            break
    run = sublation_run.load_run(run_dir)
    terminal = all(item.get("status") in sublation_run.TERMINAL_ITEM_STATES for item in run.get("items", []))
    report: dict[str, Any] | None = None
    if terminal and finalize:
        report = sublation_run.finalize_report(run_dir)
        if delivery:
            report = deliver_report(run_dir, report, delivery)
    result = sublation_run.status(run_dir)
    result["worker_steps_executed"] = executed
    result["waiting_for_workers"] = sorted(
        {
            action["assigned_actor"]
            for action in result["next_actions"]
            if action["assigned_actor"] not in workers
        }
    )
    result["max_steps_reached"] = executed >= max_steps
    result["waiting_for_delivery"] = bool(report and not report.get("delivery"))
    return result


def run_until_wait(
    run_dir: Path,
    workers: dict[str, dict[str, Any]],
    *,
    delivery: dict[str, Any] | None = None,
    max_steps: int = 1000,
    lease_seconds: int = 1800,
    max_releases: int = 3,
    finalize: bool = True,
) -> dict[str, Any]:
    if max_steps < 1:
        raise ValueError("max_steps must be at least 1")
    if max_releases < 1:
        raise ValueError("max_releases must be at least 1")
    if lease_seconds < 30 or lease_seconds > 86400:
        raise ValueError("lease_seconds must be between 30 and 86400")
    unsafe_timeouts = sorted(
        actor
        for actor, worker in workers.items()
        if int(worker.get("timeout_seconds", 0)) >= lease_seconds
    )
    if unsafe_timeouts:
        raise ValueError(
            "task lease must exceed worker timeout for: " + ", ".join(unsafe_timeouts)
        )
    resolved = run_dir.expanduser().resolve()
    with orchestrator_lock(resolved):
        return _run_until_wait_locked(
            resolved,
            workers,
            delivery=delivery,
            max_steps=max_steps,
            lease_seconds=lease_seconds,
            max_releases=max_releases,
            finalize=finalize,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--worker-config", required=True)
    parser.add_argument("--max-steps", type=int, default=1000)
    parser.add_argument("--lease-seconds", type=int, default=1800)
    parser.add_argument("--max-releases", type=int, default=3)
    parser.add_argument("--no-finalize", action="store_true")
    args = parser.parse_args()
    config = load_orchestrator_config(Path(args.worker_config))
    result = run_until_wait(
        Path(args.run_dir),
        config["workers"],
        delivery=config["delivery"],
        max_steps=args.max_steps,
        lease_seconds=args.lease_seconds,
        max_releases=args.max_releases,
        finalize=not args.no_finalize,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
