# GitHub Release Workflow — Sublation-Governed Skills

End-to-end workflow for publishing a sublation-governed skill as a standalone GitHub repo.  
Proven on `skill-sublation` itself (2026-05-29, v1.0 release).

## Pre-release Checklist

### 1. Sanitize the repo

```bash
# Remove bytecode artifacts
find . -name '__pycache__' -type d -exec rm -rf {} +
find . -name '*.pyc' -delete
find . -name '*.orig' -delete
find . -name '*.bak' -delete

# Replace hardcoded personal paths with ~
grep -rn '/Users/' . --include='*.md' --include='*.py' --include='*.json'
# Replace matches with ~/ or $SKILL_ROOT

# Check references for personal data (case names, client info, etc.)
grep -rn '案件\|client\|customer\|secret' references/  # adjust per domain
```

### 2. Verify governance trail

```bash
# Health scan
python3 scripts/lifecycle.py health --warn-after-days 7

# All candidates closed?
python3 scripts/lifecycle.py scan --state all | grep -v closed

# Any unledgered formal drift? (content in SKILL.md with no candidate manifest)
# → If yes: create backfill candidate, mark retroactive_backfill, close immediately
```

### 3. Backfill unledgered content (if any)

If formal SKILL.md or references contain content added outside the candidate pipeline:

```bash
# Create backfill candidate
mkdir -p candidates/<skill>/<candidate-id>
# Write manifest.json with:
#   "retroactive_backfill": true
#   "validation.status": "closed"
#   "closure_reason": "backfill — content validated in production"
# Run audit, expect 'conditional' (not 'passed') — WARNING on formal_post_promotion drift is normal
```

### 4. Joint audit (Codex + Hermes)

- **Codex**: thorough code-level audit (script syntax, privacy scan, path traversal, input validation, .git leakage, schema compliance, smoke tests)
- **Hermes**: verify all findings, apply fixes, re-audit, write joint report
- Write `JOINT-AUDIT.md` in repo root with: findings table, resolution status, verification results

### 5. Prepare repo structure

```
skill-name/
├── README.md          ← explain what, why, quick start
├── CHANGELOG.md       ← derived from candidate manifests
├── LICENSE            ← MIT recommended
├── .gitignore         ← __pycache__/, *.pyc, .DS_Store, candidates/, rollback-points/
├── RELEASE-v1.0.md    ← release report with governance trail + capability matrix
├── SKILL.md           ← the governance framework doc itself
├── scripts/           ← observe.py, candidate.py, audit.py, lifecycle.py
├── schemas/           ← JSON schemas
└── references/        ← design docs, experiments, patterns
```

Exclude from public repo: `candidates/`, `rollback-points/`, `skill-observations/` (runtime data with environment-specific paths).

### 6. Publish to GitHub

```bash
cd /path/to/release-candidate
git init && git add -A && git commit -m "v1.0 release"
git remote add origin https://github.com/<user>/<repo>.git
git push -u origin main
```

**Auth troubleshooting** (macOS):
- `gh auth login` needs to be run in a real terminal, not from agent session (keychain access issue)
- `git credential.helper osxkeychain` → requires GitHub Desktop to be running with logged-in account
- Fallback: GitHub PAT (Settings → Developer settings → Tokens (classic) → repo scope) → use with curl API
- If repo creation via API returns "name already exists", the user created it via web — just push

## Pitfalls

- **gh CLI from agent session**: `gh auth login --web` device flow times out because the agent can't interact with the browser. Have the user run `gh auth login` in their own terminal, or use a PAT.
- **candidate.py copies .git/**: before publishing, ensure `should_ignore()` and `collect_hashes()` exclude `.git/` to prevent bloated candidates and metadata leakage.
- **README examples must be valid**: test every command in README Quick Start against actual script argument requirements. Missing required args (`--step`, `--evidence`) is a release blocker.
- **"22 strict audit checks" wording**: the actual count is 10 base + 12 strict = 22 total. Say "22 audit checks (10 base + 12 strict)" to be accurate.
- **Governance claims in public repo**: if candidates/runtime data are excluded, explicitly note in README that the full governance trail is internal. Don't claim 14 candidates are verifiable from the public repo alone.
