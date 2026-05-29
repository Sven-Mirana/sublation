# Skill Sublation (技能扬弃)

A structured governance framework for AI agent skills — observe, candidate, audit, review, promote, and observe again.

## What is Sublation?

Sublation (Aufhebung / 扬弃) is a governance pipeline that turns agent execution experience into auditable skill improvements, without letting agents freely edit production skills.

```
Observation → Candidate → Audit → Review → Promotion → Observation Window
```

**Core principles:**
- **Formal skills are read-only** — agents cannot modify active skills directly
- **All changes go through candidates** — sandboxed copies with full audit trail
- **Promotion requires review** — cross-agent review + user approval before merging
- **Post-promotion safety net** — rollback, path verification, smoke test, fallback check

## Quick Start

```bash
# Create an observation from a skill execution failure
python3 scripts/observe.py <skill-name> \
  --skill-path ~/.hermes/skills/<category>/<skill-name> \
  --session <session-id> \
  --classification defect \
  --reflection-type SKILL_DEFECT \
  --step "script execution" \
  --evidence "error message or observed behavior" \
  --summary "What went wrong"

# Create a candidate from the observation
python3 scripts/candidate.py create <skill-name> \
  --source-path ~/.hermes/skills/<category>/<skill-name> \
  --candidate-type spec-patch \
  --agent hermes

# Audit the candidate
python3 scripts/audit.py ~/.hermes/sublation/candidates/<skill>/<candidate-id>

# Check system health
python3 scripts/lifecycle.py health --warn-after-days 7
```

## Key Numbers

- **22 audit checks** (10 base + 12 strict) with `passed | conditional | failed` resolution
- **Closed self-governance trail** across runtime, lifecycle, audit, cross-skill, release, and hardening candidates
- **Production sample candidates closed** across NPL, Canghe, legal, GBrain, and briefing skills
- **32→11 skill consolidation** via merge-driven sublation (-66%)
- **4 candidate types**: spec-patch, script-enhance, infra-fix, tooling
- **3 promotion modes**: human_patch, user_delegated_agent_patch, rollback

## Capabilities

| Capability | Description |
|---|---|
| Lifecycle Management | 9-state lifecycle (active→closed) with health scanning |
| Cross-Skill Absorption | Donor→target absorption without donor modification |
| Merge-Driven Sublation | Multi-skill consolidation with review checklist |
| Darwin Evaluator Adapter | External evaluator integration (read-only, proposal-only) |
| Post-Promotion Safety Net | Rollback, path verification, smoke test, fallback check |
| Observation Window Policy | Mandatory production observation before closure |
| Legacy Migration | Plan-based migration from v2 manifests to v3 |
| Rights & Provenance | License tracking, expression copying audit |

## Governance Trail

Candidate manifests are internal runtime data and are not included in the public repo. See [CHANGELOG.md](CHANGELOG.md) for the version evolution timeline and [RELEASE-v1.0.md](RELEASE-v1.0.md) for the v1.0 release report.

## Status

**v1.0 — Maintenance Mode.** The framework is complete. Future changes only from real skill practice exposing cracks — no feature development for its own sake.

## License

MIT
