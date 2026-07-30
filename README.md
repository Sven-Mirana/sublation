> **GitHub 发布状态**：作者已于 2026-07-29 授权本仓库公开发布。包内较早的“本地交付/未授权上传”字段属于封册历史；以 `PUBLICATION.json` 为当前仓库外发状态。GEO 激活、自动安装及法院提交仍不在本次授权范围内。

# Skill Sublation

Skill Sublation is a local governance framework for improving AI-agent Skills without silently rewriting the active versions.

Version: v4.0.0  
Release date: 2026-07-29  
License: MIT  
Repository: https://github.com/Sven-Mirana/sublation

## What It Does

The framework turns execution experience into a reviewable chain:

```text
Observation -> Candidate -> Validation -> Independent Review
-> User Decision -> Promotion -> Observation Window -> Closure
```

Candidate-layer automation may gather evidence, run tests, create a new revision, and prepare a decision packet. Installation, formal replacement, alias changes, deletion, telemetry activation, and publication remain user-controlled actions.

## V4 Highlights

- Scenario taxonomy and routing boundaries make positive, negative, ambiguous, and handoff conditions reviewable.
- Privacy-minimal usage telemetry can aggregate calls and distinct sessions without storing prompts, tool input, file content, or source session identifiers.
- Value-delta delivery reports separate measured facts, estimates, and qualitative claims.
- The one-shot Loop Engineering path retains durable evidence hashes, independent roles, immutable revisions, approval receipts, rollback material, and fail-closed promotion.
- The full package test suite covers the retained V3 control plane and the new V4 modules.

## Quick Start

```bash
python3 scripts/observe.py <skill-name> \
  --skill-path <formal-skill-path> \
  --session <session-id> \
  --classification defect \
  --reflection-type SKILL_DEFECT \
  --step "script execution" \
  --evidence "observed behavior" \
  --summary "What should improve"

python3 scripts/candidate.py create <skill-name> \
  --source-path <formal-skill-path> \
  --candidate-type spec-patch \
  --agent <builder-id>

PYTHONDONTWRITEBYTECODE=1 python3 scripts/audit.py <candidate-dir> --strict
PYTHONDONTWRITEBYTECODE=1 python3 scripts/sublation_one_shot.py --help
PYTHONDONTWRITEBYTECODE=1 python3 scripts/scenario_map.py --help
PYTHONDONTWRITEBYTECODE=1 python3 scripts/usage_report.py --help
PYTHONDONTWRITEBYTECODE=1 python3 scripts/delivery_report.py --help
```

## Package Contents

- `SKILL.md`: runtime instruction entrypoint.
- `scripts/`: candidate, audit, one-shot orchestration, approval, rollback, routing, telemetry, report, release-audit, and test helpers.
- `schemas/`: candidate, run, worker, scenario, usage-event, and delivery-report schemas.
- `references/`: governance contracts and operating patterns.
- `DEPENDENCIES.md`: runtime and platform requirements.
- `PRIVACY.md`: data fields, defaults, and authorization boundaries.
- `RELEASE-v4.0.md`, `PACKAGE-MANIFEST.json`, and `checksums.sha256`: release evidence.

## Verify

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s scripts -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/release_audit.py \
  --root . \
  --report "${TMPDIR:-/tmp}/skill-sublation-v4-release-audit.json"
shasum -a 256 -c checksums.sha256
```

## Release Boundary

This directory is a public-package snapshot. It excludes private candidates, rollback copies, credentials, internal room logs, user-specific paths, and automatic publication. The optional `publish.sh` is guarded and performs no Git or GitHub write unless a human deliberately runs it with `CONFIRM_PUBLISH=1` in a prepared repository.
