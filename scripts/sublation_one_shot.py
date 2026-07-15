#!/usr/bin/env python3
"""Start or resume a complete candidate-only Sublation run from one explicit intent."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import sublation_local_adapter
import sublation_orchestrate
import sublation_run


def default_roots() -> list[dict[str, str]]:
    candidates = (
        ("hermes", Path("~/.hermes/skills").expanduser()),
        ("codex", Path("~/.codex/skills").expanduser()),
        ("claude-code", Path("~/.claude/skills").expanduser()),
    )
    return [
        {"name": name, "path": str(path.resolve())}
        for name, path in candidates
        if path.is_dir()
    ]


def normalized_roots(roots: list[dict[str, str]]) -> list[dict[str, str]]:
    return sorted(
        [
            {"name": str(root["name"]), "path": str(Path(root["path"]).expanduser().resolve())}
            for root in roots
        ],
        key=lambda root: root["name"].casefold(),
    )


def resumable_run(
    runs_root: Path, intent: str, roots: list[dict[str, str]]
) -> Path | None:
    root = runs_root.expanduser().resolve()
    if not root.is_dir():
        return None
    expected_roots = normalized_roots(roots)
    matches: list[tuple[str, Path]] = []
    for path in root.iterdir():
        if not path.is_dir() or not (path / "run.json").is_file():
            continue
        try:
            raw = sublation_run.read_json(path / "run.json")
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if raw.get("intent") != intent:
            continue
        run = sublation_run.load_run(path)
        if normalized_roots(list(run.get("configured_roots") or [])) != expected_roots:
            continue
        if run.get("latest_report") is None:
            matches.append((str(run.get("updated_at") or run.get("created_at") or ""), path))
    return max(matches, default=("", None), key=lambda item: item[0])[1]


def create_local_config(args: argparse.Namespace, run_dir: Path, output: Path) -> None:
    config_args = argparse.Namespace(
        run_dir=str(run_dir),
        candidate_root=str(Path(args.candidate_root).expanduser().resolve()),
        output=str(output),
        endpoint=args.endpoint,
        authorized_reply_sender=args.authorized_reply_sender,
        codex_bin=args.codex_bin,
        claude_bin=args.claude_bin,
        hermes_bin=args.hermes_bin,
        worker_timeout=args.worker_timeout,
        delivery_timeout=args.delivery_timeout,
    )
    sublation_local_adapter.build_config(config_args)


def run_one_shot(args: argparse.Namespace) -> dict[str, Any]:
    runs_root = Path(args.runs_root).expanduser().resolve()
    roots = sublation_run.load_roots(args.root, args.roots_file) if (args.root or args.roots_file) else default_roots()
    if not roots:
        raise ValueError("no local skill roots were found; provide --root NAME=PATH")
    if args.run_id:
        run_dir = sublation_run.start_run(args.intent, runs_root, roots, args.run_id)
    else:
        run_dir = resumable_run(runs_root, args.intent, roots) or sublation_run.start_run(
            args.intent, runs_root, roots
        )
    config_path = Path(args.worker_config).expanduser().resolve() if args.worker_config else run_dir / "local-worker-config.json"
    if not args.worker_config or args.refresh_adapters or not config_path.is_file():
        create_local_config(args, run_dir, config_path)
    config = sublation_orchestrate.load_orchestrator_config(config_path)
    result = sublation_orchestrate.run_until_wait(
        run_dir,
        config["workers"],
        delivery=config["delivery"],
        max_steps=args.max_steps,
        lease_seconds=args.lease_seconds,
        max_releases=args.max_releases,
    )
    return {"run_dir": str(run_dir), "worker_config": str(config_path), **result}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intent", required=True)
    parser.add_argument("--runs-root", default="~/.hermes/sublation/runs")
    parser.add_argument("--candidate-root", default="~/.hermes/sublation/candidates")
    parser.add_argument("--root", action="append", default=[])
    parser.add_argument("--roots-file")
    parser.add_argument("--run-id")
    parser.add_argument("--worker-config")
    parser.add_argument("--refresh-adapters", action="store_true")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8787/api/messages")
    parser.add_argument("--authorized-reply-sender", action="append", default=["user"])
    parser.add_argument("--codex-bin")
    parser.add_argument("--claude-bin")
    parser.add_argument("--hermes-bin")
    parser.add_argument("--worker-timeout", type=int, default=1800)
    parser.add_argument("--delivery-timeout", type=int, default=60)
    parser.add_argument("--max-steps", type=int, default=1000)
    parser.add_argument("--lease-seconds", type=int, default=2100)
    parser.add_argument("--max-releases", type=int, default=3)
    args = parser.parse_args()
    print(json.dumps(run_one_shot(args), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
