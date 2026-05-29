# Joint Audit Report — skill-sublation v1.0 Release Candidate

**Auditors**: Codex (primary audit) + Hermes (verification & remediation)
**Date**: 2026-05-29
**Target**: `<release-root>/`
**Verdict**: ✅ APPROVED for release

---

## Audit Process

1. **Codex** performed a thorough pre-release audit covering: content integrity, privacy/security, script health, documentation quality, structure, and governance self-consistency.
2. **Hermes** verified all findings, applied fixes, re-audited, and confirmed resolution.
3. This report synthesizes both perspectives.

---

## Findings & Resolution

### HIGH (3) — All Resolved

| # | Finding | Codex | Fix | Verified |
|---|---------|-------|-----|----------|
| 1 | README Quick Start `observe.py` example missing `--step` and `--evidence` | BLOCKER | Added required args to example | ✅ |
| 2 | `candidate.py` copies `.git/` into candidates and hashes git metadata | BLOCKER | Added `.git` to `should_ignore()` and `collect_hashes()` | ✅ |
| 3 | `candidate.py` allows path traversal via `skill_name`/`candidate_id` | BLOCKER | Added validation rejecting `..`, `/`, `~` | ✅ |

### MEDIUM (2) — All Resolved

| # | Finding | Codex | Fix | Verified |
|---|---------|-------|-----|----------|
| 4 | `observe.py` accepts `confidence`/`trace_completeness` outside 0..1 range | SHOULD FIX | Added range validation after `parse_args()` | ✅ |
| 5 | "14 candidate manifests" claim not independently reproducible from public repo | SHOULD FIX | Added explicit disclaimer: "candidate runtime data, not included in public repo" | ✅ |

### LOW (1) — Resolved

| # | Finding | Codex | Fix | Verified |
|---|---------|-------|-----|----------|
| 6 | "22 strict audit checks" overstated (actually 10 base + 12 strict) | NIT | Reworded to "22 audit checks (10 base + 12 strict)" in README + RELEASE | ✅ |

### Additional (1) — Found by Hermes

| # | Finding | Fix | Verified |
|---|---------|-----|----------|
| 7 | `github-release-checklist.md` used `/Users/<name>` as example — confusing for non-macOS users | Changed to generic `~/<username>` or `C:\Users\<name>` | ✅ |

---

## Hermes Verification Results

```
✅ File completeness     — all 12 required files present
✅ Privacy scan          — zero personal paths or sensitive data
✅ Bytecode clean        — no __pycache__, .pyc, .orig artifacts
✅ Script syntax         — all 4 scripts compile (observe, candidate, audit, lifecycle)
✅ Schema validity       — both JSON schemas parse correctly
✅ CLI --help            — all 4 scripts produce valid help output
✅ Git initialized       — 2 commits on main branch
```

**Functional smoke tests passed:**
- `confidence=1.5` → correctly rejected (exit 2)
- `trace_completeness=-0.1` → correctly rejected (exit 2)
- `confidence=0.9` → accepted, observation written
- `skill_name="../escape"` → correctly rejected (exit 1)
- `skill_name="/etc/passwd"` → correctly rejected (exit 1)
- `skill_name="~/.ssh"` → correctly rejected (exit 1)

---

## Remaining Notes (Non-blocking)

1. **Governance trail**: The 14 candidate manifests and 23 total records are internal runtime data. CHANGELOG.md provides a complete text summary. This is by design — candidates contain environment-specific paths and are not intended for public distribution.

2. **Internal-only candidates in references**: 3 NPL monitor experiment files and 1 observation file reference specific internal cron runs. These are documented as historical examples with the pattern clearly explained. Acceptable for v1.0.

3. **`delegation-data-isolation-incident-20260527.md`**: References a specific incident date. This is a design pattern document, not an incident report with personal data. Acceptable.

---

## Joint Verdict

Both Codex and Hermes agree: **the release candidate is ready to publish.**

All HIGH findings have been resolved and verified. MEDIUM findings have been addressed with explicit disclaimers. LOW finding corrected. No remaining blockers.

Release as `Sven/skill-sublation` v1.0.
