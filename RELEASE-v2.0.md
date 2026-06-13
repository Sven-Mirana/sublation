# Skill Sublation v2.0.0 Release Notes

Date: 2026-06-13
Status: Local package prepared; external publication not performed by this build step.

## Summary

v2.0 hardens Skill Sublation as a release-governed process instead of a loose self-edit loop. The release preserves candidate-first semantics, adds configurable review seats, strengthens promotion evidence requirements, and closes release hygiene blockers identified before publication.

## Promoted Local Candidates

- `20260612-configurable-review-seats-codex`
- `20260612-release-hygiene-codex`

Both candidates are in `observation_window` in the local governance records. Runtime candidate manifests and rollback snapshots are excluded from the public package because they contain environment-specific paths.

## Release Blockers Resolved

| ID | Resolution |
|---|---|
| R1 | Deleted unauthorized SKILL.md content; future reintroduction must be a fresh candidate with source evidence. |
| R2 | Scrubbed hard-coded personal path leakage from release-facing content. |
| R3 | Removed stale release-facing references. |
| R4 | Removed bytecode residue and excluded bytecode from package output. |
| R5 | Corrected broken release-facing reference link. |

## Validation Evidence

- Strict audit passed for `configurable-review-seats`.
- Strict audit passed for `release-hygiene`.
- `scripts/test_review_policy.py` passed: 11 passed, 0 failed.
- Package scan found no `.pyc`, `__pycache__`, `.DS_Store`, or `.git` artifacts.
- Package scan found no local personal path matching the maintainer workstation.
- Package scan found no deleted R1 target wording.

## Non-Goals

- No GitHub push, tag, release creation, credential step, or external publication was performed.
- No private candidate, rollback, chat, or local workspace evidence is bundled.
- No formal skill writes outside the approved v2.0 promotion and release-hygiene scope are represented as user-approved promotion.
