# Value-Delta Delivery Report

## Purpose

Turn verified candidate evidence into a short delivery artifact without
collapsing governance state into marketing language.

## Three Evidence Tiers

1. `measured`: mechanically reproducible before/after values with at least one
   labeled SHA-256 evidence anchor.
2. `estimated`: a numeric estimate with an explicit formula, assumptions, unit,
   and evidence anchor.
3. `not_measurable`: a qualitative statement. Numeric keys are forbidden.

Moving a claim between tiers requires changing the structured input and
supplying the stronger evidence. The renderer does not infer or upgrade a tier.

## Trigger Boundary

Generate the report at a batch delivery checkpoint or observation-window
checkpoint. Report creation does not authorize installation, promotion,
publication, observation closure, or any external transmission.

## Manifest Record

The optional `validation.delivery_report` object identifies a generated
artifact by relative path, SHA-256, and generation time. It is an identity
record only. Existing `value_delta`, empirical, review, rollback, and user
decision gates remain authoritative.

## Determinism And Privacy

- The tool adds no current timestamp. `generated_at` appears only when supplied.
- Input and output must not contain formal absolute paths, prompts, conversation
  content, credentials, or private case data.
- The first fixture uses only an existing public-to-this-workspace merge count
  and its content hash.
