# Skill Sublation v3.0.0

Release date: 2026-07-14  
License: MIT

## Summary

V3 turns the Loop Engineering governance protocol into an executable, durable control plane while preserving the central rule: automation may prepare evidence and an exact decision packet, but only the user may authorize formal promotion or other protected actions.

## Included

- Candidate, observation, audit, lifecycle, and strong-path tools retained from V2;
- `loop_engineering.py` for candidate hard gates and decision-packet generation;
- `sublation_one_shot.py` as the explicit-trigger entrypoint;
- `sublation_run.py` for durable run state and evidence binding;
- `sublation_orchestrate.py` for bounded role execution;
- `sublation_receipt.py` for approval receipt validation;
- `sublation_promote.py` for approved-scope promotion and rollback;
- `sublation_local_adapter.py` for ephemeral local adapter configuration;
- run and worker configuration schemas;
- the corresponding unit-test suite and V3 reference contracts.

## Safety Boundary

- No automatic formal skill write, deletion, publication, login, credential handling, PATH change, provider change, launchd change, or cron change;
- Default automation endpoint is `USER_DECISION_REQUIRED`;
- Reviewer PASS is evidence, not approval;
- Candidate revisions are immutable once referenced by evidence;
- Promotion requires exact approved scope, current baseline match, rollback material, and post-write verification;
- Failure restores the prior tree and records the blocked state;
- The public package excludes private candidates, rollback snapshots, credentials, internal chat logs, user-specific absolute paths, and machine-local release history.

## Verify

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_audit.py --root . --report "${TMPDIR:-/tmp}/skill-sublation-v3-release-audit.json"
python3 -m json.tool schemas/manifest-v3.json >/dev/null
python3 -m json.tool schemas/run-v1.json >/dev/null
python3 -m json.tool schemas/worker-config-v1.json >/dev/null
shasum -a 256 -c checksums.sha256
```

`scripts/audit.py --strict` remains the candidate-layer gate and must be run against an actual candidate directory. The release audit above checks the packaged public tree, frontmatter, JSON, links, private path components, bytecode, personal paths, internal room identifiers, and common secret forms.

Run the guarded `publish.sh` only after reviewing this release note, `JOINT-AUDIT.md`, `PACKAGE-MANIFEST.json`, and the final checksums from a prepared Git repository.

## Upgrade Notes

V3 retains V2 governance artifacts. Existing candidate manifests remain valid when they satisfy manifest v3 and the configured review policy. One-shot runs use separate run/worker schemas and do not silently convert or promote existing candidates.
