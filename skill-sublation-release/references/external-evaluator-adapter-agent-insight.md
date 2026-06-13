# External Evaluator Adapter: Agent-Insight

Agent-Insight (`openEuler/witty-skill-insight`) may be used by sublation only as
a read-only external evaluator. It is not a promoter, not a mutator, and not an
independent optimizer inside the sublation lifecycle.

## Allowed Path

```text
candidate copy
  -> temporary import directory
  -> Agent-Insight official automation/import API
  -> native static evaluation with enableL2:false
  -> external_evaluations[] evidence
  -> empirical_scorecard when measurable
  -> Hermes/Codex review
  -> user approval gate
```

## Prohibited Path

```text
formal skill directory
  -> skill-optimizer / DiagnosticMutator
  -> iterative-optimizer
  -> skill-sync pull
  -> load_skill
  -> automatic promotion
```

This prohibited path bypasses sublation's candidate layer, rollback record,
cross-review, and user approval gate.

## Boundary Rules

- Input must be a candidate copy, fixture, or temporary directory derived from a candidate.
- Formal skill paths under `~/.hermes/skills`, `~/.codex/skills`, or `~/.agents/skills` are invalid input.
- Native static evaluation defaults to `enableL2:false`.
- L2/LLM evaluation requires a separate user-approved candidate and must still be read-only.
- Agent-Insight output must be recorded as evidence, never as authority.
- Report paths should live under the candidate `validation/` directory or the project coordination report directory.
- Any optimizer, mutator, sync, or loader capability is out of scope.

## Native API Contract

Import:

```http
POST /skill-insight/api/skills/automation/import
Content-Type: application/json

{
  "path": "/private/tmp/witty-import/<candidate-copy>",
  "user": "codex@subation.dev"
}
```

Evaluate:

```http
POST /skill-insight/api/skills/<skill-id>/versions/<version>/evaluate
Content-Type: application/json

{
  "user": "codex@subation.dev",
  "enableL2": false
}
```

Summary:

```http
GET /skill-insight/api/skills/<skill-id>/versions/<version>/evaluation-summary?user=codex@subation.dev
```

Detail:

```http
GET /skill-insight/api/evaluation/<evaluation-id>
```

## Evidence Mapping

Record these fields when native evaluation succeeds:

- `evaluator`: `agent-insight`
- `target`: `candidate`
- `mode`: `read_only_scorecard`
- `formal_skill_modified`: `false`
- `enable_l2`: `false`
- `skill_id`
- `version`
- `evaluation_id`
- `content_hash`
- `issues_count`
- `severity_histogram`
- `report_path`
- `notes`: score/report is evidence, not promotion authority

## First Verified Run

2026-06-03 native L1 run:

| Field | Value |
|---|---|
| Candidate | `piclist-upload/20260602-dry-run-offline-codex` |
| Temporary input | `/private/tmp/witty-piclist-clean-import-20260603/piclist-upload-codex-native-20260603` |
| Agent-Insight skill id | `cmpxpsdqz000113zc7nbbfxus` |
| Version | `0` |
| Evaluation id | `cmpxpsq1p000513zcivc3ylqm` |
| Generator | `static-evaluator@0.1` |
| Status | `ok` |
| Issues | `0` |
| Severity | `high=0, medium=0, low=0` |
| L2 | disabled |
| Formal skill modified | false |

Canonical report:

`coordination/tri-party-room/agent-insight-piclist-native-static-20260603.md`

## Lessons

- Direct SQLite insertion is unsafe as a standard path. It produced a broken
  `SkillVersion.content` value during the first manual attempt and caused Prisma
  to reject the row as non-string content.
- The correct API path includes the `/skill-insight` prefix.
- A sublation `audit.py` report is useful baseline evidence but is not native
  Agent-Insight evidence.
- Native evaluation can pass without L2/LLM scoring and is enough for the first
  read-only adapter milestone.
