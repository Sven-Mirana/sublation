#!/usr/bin/env python3
"""Validate scenario routes and render a deterministic Markdown map."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "skill-sublation.scenario-taxonomy.v1"
SKILL_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
SCENARIOS = (
    ("governance", "Skill 治理"),
    ("legal_research", "法律检索与法源核验"),
    ("litigation_workbench", "诉讼工作底稿"),
    ("document_processing", "文档处理"),
    ("article_writing", "文章写作"),
    ("wechat_publishing", "微信发布"),
    ("market_daily", "市场日报"),
    ("media_generation", "媒体生成"),
    ("software_delivery", "软件交付"),
    ("general_research", "通用研究"),
)
SCENARIO_IDS = {item[0] for item in SCENARIOS}


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_array(value: Any, *, nonempty: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (not nonempty or bool(value))
        and all(_nonempty(item) for item in value)
    )


def validate_payload(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["input must be a JSON object"]
    if set(payload) - {"schema_version", "map_id", "skills"}:
        errors.append("input contains unsupported top-level keys")
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION!r}")
    if not _nonempty(payload.get("map_id")):
        errors.append("map_id is required")
    skills = payload.get("skills")
    if not isinstance(skills, list):
        return errors + ["skills must be an array"]

    seen: set[str] = set()
    for index, item in enumerate(skills):
        prefix = f"skills[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        allowed = {"skill", "description", "scenarios", "trigger_terms", "routing_boundary"}
        unknown = sorted(set(item) - allowed)
        if unknown:
            errors.append(f"{prefix} contains unsupported keys: {', '.join(unknown)}")
        skill = item.get("skill")
        if not isinstance(skill, str) or not SKILL_RE.fullmatch(skill):
            errors.append(f"{prefix}.skill must be a canonical lowercase skill id")
        elif skill in seen:
            errors.append(f"duplicate skill route: {skill}")
        else:
            seen.add(skill)
        if not _nonempty(item.get("description")):
            errors.append(f"{prefix}.description is required")
        scenarios = item.get("scenarios")
        if not isinstance(scenarios, list) or not scenarios:
            errors.append(f"{prefix}.scenarios must be a nonempty array")
        else:
            unknown_scenarios = sorted(
                scenario for scenario in scenarios if scenario not in SCENARIO_IDS
            )
            if unknown_scenarios:
                errors.append(
                    f"{prefix}.scenarios contains unknown ids: {', '.join(unknown_scenarios)}"
                )
            if len(scenarios) != len(set(scenarios)):
                errors.append(f"{prefix}.scenarios must not contain duplicates")
        triggers = item.get("trigger_terms", [])
        if not _string_array(triggers):
            errors.append(f"{prefix}.trigger_terms must be a string array")
        elif len(triggers) != len(set(triggers)):
            errors.append(f"{prefix}.trigger_terms must not contain duplicates")

        boundary = item.get("routing_boundary")
        if not isinstance(boundary, dict):
            errors.append(f"{prefix}.routing_boundary must be an object")
            continue
        allowed_boundary = {"primary_when", "not_when", "handoff_to", "clarify_when"}
        unknown_boundary = sorted(set(boundary) - allowed_boundary)
        if unknown_boundary:
            errors.append(
                f"{prefix}.routing_boundary contains unsupported keys: "
                + ", ".join(unknown_boundary)
            )
        if not _string_array(boundary.get("primary_when"), nonempty=True):
            errors.append(f"{prefix}.routing_boundary.primary_when must be nonempty")
        for key in ("not_when", "clarify_when"):
            if not _string_array(boundary.get(key)):
                errors.append(f"{prefix}.routing_boundary.{key} must be a string array")
        handoffs = boundary.get("handoff_to")
        if not isinstance(handoffs, list):
            errors.append(f"{prefix}.routing_boundary.handoff_to must be an array")
            continue
        for handoff_index, handoff in enumerate(handoffs):
            handoff_prefix = f"{prefix}.routing_boundary.handoff_to[{handoff_index}]"
            if not isinstance(handoff, dict):
                errors.append(f"{handoff_prefix} must be an object")
                continue
            if set(handoff) != {"skill", "when"}:
                errors.append(f"{handoff_prefix} must contain only skill and when")
            target = handoff.get("skill")
            if not isinstance(target, str) or not SKILL_RE.fullmatch(target):
                errors.append(f"{handoff_prefix}.skill must be a canonical skill id")
            elif target == skill:
                errors.append(f"{handoff_prefix} cannot hand off to itself")
            if not _nonempty(handoff.get("when")):
                errors.append(f"{handoff_prefix}.when is required")
    return errors


def _escape(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_markdown(payload: dict[str, Any]) -> str:
    errors = validate_payload(payload)
    if errors:
        raise ValueError("\n".join(errors))
    ordered_skills = sorted(payload["skills"], key=lambda item: item["skill"])
    lines = [
        "# Skill Sublation Scenario Map",
        "",
        f"- Map: `{_escape(payload['map_id'])}`",
        "- Contract: `skill-sublation.scenario-taxonomy.v1`",
    ]
    for scenario_id, label in SCENARIOS:
        matches = [
            item for item in ordered_skills if scenario_id in item["scenarios"]
        ]
        if not matches:
            continue
        lines.extend(
            [
                "",
                f"## {label}",
                "",
                "| Skill | Description | Primary when | Trigger terms |",
                "|---|---|---|---|",
            ]
        )
        for item in matches:
            boundary = item["routing_boundary"]
            lines.append(
                "| `{skill}` | {description} | {primary} | {triggers} |".format(
                    skill=_escape(item["skill"]),
                    description=_escape(item["description"]),
                    primary=_escape("; ".join(boundary["primary_when"])),
                    triggers=_escape("; ".join(item.get("trigger_terms", [])) or "-"),
                )
            )

    lines.extend(["", "## Routing Boundaries", ""])
    for item in ordered_skills:
        boundary = item["routing_boundary"]
        lines.append(f"### `{_escape(item['skill'])}`")
        lines.append("")
        lines.append(
            "- Not when: "
            + (_escape("; ".join(boundary["not_when"])) if boundary["not_when"] else "none declared")
        )
        lines.append(
            "- Clarify when: "
            + (
                _escape("; ".join(boundary["clarify_when"]))
                if boundary["clarify_when"]
                else "none declared"
            )
        )
        if boundary["handoff_to"]:
            for handoff in sorted(
                boundary["handoff_to"], key=lambda value: (value["skill"], value["when"])
            ):
                lines.append(
                    f"- Handoff to `{_escape(handoff['skill'])}` when: {_escape(handoff['when'])}"
                )
        else:
            lines.append("- Handoff: none declared")
        lines.append("")
    lines.append("This map is advisory and does not invoke or install any Skill.")
    lines.append("")
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
