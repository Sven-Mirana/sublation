# Spec-only merge candidate pattern

Use this when the user asks for a merge candidate but explicitly limits scope to `SKILL.md + manifest` and says to skip scripts, references, runtime integration, or sidecar evidence files.

## Trigger example

- "Create merge candidate for A + B. Spec-patch only: SKILL.md + manifest. Skip scripts. Quick execution."

## Pattern

1. Treat this as a sublation candidate sandbox, not an in-place source skill edit.
2. Inspect source `SKILL.md` files and any local manifest/schema examples just enough to preserve routing, trigger coverage, donor metadata, and provenance.
3. Do not run scaffold commands that generate extra files unless the user accepts those files. If a scaffold is already present, reduce the candidate back to the requested surface.
4. Candidate directory should contain exactly:
   - `SKILL.md`
   - `manifest.json`
5. `manifest.json` should still record:
   - `schema_version: 3`
   - `candidate_type: spec-patch`
   - source/donor skills and paths
   - relationship pattern (`skill_merge_plan` or `cross_skill_absorption` as appropriate)
   - rights/provenance, especially whether expression was copied
   - explicit out-of-scope list: scripts, references, runtime integration, credentials, promotion
6. Treat credentials, tokens, API keys, and source environment details as non-copyable. If referenced, write `[REDACTED]` or omit.
7. Verify the requested narrow scope before reporting completion:
   - parse `manifest.json` as JSON
   - check final tree contains only `SKILL.md` and `manifest.json`
   - check no `scripts/` files exist
   - confirm source skill directories were not modified

## Why this matters

The standard sublation scaffold may create `PATCH.diff`, `RATIONALE.md`, `EVIDENCE.md`, `validation/`, `references/`, and copied runtime files. Those are useful for full candidates, but violate a user request for a quick spec-only merge candidate. For this class of task, final scope verification is more important than producing the full scaffold payload.

## Example outcome

For `huashu-wechat-image + huashu-xhs-image -> huashu-image-gen`, the final candidate was intentionally reduced to two files under:

`~/.hermes/sublation/candidates/huashu-image-gen/<candidate-id>/`

No source skills were changed, and no scripts or references were copied.