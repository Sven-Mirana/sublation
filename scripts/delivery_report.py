#!/usr/bin/env python3
"""Render a deterministic Skill Sublation value-delta report."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "skill-sublation.delivery-report-input.v1"
METRIC_RE = re.compile(r"^[a-z][a-z0-9_]*$")
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_evidence(items: Any, prefix: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(items, list) or not items:
        return [f"{prefix}.evidence must be a nonempty array"]
    for index, item in enumerate(items):
        item_prefix = f"{prefix}.evidence[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_prefix} must be an object")
            continue
        if set(item) != {"label", "sha256"}:
            errors.append(f"{item_prefix} must contain only label and sha256")
        if not _nonempty(item.get("label")):
            errors.append(f"{item_prefix}.label is required")
        if not isinstance(item.get("sha256"), str) or not SHA256_RE.fullmatch(item["sha256"]):
            errors.append(f"{item_prefix}.sha256 must be sha256:<64 lowercase hex>")
    return errors


def _validate_base(item: Any, prefix: str, allowed: set[str]) -> list[str]:
    errors: list[str] = []
    if not isinstance(item, dict):
        return [f"{prefix} must be an object"]
    unknown = sorted(set(item) - allowed)
    if unknown:
        errors.append(f"{prefix} contains unsupported keys: {', '.join(unknown)}")
    metric = item.get("metric")
    if not isinstance(metric, str) or not METRIC_RE.fullmatch(metric):
        errors.append(f"{prefix}.metric must match {METRIC_RE.pattern}")
    if not _nonempty(item.get("label")):
        errors.append(f"{prefix}.label is required")
    errors.extend(_validate_evidence(item.get("evidence"), prefix))
    return errors


def validate_payload(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["input must be a JSON object"]
    allowed_top = {
        "schema_version",
        "batch_id",
        "generated_at",
        "measured",
        "estimated",
        "not_measurable",
    }
    unknown_top = sorted(set(payload) - allowed_top)
    if unknown_top:
        errors.append(f"input contains unsupported keys: {', '.join(unknown_top)}")
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION!r}")
    if not _nonempty(payload.get("batch_id")):
        errors.append("batch_id is required")
    if "generated_at" in payload and not _nonempty(payload.get("generated_at")):
        errors.append("generated_at must be a nonempty string")

    tier_specs = {
        "measured": {"metric", "label", "unit", "before", "after", "evidence"},
        "estimated": {"metric", "label", "unit", "value", "formula", "assumptions", "evidence"},
        "not_measurable": {"metric", "label", "statement", "evidence"},
    }
    for tier, allowed in tier_specs.items():
        items = payload.get(tier)
        if not isinstance(items, list):
            errors.append(f"{tier} must be an array")
            continue
        seen: set[str] = set()
        for index, item in enumerate(items):
            prefix = f"{tier}[{index}]"
            errors.extend(_validate_base(item, prefix, allowed))
            if not isinstance(item, dict):
                continue
            metric = item.get("metric")
            if isinstance(metric, str):
                if metric in seen:
                    errors.append(f"{tier} repeats metric {metric!r}")
                seen.add(metric)
            if tier == "measured":
                if not _nonempty(item.get("unit")):
                    errors.append(f"{prefix}.unit is required")
                if not _is_number(item.get("before")):
                    errors.append(f"{prefix}.before must be numeric")
                if not _is_number(item.get("after")):
                    errors.append(f"{prefix}.after must be numeric")
            elif tier == "estimated":
                if not _nonempty(item.get("unit")):
                    errors.append(f"{prefix}.unit is required")
                if not _is_number(item.get("value")):
                    errors.append(f"{prefix}.value must be numeric")
                if not _nonempty(item.get("formula")):
                    errors.append(f"{prefix}.formula is required")
                assumptions = item.get("assumptions")
                if (
                    not isinstance(assumptions, list)
                    or not assumptions
                    or not all(_nonempty(value) for value in assumptions)
                ):
                    errors.append(f"{prefix}.assumptions must be a nonempty string array")
            elif not _nonempty(item.get("statement")):
                errors.append(f"{prefix}.statement is required")

    metric_tiers: dict[str, str] = {}
    for tier in ("measured", "estimated", "not_measurable"):
        for item in payload.get(tier, []) if isinstance(payload.get(tier), list) else []:
            if not isinstance(item, dict) or not isinstance(item.get("metric"), str):
                continue
            metric = item["metric"]
            previous = metric_tiers.get(metric)
            if previous:
                errors.append(f"metric {metric!r} appears in both {previous} and {tier}")
            metric_tiers[metric] = tier
    return errors


def _format_number(value: int | float) -> str:
    return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)


def _escape_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _evidence_text(items: list[dict[str, str]]) -> str:
    return "; ".join(f"{item['label']} ({item['sha256']})" for item in items)


def render_markdown(payload: dict[str, Any]) -> str:
    errors = validate_payload(payload)
    if errors:
        raise ValueError("\n".join(errors))

    lines = [
        "# Skill Sublation Value-Delta Delivery Report",
        "",
        f"- Batch: `{_escape_cell(payload['batch_id'])}`",
    ]
    if payload.get("generated_at"):
        lines.append(f"- Generated at: `{_escape_cell(payload['generated_at'])}`")

    lines.extend(
        [
            "",
            "## Measured",
            "",
            "| Metric | Before | After | Delta | Unit | Evidence |",
            "|---|---:|---:|---:|---|---|",
        ]
    )
    if payload["measured"]:
        for item in payload["measured"]:
            delta = item["after"] - item["before"]
            lines.append(
                "| {label} | {before} | {after} | {delta} | {unit} | {evidence} |".format(
                    label=_escape_cell(item["label"]),
                    before=_format_number(item["before"]),
                    after=_format_number(item["after"]),
                    delta=_format_number(delta),
                    unit=_escape_cell(item["unit"]),
                    evidence=_escape_cell(_evidence_text(item["evidence"])),
                )
            )
    else:
        lines.append("| None | - | - | - | - | - |")

    lines.extend(
        [
            "",
            "## Estimated",
            "",
            "| Metric | Value | Unit | Formula | Assumptions | Evidence |",
            "|---|---:|---|---|---|---|",
        ]
    )
    if payload["estimated"]:
        for item in payload["estimated"]:
            lines.append(
                "| {label} | {value} | {unit} | {formula} | {assumptions} | {evidence} |".format(
                    label=_escape_cell(item["label"]),
                    value=_format_number(item["value"]),
                    unit=_escape_cell(item["unit"]),
                    formula=_escape_cell(item["formula"]),
                    assumptions=_escape_cell("; ".join(item["assumptions"])),
                    evidence=_escape_cell(_evidence_text(item["evidence"])),
                )
            )
    else:
        lines.append("| None | - | - | - | - | - |")

    lines.extend(
        [
            "",
            "## Not Measurable",
            "",
            "| Metric | Statement | Evidence |",
            "|---|---|---|",
        ]
    )
    if payload["not_measurable"]:
        for item in payload["not_measurable"]:
            lines.append(
                "| {label} | {statement} | {evidence} |".format(
                    label=_escape_cell(item["label"]),
                    statement=_escape_cell(item["statement"]),
                    evidence=_escape_cell(_evidence_text(item["evidence"])),
                )
            )
    else:
        lines.append("| None | - | - |")
    lines.extend(["", "Tier labels are evidence classes, not confidence decoration.", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_json")
    parser.add_argument("--output")
    args = parser.parse_args()

    try:
        payload = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
        output = render_markdown(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
