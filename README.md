# Skill Sublation

Skill Sublation is a governance framework for AI agent skill evolution: observe, candidate, audit, review, promote, and observe again.

Version: v2.0.0
Release date: 2026-06-13
License: MIT

## What It Does

Skill Sublation keeps production skills stable while still letting agent practice improve them. Agents write observations and candidate copies; audits and reviewers produce evidence; a human or delegated local supervisor approves promotion; promoted changes remain in an observation window with rollback evidence.

Core flow:

```text
Observation -> Candidate -> Audit -> Review -> Promotion -> Observation Window
```

## v2.0 Highlights

- Configurable review seats: default three-agent review remains supported, while manifest-declared policies can define local role assignments, single-agent disclosure, or user-waived review.
- Stronger promotion evidence: value-delta gates, pre-promotion reports, decision history, independent reproduction, rejected alternatives, redacted reporting, and post-promotion safety metadata.
- Release hygiene: stale references removed, bytecode artifacts excluded, hard-coded local personal paths scrubbed, broken release links corrected, and R1 unauthorized content removed rather than retroactively justified.
- Evidence-not-authority evaluator model: external evaluators and peer agents can supply evidence, but they do not gain promotion authority.
- Public-package boundary: runtime candidates, rollback points, private workspace paths, and local chat logs are intentionally excluded from this release folder.

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
```

## Package Contents

- `SKILL.md` is the runtime instruction entrypoint.
- `scripts/` contains candidate, audit, lifecycle, observation, and test helpers.
- `schemas/` contains manifest and observation schemas.
- `references/` contains governance patterns and release procedures.
- `RELEASE-v2.0.md`, `JOINT-AUDIT.md`, `PACKAGE-MANIFEST.json`, and `checksums.sha256` document this local package.

## Release Boundary

This folder is a local release package. It does not include git history, private candidate manifests, rollback snapshots, or any automatic publication step. `publish.sh` is guarded and only publishes if a human runs it with `CONFIRM_PUBLISH=1`.
