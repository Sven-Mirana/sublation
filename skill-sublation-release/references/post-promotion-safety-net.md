# Post-Promotion Safety Net

This reference defines the minimum safety checks after a candidate is promoted.

## Why

Audit can prove that a candidate is structurally valid. It cannot prove the promoted skill still works in the user's real runtime. The post-promotion safety net catches:

- patches applied to the wrong skill copy or runtime profile;
- missing rollback evidence;
- skills that pass specification audit but fail real workflows;
- new provider/backend contracts that block instead of falling back;
- observation windows closed without closure evidence.

## Required Evidence

Add this under `validation.post_promotion_safety` after promotion:

```json
{
  "rollback_ready": true,
  "rollback_point": "~/.hermes/sublation/rollback-points/...",
  "target_path_verified": true,
  "source_path_matches_promotion_target": false,
  "target_path_note": "Candidate was created from Codex copy and synced to Hermes production copy.",
  "business_smoke_test": {
    "status": "passed",
    "evidence": [
      "Hermes business validation report: workflow complete and key capabilities retained."
    ]
  },
  "fallback_verified": true,
  "old_capability_retained": true
}
```

## Closure Rule

Do not close `observation_window` unless:

- rollback is ready;
- target path is verified;
- smoke test has passed or is explicitly not required;
- fallback behavior is verified when the change touches external services, data providers, generation backends, cron, or MCP;
- key old capabilities are retained.

Use `lifecycle.py close-observation`; do not manually set `status: closed`.
