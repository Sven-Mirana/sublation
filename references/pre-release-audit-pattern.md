# Pre-Release Audit Pattern — Codex + Hermes Joint Review

When a skill or sublation-managed project is approaching a public release, use this two-phase audit pattern. Validated during the skill-sublation v1.0 release (2026-05-29).

## Phase 1: Codex Primary Audit

Delegate the entire release candidate to Codex for a thorough first-pass audit. Codex should check:

1. **Content integrity** — all referenced files present, no stale references, no internal contradictions
2. **Privacy/security** — grep for personal paths, tokens, sensitive data
3. **Script health** — syntax check, --help output, import errors
4. **Documentation quality** — README clarity, CHANGELOG accuracy, LICENSE validity
5. **Structure** — .gitignore coverage, no junk files
6. **Governance self-consistency** — does the release pass its own standards?

Codex writes findings to `AUDIT-CODEX.md` in the release candidate root. Flag issues honestly — don't sugarcoat.

## Phase 2: Hermes Remediation + Verification

Hermes reads Codex's audit, fixes all HIGH and MEDIUM findings, then independently re-verifies:

- File completeness
- Privacy scan (zero personal paths)
- Bytecode clean (no `__pycache__`, `.pyc`, `.orig`)
- Script syntax (all compile)
- Schema validity (all JSON parse)
- CLI --help (all work)
- Functional smoke tests for each fix (out-of-range values rejected, path traversal blocked, etc.)

## Phase 3: Joint Report

Write `JOINT-AUDIT.md` synthesizing both perspectives:

- Table of all findings with Codex classification, fix applied, verification status
- Hermes verification results (checklist format)
- Any remaining non-blocking notes
- Final verdict: APPROVED or NEEDS WORK

## Pitfalls Learned

- **README examples MUST match actual CLI requirements**: Codex found `observe.py` example missing `--step` and `--evidence`. Always run the exact commands shown in README to verify.
- **`.git/` directory leaks into candidates**: `copytree` with custom ignore must exclude `.git`. Without this, candidate manifests record git metadata hashes, bloating candidates and making baselines drift.
- **Path traversal in CLI tools**: `skill_name` and `candidate_id` from CLI args are used directly in `Path()` joins. Validate before use — reject `..`, `/`, `~`.
- **Input validation gaps**: schema says `0..1` but argparse accepts any float. Add post-parse validation.
- **"22 strict" is misleading**: count the actual checks. audit.py has 10 base + 12 strict = 22 total. Say "22 audit checks (10 base + 12 strict)".
- **Governance claims need disclaimers**: if candidate manifests are internal runtime data, say so explicitly in README. Don't let readers assume they can verify the counts independently.
