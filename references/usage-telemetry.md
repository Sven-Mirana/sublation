# Minimal Usage Telemetry

## Event Contract

New events contain exactly:

- `ts`: UTC second-resolution timestamp;
- `skill`: canonical Skill identifier;
- `session_id`: first 12 hexadecimal characters of a SHA-256 digest of the
  runtime session identifier.

The digest supports distinct-session counts without preserving the source
identifier. No tool input, prompt, transcript, path, file content, result,
case data, credential, or model log is permitted.

## Hook Boundary

The logger is fail-silent so monitoring cannot block normal work. Installing or
changing a PostToolUse hook remains a separate settings mutation and requires
explicit user authorization for that runtime. Copying this candidate does not
activate the hook.

## Reporting Boundary

The report shows calls, distinct-session counts, and first/last timestamps. It
never shows session IDs. A Skill may be called and still fail; telemetry is
therefore supporting observation evidence, not a business-smoke verdict.

Zero-call rows are emitted only when the caller supplies an explicit JSON array
of known Skill IDs. Absence from a partial log is otherwise not treated as
proof of non-use.

## Legacy Compatibility

The report may read the existing three-field `{ts, skill, session}` format for
local aggregation. Records with any extra field are rejected. New writes always
use the governed `session_id` schema.
