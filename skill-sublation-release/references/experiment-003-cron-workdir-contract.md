# Experiment 003 — Cron Workdir Contract

## Summary

- Skill: `npl-monitor`
- Candidate: `npl-monitor/20260526-cron-workdir-contract-codex`
- Candidate type: `infra-fix`
- Created by: Codex
- Cross reviewer: Hermes supplemental review
- Status: promoted, awaiting production observation window

## Trigger Observation

The 2026-05-26 NPL cron run first tried to execute `python3 scripts/...` from an incorrect cwd, resolving to `~/.hermes/skills/scripts/...`. The job recovered later, but the recovery path was opaque.

## Candidate Scope

### Changes

- Require relative script commands to run from the formal skill root.
- Set cron job workdir to `~/.hermes/skills/legal/npl-monitor`.
- Treat old-format data files without `source_ok/status` as incomplete 002 production validation.

### Out of Scope

- No script code changes.
- No Playwright or anti-bot bypass.
- No real data writes during validation.

## Validation

- Ran 4 fixture/temp-output checks with formal 002 scripts.
- Outputs went to `/private/tmp/npl-003-validation`.
- Assertions passed for `auction_ok`, `auction_blocked`, `yindeng_ok`, and `yindeng_parse_empty`.

## Lesson For Sublation

Not every failure is a skill-content defect. `infra-fix` must be a first-class candidate type, and promotion should include a production observation window before a candidate is marked fully closed.

