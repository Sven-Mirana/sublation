# New Skill from External Source

How to create a sublation candidate for a skill that doesn't exist yet in the local `~/.hermes/skills/` directory.

## When to Use

- You find an external skill (GitHub, ClawHub, etc.) that fills a gap in the local skill library
- No local equivalent exists — this is not absorption into an existing target, it's new skill creation
- The external skill has a design system, workflow, or API contract worth preserving

## Workflow

### 1. Observation

Point `observe.py` at the external clone:

```bash
python3 scripts/observe.py <new-skill-name> \
  --skill-path ~/Desktop/<repo>/skills/<external-skill> \
  --session "<session-id>" \
  --classification partial \
  --reflection-type DISCOVERY \
  --step "external evaluation" \
  --status discovery \
  --evidence "<what the external skill has>" \
  --summary "<why it's worth absorbing>" \
  --recommendation create_candidate
```

### 2. Candidate Creation

Use the external clone path as `--source-path`. `candidate.py` will record it in `source_skill.path` — this is intentional and correct:

```bash
python3 scripts/candidate.py create <new-skill-name> \
  --source-path ~/Desktop/<repo>/skills/<external-skill> \
  --candidate-type spec-patch \
  --agent codex \
  --observation <obs-path>
```

The `source_skill.path` will point to the external clone. This means:
- `strict_source_baseline_current` will check against the external clone, not against `~/.hermes/skills/` (which doesn't exist yet)
- The baseline is anchored to the donor's current state

### 3. Manifest Setup

Key differences from a normal candidate:

```json
{
  "source_skill": {
    "path": "/Users/.../Desktop/baoyu-skills/skills/baoyu-diagram",
    "note": "External source — target skill does not exist yet in ~/.hermes/skills/"
  },
  "relationships": {
    "sublation_pattern": "cross_skill_absorption",
    "target_skill": {
      "name": "svg-diagram",
      "path": "~/.hermes/skills/creative/svg-diagram",
      "note": "New skill to be created — currently only exists as candidate"
    },
    "donor_skills": [...]
  },
  "scope": {
    "changes": [
      "Adapt SKILL.md from external conventions to Hermes conventions",
      "Remove external runtime dependencies (Bun, Chrome, npx)",
      "Add Hermes-native tool references"
    ],
    "out_of_scope": [
      "Do NOT copy external source code verbatim",
      "Do NOT modify donor files",
      "Do NOT require external runtime dependencies"
    ]
  }
}
```

### 4. Promotion

Before promotion, the candidate needs special handling:
- `target_path_verified`: confirm the target directory `~/.hermes/skills/<category>/<name>/` will be created
- `source_path_matches_promotion_target`: will be `false` — document in `target_path_note`
- The promotion action creates the target directory if it doesn't exist

### 5. Post-Promotion

After promotion, the target skill exists at `~/.hermes/skills/<category>/<name>/`. The external clone source can be deleted — the skill now stands on its own.

## Pitfalls

- **Don't use this for every external skill.** Only when there's a genuine capability gap and the external design system is worth preserving. Prefer `github-skill-installer` for direct installation.
- **The external clone is temporary.** Don't reference it from the promoted skill's SKILL.md. The candidate RATIONALE.md and EVIDENCE.md record the provenance.
- **Cross-profile awareness**: if the target path includes a specific profile directory, verify it matches the current session's profile.

## Example

Session 2026-06-03: `baoyu-diagram` (9 diagram types, 8-color palette, JetBrains Mono typography) → created `svg-diagram` candidate. No local diagram skill covered flowchart, sequence, timeline, state machine, or mind map types. Target: `~/.hermes/skills/creative/svg-diagram`.
