#!/usr/bin/env python3
"""Unit tests for delivery_report.py."""

from __future__ import annotations

import copy
import unittest

from delivery_report import render_markdown, validate_payload


SHA = "sha256:" + ("a" * 64)


def valid_payload() -> dict:
    evidence = [{"label": "fixture", "sha256": SHA}]
    return {
        "schema_version": "skill-sublation.delivery-report-input.v1",
        "batch_id": "batch-1",
        "generated_at": "2026-07-25T00:00:00Z",
        "measured": [
            {
                "metric": "skill_count",
                "label": "Skill count",
                "unit": "skills",
                "before": 4,
                "after": 1,
                "evidence": evidence,
            }
        ],
        "estimated": [
            {
                "metric": "resident_tokens",
                "label": "Resident tokens",
                "unit": "tokens/session",
                "value": 350,
                "formula": "character_delta / 1.5",
                "assumptions": ["1.5 Chinese characters per token"],
                "evidence": evidence,
            }
        ],
        "not_measurable": [
            {
                "metric": "choice_burden",
                "label": "Choice burden",
                "statement": "The route presents one entry point.",
                "evidence": evidence,
            }
        ],
    }


class DeliveryReportTests(unittest.TestCase):
    def test_valid_payload_renders_three_distinct_sections(self) -> None:
        report = render_markdown(valid_payload())
        self.assertIn("## Measured", report)
        self.assertIn("## Estimated", report)
        self.assertIn("## Not Measurable", report)
        self.assertIn("| Skill count | 4 | 1 | -3 |", report)

    def test_rendering_is_deterministic(self) -> None:
        payload = valid_payload()
        self.assertEqual(render_markdown(payload), render_markdown(copy.deepcopy(payload)))

    def test_estimated_requires_formula_and_assumptions(self) -> None:
        payload = valid_payload()
        del payload["estimated"][0]["formula"]
        payload["estimated"][0]["assumptions"] = []
        errors = validate_payload(payload)
        self.assertTrue(any(".formula is required" in item for item in errors))
        self.assertTrue(any(".assumptions must be" in item for item in errors))

    def test_not_measurable_rejects_numeric_claim(self) -> None:
        payload = valid_payload()
        payload["not_measurable"][0]["value"] = 99
        errors = validate_payload(payload)
        self.assertTrue(any("unsupported keys: value" in item for item in errors))

    def test_metric_cannot_cross_tiers(self) -> None:
        payload = valid_payload()
        payload["estimated"][0]["metric"] = "skill_count"
        errors = validate_payload(payload)
        self.assertTrue(any("appears in both measured and estimated" in item for item in errors))

    def test_evidence_hash_is_strict(self) -> None:
        payload = valid_payload()
        payload["measured"][0]["evidence"][0]["sha256"] = "sha256:ABC"
        errors = validate_payload(payload)
        self.assertTrue(any("64 lowercase hex" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
