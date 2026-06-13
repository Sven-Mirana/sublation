# Business Smoke Test Pattern

After promotion but before closing observation_window, verify the promoted skill still works
in the runtime where the user actually uses it. Audit proves structural validity; smoke tests
prove operational validity.

## The Pattern

```python
checks = [
    ("key capability A", "marker text" in skill_md),
    ("key capability B", all(s in skill_md for s in ["item1", "item2"])),
    ("no regression X", "old_broken_tool" not in skill_md),
    ("workflow intact", all(f"Step {i}" in skill_md for i in range(1,10))),
]
for label, ok in checks:
    print(f"  {'✓' if ok else '✗'} {label}")
print(f"\n{skill_name}: {'PASS' if all(c[1] for c in checks) else 'ISSUES FOUND'}")
```

## What to Check

1. **New contract/feature is present** — e.g. "Generation Backend Contract" or "Provider Contract"
2. **Old workflow is intact** — Step 1..N all still exist
3. **Key capabilities preserved** — art styles, presets, data dimensions
4. **Old tool references removed** — no hardcoded references to replaced tools (e.g. `canghe-image-gen`)
5. **New guidance is actionable** — prompt-only, download, retry instructions are present

## When to Use

- After a cross-skill absorption promotion (canghe←baoyu, npl←npl-monitor)
- After any spec-patch that adds a contract or backend guidance
- Before closing an observation_window for a business-facing skill

## What NOT to Check

- Audit-level structural checks (manifest, schema, pyc) — audit.py handles those
- Full production execution — that's expensive and requires user context
- Darwin-level 9-dim rubric — Darwin is a separate evaluator

## Discovery

This pattern was developed during 2026-05-28 when `canghe-comic` was promoted to Codex's
skill directory instead of Hermes' — revealing that cross-agent path mismatches can silently
succeed at audit but fail at runtime. The smoke test caught it.
