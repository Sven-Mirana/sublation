#!/usr/bin/env python3
"""Unit tests for minimal Skill usage telemetry."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from log_skill_use import append_record, build_record
from usage_report import load_events, render_markdown


class UsageTelemetryTests(unittest.TestCase):
    def test_new_record_has_only_three_fields_and_no_private_content(self) -> None:
        sentinel = "PRIVATE-SENTINEL-DO-NOT-STORE"
        event = {
            "tool_name": "Skill",
            "session_id": "session-secret-123",
            "prompt": sentinel,
            "tool_input": {
                "skill": "skill-sublation",
                "args": sentinel,
                "file_content": sentinel,
            },
            "tool_result": sentinel,
        }
        record = build_record(event, now=lambda: "2026-07-25T00:00:00Z")
        self.assertEqual(set(record or {}), {"ts", "skill", "session_id"})
        self.assertNotIn(sentinel, json.dumps(record))
        self.assertEqual(len(record["session_id"]), 12)
        self.assertNotEqual(record["session_id"], event["session_id"][:12])

    def test_non_skill_event_is_ignored(self) -> None:
        event = {"tool_name": "Read", "session_id": "abc", "tool_input": {"skill": "x"}}
        self.assertIsNone(build_record(event))

    def test_append_and_load_preserve_minimal_contract(self) -> None:
        record = {
            "ts": "2026-07-25T00:00:00Z",
            "skill": "skill-sublation",
            "session_id": "0123456789ab",
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "usage.jsonl"
            append_record(record, path)
            events, rejected = load_events(path)
            self.assertEqual(events, [record])
            self.assertEqual(rejected, 0)
            self.assertEqual(set(json.loads(path.read_text())), set(record))

    def test_extra_content_field_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "usage.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "ts": "2026-07-25T00:00:00Z",
                        "skill": "skill-sublation",
                        "session_id": "0123456789ab",
                        "prompt": "must-not-pass",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            events, rejected = load_events(path)
            self.assertEqual(events, [])
            self.assertEqual(rejected, 1)

    def test_report_never_exposes_session_ids(self) -> None:
        events = [
            {
                "ts": "2026-07-25T00:00:00Z",
                "skill": "skill-sublation",
                "session_id": "0123456789ab",
            }
        ]
        report = render_markdown(events)
        self.assertIn("Distinct sessions", report)
        self.assertNotIn("0123456789ab", report)

    def test_zero_call_row_requires_explicit_inventory(self) -> None:
        report_without = render_markdown([])
        report_with = render_markdown([], known_skills=["unused-skill"])
        self.assertNotIn("unused-skill", report_without)
        self.assertIn("| `unused-skill` | 0 |", report_with)

    def test_legacy_three_field_record_is_read_only_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "usage.jsonl"
            path.write_text(
                '{"ts":"2026-07-25T00:00:00Z","skill":"skill-sublation","session":"deadbeef"}\n',
                encoding="utf-8",
            )
            events, rejected = load_events(path)
            self.assertEqual(rejected, 0)
            self.assertEqual(events[0]["session_id"], "deadbeef")


if __name__ == "__main__":
    unittest.main()
