# Changelog

## v3.0.0 - 2026-07-14

### Added

- Executable Loop Engineering gate and decision-packet generator.
- Durable one-shot run ledger, bounded worker orchestration, local ephemeral adapter, approval receipt verification, and rollback-aware promotion helpers.
- Run and worker configuration schemas.
- Tests for loop automation, durable runs, orchestration, receipts, adapters, and promotion recovery.

### Changed

- The skill entrypoint now documents explicit-trigger one-shot behavior and `USER_DECISION_REQUIRED` as the default automation endpoint.
- Release guidance binds evidence, review state, reports, approvals, candidate revisions, and baseline hashes before formal writes.
- Public release text uses generic user/approver roles and excludes internal incident records and private runtime artifacts.

### Retained

- V2 configurable review seats, strict audit, value-delta gate, decision history, observation windows, and evidence-not-authority model.
- Formal skill roots remain read-only until explicit user approval.

## v2.0.0 - 2026-06-13

### Added

- Configurable review policy metadata for default three-agent, configured multi-agent, single-agent, and user-waived review modes.
- Explicit value-delta, decision-history, independent-reproduction, rejected-alternative, redacted-reporting, and post-promotion safety checks.
- Strong-path checks and bytecode-aware patch verification for cleanup candidates.
- Public release package manifest and checksums.

### Changed

- Promotion evidence now treats Hermes, Claude Code, Codex, and external evaluators as evidence sources rather than promotion authorities.
- Review-seat policy is manifest-driven, while user approval remains the final boundary for formal promotion.
- Release documentation now separates public package contents from private runtime candidate and rollback records.

### Fixed

- Removed R1 unauthorized SKILL.md content instead of justifying it after the fact.
- Removed stale release-facing references and a broken template link.
- Removed bytecode residue from release candidates and formal release packaging.
- Replaced release-facing personal-path examples with portable placeholders.

## v1.0.0 - 2026-05-29

- Initial public release package for the Skill Sublation governance pipeline.
- Candidate, audit, lifecycle, and observation helpers.
- Manifest v3 and observation v3 schemas.
- Initial release checklist and audit report.
