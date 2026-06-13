# Empirical Scorecard Gate

## Purpose

The empirical scorecard is a promotion-evidence layer for measurable candidates. It fills the gap between structural audit and business smoke testing:

- audit proves the candidate is well-formed and governance-safe;
- smoke testing proves the skill still runs or degrades acceptably;
- empirical scorecard records whether a measurable change improved against a baseline.

This is not an optimizer. It does not select, mutate, rank, clip, or promote candidates.

## Manifest Location

Use `validation.empirical_scorecard`.

Measured example:

```json
{
  "status": "measured",
  "metric_name": "fixture_pass_rate",
  "baseline_score": 0.67,
  "candidate_score": 1.0,
  "higher_is_better": true,
  "fixture_or_dataset": "validation/fixtures/status-output-cases",
  "evaluator": "pytest fixture assertions",
  "regression_checks": [
    "legacy empty result still reported as empty",
    "blocked source is not reported as clean zero results"
  ],
  "decision": "improved",
  "notes": "Score is evidence for review, not automatic promotion authority."
}
```

Not applicable example:

```json
{
  "status": "not_applicable",
  "not_applicable_reason": "Pure governance-boundary change; no single fixture score can represent the legal/approval risk reduction.",
  "decision": "not_applicable"
}
```

Not measured example:

```json
{
  "status": "not_measured",
  "not_measured_reason": "Candidate is still in design review; measurable fixture not yet available.",
  "decision": "deferred"
}
```

## Review Rule

Use the gate only when the candidate has a meaningful measurable target: parsing accuracy, fixture pass rate, output schema compliance, report completeness, latency, token reduction, retrieval coverage, or similar.

For qualitative legal reasoning, policy boundaries, authorship style, or user-trust changes, mark `not_applicable` and explain why. Do not invent false precision.

## Blocking Conditions

- `status: measured` is missing baseline/candidate scores, metric, fixture/dataset, evaluator, regression checks, or decision.
- scores are non-numeric.
- `decision` is `regressed` or `blocked`.
- `status: not_applicable` has no reason.
- `status: not_measured` has no reason.

`not_measured` after approval or promotion is a warning requiring explicit human review, not an automatic fail. This preserves the maintenance-mode rule: real workflow evidence should guide new gates, but governance stays human-led.
