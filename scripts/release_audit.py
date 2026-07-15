#!/usr/bin/env python3
"""Audit a public Skill Sublation release without treating it as a candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


EXCLUDED_PARTS = {".git", "__pycache__"}
FORBIDDEN_PATH_PARTS = {"private", "candidates", "rollback-points", "review-exports", "coordination"}
PERSONAL_NAME = "Zhu" + "anz"
CONTENT_RULES = {
    "personal_name": re.compile(r"\b" + PERSONAL_NAME + r"\b", re.IGNORECASE),
    "personal_absolute_path": re.compile(
        r"/Users/" + PERSONAL_NAME + r"(?:/|\b)|/home/" + "a" + "a" + r"(?:/|\b)"
    ),
    "room_message_id": re.compile(r"\b178\d{10}\b"),
    "raw_room_log": re.compile("messages" + r"\.jsonl|coordination/" + "tri-party-chat/data"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
}
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def iter_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and not any(part in EXCLUDED_PARTS for part in path.relative_to(root).parts)
    )


def tree_hash(root: Path, files: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in files:
        rel = path.relative_to(root).as_posix()
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def add_finding(findings: list[dict[str, object]], rule: str, path: str, line: int | None = None) -> None:
    finding: dict[str, object] = {"rule": rule, "path": path}
    if line is not None:
        finding["line"] = line
    findings.append(finding)


def audit(root: Path) -> dict[str, object]:
    root = root.resolve()
    files = iter_files(root)
    findings: list[dict[str, object]] = []

    for path in root.rglob("*"):
        rel = path.relative_to(root).as_posix()
        parts = set(path.relative_to(root).parts)
        if path.is_symlink():
            add_finding(findings, "symlink_not_allowed", rel)
        if parts & FORBIDDEN_PATH_PARTS:
            add_finding(findings, "private_runtime_path_not_allowed", rel)
        if path.name.endswith((".pyc", ".pyo")) or "__pycache__" in parts:
            add_finding(findings, "bytecode_not_allowed", rel)

    skill_path = root / "SKILL.md"
    if not skill_path.is_file():
        add_finding(findings, "missing_skill", "SKILL.md")
    else:
        skill_text = skill_path.read_text(encoding="utf-8")
        if not skill_text.startswith("---\n") or "\n---\n" not in skill_text[4:]:
            add_finding(findings, "invalid_skill_frontmatter", "SKILL.md")
        for field in ("name:", "version:", "description:", "license:"):
            if field not in skill_text.split("\n---\n", 1)[0]:
                add_finding(findings, "missing_skill_frontmatter_field", "SKILL.md")

    for path in files:
        rel = path.relative_to(root).as_posix()
        if path.suffix.lower() == ".json":
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                add_finding(findings, "invalid_json", rel)

        if path.suffix.lower() not in {".md", ".txt", ".py", ".json", ".sh"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            add_finding(findings, "non_utf8_text", rel)
            continue

        for rule, pattern in CONTENT_RULES.items():
            match = pattern.search(text)
            if match:
                line = text.count("\n", 0, match.start()) + 1
                add_finding(findings, rule, rel, line)

        if path.suffix.lower() != ".md":
            continue
        for match in MARKDOWN_LINK.finditer(text):
            raw_target = match.group(1).strip()
            target = raw_target.split("#", 1)[0].strip()
            if not target or target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            if any(marker in target for marker in ("<", ">", "{", "}")):
                continue
            resolved = (path.parent / target).resolve()
            try:
                resolved.relative_to(root)
            except ValueError:
                add_finding(findings, "markdown_link_escapes_root", rel)
                continue
            if not resolved.exists():
                line = text.count("\n", 0, match.start()) + 1
                add_finding(findings, "broken_markdown_link", rel, line)

    return {
        "schema_version": "sublation-public-release-audit-v1",
        "status": "PASS" if not findings else "HOLD",
        "root": str(root),
        "file_count": len(files),
        "finding_count": len(findings),
        "tree_sha256": tree_hash(root, files),
        "findings": findings,
        "note": "Matched values are intentionally omitted.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    report = audit(args.root)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "file_count", "finding_count", "tree_sha256")}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
