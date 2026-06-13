# Value-Delta Gate

Sublation only happens when there is something real to sublate. A candidate that cannot show a positive delta should remain an observation, not become a promotion.

## Required Judgment

Before promotion, every new candidate should answer five questions:

1. What capability, scope, reliability, clarity, safety, maintainability, or governance quality improves?
2. Which old capability could regress?
3. Is the old workflow retained, aliased, split cleanly, or intentionally retired?
4. What fallback, downgrade, or rollback path exists if the new path fails?
5. What must the observation window prove before closure?

## Manifest Field

Use `validation.value_delta`:

```json
{
  "status": "positive_delta",
  "positive_delta_categories": ["governance_quality", "safety"],
  "summary": "The candidate blocks promotions that cannot prove they improve or preserve the original skill.",
  "evidence": ["strict audit checks validation.value_delta before promotion"],
  "regression_risks": ["Over-strict gate could slow purely clerical fixes"],
  "old_capability_retained": true,
  "capability_reduction": false,
  "fallback_or_rollback": "Use rollback point or keep candidate in observation without promotion.",
  "observation_acceptance": "Promotion closes only after audit and at least one candidate uses the gate without blocking valid work.",
  "user_approval_note": "Required only when backward_compat:false or capability_reduction:true."
}
```

## Blocking Rules

- `unproven` or `regressed` cannot be promoted.
- Missing value delta on new promoted candidates is a strict audit failure.
- `old_capability_retained: false` blocks promotion unless the user explicitly approves the loss and rollback/fallback is recorded.
- `backward_compat: false` or `capability_reduction: true` requires a concrete user approval note.

## Principle

退化不叫扬弃。Candidate isolation and observation windows exist to catch regressions before users inherit them.
