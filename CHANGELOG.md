# Changelog

All notable changes to skill-sublation, derived from the candidate governance trail.

## v1.0 (2026-05-29) — Maintenance Mode

### Framework Complete

The self-governance trail drove the framework from an initial experiment to a production-ready governance system, then added release backfills and pre-release hardening.

### Candidate Timeline

| Date | Candidate | Type | What Changed |
|------|-----------|------|-------------|
| 2026-05-26 | core-runtime-codex | tooling | Core runtime: observe→candidate→audit pipeline |
| 2026-05-27 | audit-strict-checks-codex | tooling | 22 strict audit checks (residual labels, PATCH.diff format, manifest consistency, etc.) |
| 2026-05-27 | audit-semantic-fix-codex | tooling | Fixed audit semantic handling of closed/superseded candidates |
| 2026-05-27 | candidate-lifecycle-codex | tooling | 9-state lifecycle management + `lifecycle.py` CLI |
| 2026-05-27 | observation-window-closure-policy-codex | spec-patch | Mandatory observation window closure with evidence requirements |
| 2026-05-27 | observation-window-health-codex | tooling | `lifecycle.py health` for scanning stale observation windows |
| 2026-05-27 | health-waive-legacy-codex | tooling | Legacy cutoff for health scanning historical records |
| 2026-05-27 | legacy-migration-plan-codex | tooling | `lifecycle.py plan-legacy` for v2→v3 migration planning |
| 2026-05-27 | patch-diff-validation-codex | tooling | PATCH.diff strict format validation (bare `@@` blocking) |
| 2026-05-27 | promotion-readiness-cleanup-codex | spec-patch | Pre-promotion cleanup checklist (candidate labels, adjacent work, diff scope) |
| 2026-05-28 | cross-skill-relationships-codex | spec-patch | Cross-skill absorption pattern + manifest relationships schema |
| 2026-05-28 | darwin-evaluator-adapter-codex | spec-patch | External evaluator adapter (Darwin: read-only scorecard, proposal-only) |
| 2026-05-28 | post-promotion-safety-net-codex | spec-patch | Post-promotion safety net: rollback, path verification, smoke test, fallback |
| 2026-05-28 | merge-driven-sublation-backfill-hermes | spec-patch | **Backfill.** Merge-driven sublation methodology (32→11 skills, -66%). Governance trail retroactively documented. |
| 2026-05-29 | v1-release-process-backfill-codex | spec-patch | **Backfill.** v1.0 release process documented in the governance trail. |
| 2026-05-29 | pre-release-audit-pattern-backfill-codex | spec-patch | **Backfill.** Codex + Hermes pre-release audit pattern documented. |
| 2026-05-29 | pre-release-hardening-codex | tooling | Hardened candidate path handling, VCS artifact exclusion, and observation range validation. |
| 2026-05-29 | public-release-joint-audit-backfill-codex | spec-patch | **Backfill.** Public release now requires cleanup, joint audit, JOINT-AUDIT.md, and user approval before push. |

### Merge-Driven Consolidation

Two rounds of skill merging reduced 32 skills to 11 (-66%):

**Round 1** (15→5): document-ocr, universal-converter, content-publisher, skill-lifecycle, media-toolkit
**Round 2** (17→6): speech-to-text, document-generator, legal-research-hub, legal-document-ingest, stock-workspace, contract-review

### Cross-Skill Governance

Production candidates across governed skills: skill-sublation (14), npl-monitor (3), canghe-comic (1), canghe-article-illustrator (1), canghe-infographic (1), legal-case-search (1), legal-qa-extractor (1), case-knowledge-graph (1), npl-due-diligence (1), gbrain (1), ai-daily-briefing (1) — plus backfill.

All closed. Queue empty. Health scan clean.

### Post-Promotion Safety Net

Every promoted candidate now carries:
- Rollback readiness + rollback point
- Target path verification (cross-agent path mismatch protection)
- Business smoke test (not just structural audit)
- Fallback verification (external service degradation)
- Old capability retention check
