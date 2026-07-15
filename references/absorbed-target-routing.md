# Absorbed Target Routing

When the natural sublation target has been absorbed into another skill, route to the umbrella — don't revive the leaf.

## Problem

You identify a donor skill (e.g., `baoyu-url-to-markdown`) with capabilities missing from the local equivalent. You check `~/.hermes/skills/` and find `canghe-url-to-markdown` — looks like the target. But the last line reads:

```markdown
**absorbed_into**: `universal-converter` (2026-05-28)
```

## Detection

```bash
# Check if SKILL.md ends with absorbed_into
tail -3 ~/.hermes/skills/<category>/<skill>/SKILL.md | grep absorbed_into
```

## Action

1. **Do NOT revive the leaf skill.** It was absorbed intentionally as part of merge-driven sublation.
2. **Read the umbrella SKILL.md** to confirm it covers the function domain.
3. **Scope the candidate to the umbrella's sub-pipeline.** E.g., `universal-converter` has three stages (URL→MD, format, MD→HTML); the baoyu adapter absorption only touches the URL→MD stage (`scripts/url-to-markdown/`).
4. **In the manifest**, target the umbrella, not the leaf:

```json
"relationships": {
  "sublation_pattern": "cross_skill_absorption",
  "target_skill": {
    "name": "universal-converter",
    "path": "~/.hermes/skills/productivity/universal-converter"
  }
}
```

5. **In out_of_scope**, explicitly state: "Do NOT modify other pipeline stages (format-markdown/, markdown-to-html/)"

## Example

Session 2026-06-03: `baoyu-url-to-markdown` → detected `canghe-url-to-markdown` has `absorbed_into: universal-converter`. Routed to `universal-converter`, scoped candidate to `scripts/url-to-markdown/` only.
