# Darwin Evaluator Adapter

Darwin is useful to skill-sublation as an evaluator, not as an autonomous promoter.

## Role

Darwin may produce:

- 9-dimension scorecards for a candidate `SKILL.md`;
- 2-3 representative test prompts;
- read-only quality findings;
- proposal-only rewrite suggestions;
- a result card or score report under `validation/`.

Darwin must not:

- edit active formal skill directories;
- mark candidates as approved, promoted, closed, or rejected;
- overwrite sublation rollback records;
- copy donor skill source files into a target without rights/provenance metadata;
- treat its score as a replacement for audit, Hermes/Codex review, or user approval.

## Required Manifest Fields

When Darwin is used, add an entry like:

```json
{
  "external_evaluations": [
    {
      "evaluator": "darwin-skill",
      "target": "candidate",
      "mode": "read_only_scorecard",
      "report_path": "validation/darwin-scorecard.json",
      "formal_skill_modified": false,
      "notes": "Reference evidence only."
    }
  ]
}
```

Allowed Darwin modes:

| Mode | Meaning |
|---|---|
| `read_only_scorecard` | Darwin reads the candidate and writes a score report. |
| `proposal_only` | Darwin writes suggested changes, but another agent applies any accepted edits in the candidate layer. |
| `dry_run` | Darwin simulates evaluation when test execution is unavailable. |

## Rights And Provenance

For cross-skill absorption, record what was absorbed and whether protected expression was copied:

```json
{
  "rights_provenance": {
    "policy": "Absorb capability patterns; do not copy protected expression without review.",
    "donor_rights": [
      {
        "skill_name": "darwin-skill",
        "path": "~/.hermes/skills/hermes-agent/darwin-skill",
        "license": "README claims MIT; installed copy has no LICENSE file.",
        "provenance": "Hermes-installed local skill reviewed on 2026-05-28.",
        "absorbed_material": "Evaluator role, scorecard concept, test-prompt validation concept.",
        "expression_copied": false,
        "permission_basis": "Adapter documents an interface and governance boundary; no Darwin source files copied.",
        "notes": "Darwin reports are reference evidence only."
      }
    ]
  }
}
```

`expression_copied: true` is not forbidden, but it must trigger human review of license/permission before promotion.
