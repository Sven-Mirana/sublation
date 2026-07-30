#!/usr/bin/env python3
"""Unit tests for scenario_map.py."""

from __future__ import annotations

import copy
import unittest

from scenario_map import render_markdown, validate_payload


def route(skill: str = "skill-sublation") -> dict:
    return {
        "skill": skill,
        "description": "Govern isolated Skill changes.",
        "scenarios": ["governance", "software_delivery"],
        "trigger_terms": ["candidate", "audit"],
        "routing_boundary": {
            "primary_when": ["A Skill change needs evidence and review."],
            "not_when": ["The request is ordinary content editing."],
            "handoff_to": [
                {
                    "skill": "legal-research-hub",
                    "when": "The task is legal retrieval rather than Skill governance.",
                }
            ],
            "clarify_when": ["The requested target root is ambiguous."],
        },
    }


def valid_payload() -> dict:
    return {
        "schema_version": "skill-sublation.scenario-taxonomy.v1",
        "map_id": "map-1",
        "skills": [route()],
    }


class ScenarioMapTests(unittest.TestCase):
    def test_valid_map_renders_scenarios_and_boundary(self) -> None:
        report = render_markdown(valid_payload())
        self.assertIn("Skill 治理", report)
        self.assertIn("软件交付", report)
        self.assertIn("Handoff to `legal-research-hub`", report)

    def test_rendering_is_deterministic(self) -> None:
        payload = valid_payload()
        self.assertEqual(render_markdown(payload), render_markdown(copy.deepcopy(payload)))

    def test_unknown_scenario_is_rejected(self) -> None:
        payload = valid_payload()
        payload["skills"][0]["scenarios"] = ["private_unknown"]
        self.assertTrue(any("unknown ids" in item for item in validate_payload(payload)))

    def test_duplicate_skill_is_rejected(self) -> None:
        payload = valid_payload()
        payload["skills"].append(copy.deepcopy(payload["skills"][0]))
        self.assertTrue(any("duplicate skill route" in item for item in validate_payload(payload)))

    def test_self_handoff_is_rejected(self) -> None:
        payload = valid_payload()
        payload["skills"][0]["routing_boundary"]["handoff_to"][0]["skill"] = "skill-sublation"
        self.assertTrue(any("cannot hand off to itself" in item for item in validate_payload(payload)))

    def test_primary_boundary_is_required(self) -> None:
        payload = valid_payload()
        payload["skills"][0]["routing_boundary"]["primary_when"] = []
        self.assertTrue(any("primary_when must be nonempty" in item for item in validate_payload(payload)))


if __name__ == "__main__":
    unittest.main()
