# Skill Sublation

Skill Sublation is a governance framework for AI agent skill evolution: observe, candidate, audit, review, promote, and observe again.

Version: v3.0.0
Release date: 2026-07-14
License: MIT

## What It Does

Skill Sublation keeps production skills stable while still letting agent practice improve them. Agents write observations and candidate copies; audits and reviewers produce evidence; a human or delegated local supervisor approves promotion; promoted changes remain in an observation window with rollback evidence.

Core flow:

```text
Observation -> Candidate -> Audit -> Review -> Promotion -> Observation Window
```

## v3.0 Highlights

- Loop Engineering automation: candidate checks, hard gates, evidence aggregation, review-seat state, and decision-packet generation are executable rather than protocol-only.
- One-shot orchestration: an explicit `sublation` or “扬弃” trigger can create or resume a durable run and continue through candidate-layer work without repeatedly interrupting the user.
- Approval integrity: reports, evidence hashes, approval receipts, candidate revisions, baseline state, and approved scope are bound before promotion.
- Bounded adapters: worker roles receive least-privilege read/write/network policies; persistent PATH, provider, credential, launchd, and cron changes remain outside the default path.
- Rollback-safe promotion: formal writes require explicit user approval, a baseline-matched rollback copy, post-write verification, and restoration on failure.
- V2 governance remains intact: configurable review seats, value-delta gates, strict audit, decision history, observation windows, and public-package hygiene are retained.

## Quick Start

```bash
python3 scripts/observe.py <skill-name> \
  --skill-path ~/.hermes/skills/<category>/<skill-name> \
  --session <session-id> \
  --classification defect \
  --reflection-type SKILL_DEFECT \
  --step "script execution" \
  --evidence "error message or observed behavior" \
  --summary "What went wrong"

python3 scripts/candidate.py create <skill-name> \
  --source-path ~/.hermes/skills/<category>/<skill-name> \
  --candidate-type spec-patch \
  --agent hermes

PYTHONDONTWRITEBYTECODE=1 python3 scripts/audit.py ~/.hermes/sublation/candidates/<skill>/<candidate-id> --strict
python3 scripts/lifecycle.py health --warn-after-days 7

# Explicit-trigger V3 one-shot. Run --help first and provide bounded roots/config.
PYTHONDONTWRITEBYTECODE=1 python3 scripts/sublation_one_shot.py --help
```

## Package Contents

- `SKILL.md` is the runtime instruction entrypoint.
- `scripts/` contains candidate, audit, lifecycle, V3 run/orchestration, receipt, promotion, adapter, release-audit, and test helpers.
- `schemas/` contains manifest, observation, run, and worker configuration schemas.
- `references/` contains governance patterns, Loop Engineering contracts, and release procedures.
- `RELEASE-v3.0.md`, `JOINT-AUDIT.md`, `PACKAGE-MANIFEST.json`, and `checksums.sha256` document this local package.

## Release Boundary

This folder is a local release package. It does not include git history, private candidate manifests, rollback snapshots, credentials, internal chat logs, or any automatically executed publication step. `publish.sh` is guarded and only publishes if a human deliberately runs it with `CONFIRM_PUBLISH=1` from a prepared repository.

The candidate strict audit and the public release audit serve different objects. Run `scripts/audit.py --strict` against a candidate directory. Run `scripts/release_audit.py` against this release directory.
