# Skill Sublation v4.0.0

Release date: 2026-07-29  
License: MIT

## Summary

V4 makes Skill selection and value evidence easier to review while preserving the central governance rule: automation may improve and validate an isolated candidate, but protected actions remain under user control.

## Included

- All retained V3 candidate, audit, run-ledger, orchestration, approval, rollback, and release-audit components;
- controlled scenario taxonomy and deterministic route-map validation;
- explicit `primary_when`, `not_when`, `clarify_when`, and `handoff_to` contracts;
- opt-in privacy-minimal usage logging and session-free aggregate reporting;
- evidence-tiered value-delta delivery reports;
- schemas and focused tests for the three V4 modules.

## Safety Boundary

- Copying or installing the Skill does not activate telemetry or mutate runtime settings.
- New usage events contain exactly `ts`, `skill`, and a 12-hex SHA-256 session digest.
- Prompts, tool inputs, transcripts, paths, file contents, results, credentials, case data, and model logs are forbidden from usage events.
- Routing maps are advisory and do not call, merge, install, or promote Skills.
- Delivery reports do not turn estimates or qualitative claims into measured results.
- Formal replacement, alias changes, deletion, installation, telemetry activation, publication, provider use, and credential handling require separate user authorization.
- Public packaging excludes private candidates, rollback copies, user paths, internal room logs, and credentials.

## Dependencies

The scripts use the Python standard library only. Core helpers require Python 3.10 or later. Full bounded one-shot orchestration is designed for macOS and fails closed when the required `sandbox-exec` isolation is unavailable. See `DEPENDENCIES.md`.

## Verify

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s scripts -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/release_audit.py \
  --root . \
  --report "${TMPDIR:-/tmp}/skill-sublation-v4-release-audit.json"
shasum -a 256 -c checksums.sha256
```

The package's test receipt and release audit are bounded mechanical evidence. Users must still review their own agent commands, provider policies, writable roots, privacy requirements, and promotion targets before enabling a live workflow.

## Upgrade Notes

V4 keeps the V3 manifest, run, worker, and approval contracts. The new scenario, usage-event, and delivery-report schemas are additive. Existing telemetry remains disabled until explicitly configured by the user.
