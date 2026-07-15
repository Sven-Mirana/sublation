# SkillSpector Observation Window Gate

This reference records how Sublation uses NVIDIA SkillSpector after promotion.

## Purpose

SkillSpector is a static security evidence layer for the observation window. It helps detect new supply-chain, documentation, file-operation, credential, and tool-misuse risks after a candidate is promoted.

It is not an authority layer. It never replaces value-delta review, old-capability retention, rollback readiness, configured review seats, or user approval.

## Default Command

Use static local mode unless user explicitly approves a different mode:

```bash
skillspector scan <formal-skill-path> --no-llm --format json --output <candidate>/validation/skillspector-<phase>.json
```

Do not use provider credentials, LLM mode, remote repositories, telemetry, broad full-root scans, or baseline suppression by default.

## Baseline Diff

Raw `risk_score`, top-level `severity`, and `recommendation` are context only.

The gate is a baseline diff:

1. When a candidate enters `observation_window`, run SkillSpector on the promoted formal path.
2. Store the raw JSON report and a normalized `baseline_fingerprint`.
3. Before closing the observation window, run the same command with the same SkillSpector version.
4. Compare normalized findings and populate `new_findings_since_baseline`.

If the SkillSpector version changed, do not compare automatically. Re-baseline and ask the configured review seats to decide whether any apparent new finding is a rule-version artifact or a real regression.

## Closure Semantics

Block observation-window closure only when one of these appears since baseline:

- new `[malware]` YARA finding;
- new confirmed HIGH/CRITICAL finding that has not been triaged.

Blocking closure does not mean automatic rollback. It means create a remediation candidate, record accepted risk with controls, or keep the observation window open.

These findings are triage-only by default:

- raw `risk_score` or `DO_NOT_INSTALL` recommendation;
- LOW/MEDIUM findings;
- `[agent_skills]` YARA findings;
- OSV fallback findings;
- `network_reconnaissance`;
- expected governance-tooling findings such as explicit-argument subprocess checks or candidate scaffolding.

## Required Manifest Fields

Record under `validation.post_promotion_safety.skillspector`:

- `status`;
- `tool`;
- `version`;
- `mode`;
- `command`;
- `target_path`;
- `baseline_report_path`;
- `baseline_fingerprint`;
- `baseline_tool_version`;
- `closing_report_path`;
- `current_fingerprint`;
- `risk_score`;
- `severity`;
- `recommendation`;
- `recommendation_gating: false`;
- `severity_histogram`;
- `yara_namespaces`;
- `new_findings_since_baseline`;
- `new_malware_yara_findings`;
- `new_confirmed_high_or_critical_untriaged_findings`;
- `triage`;
- `version_change_policy`;
- `closure_decision`.

## Review Rule

Configured review seats may use SkillSpector evidence to require remediation, but no agent may lower review requirements, close observation windows, promote, rollback, or suppress findings solely because of a scan result.
