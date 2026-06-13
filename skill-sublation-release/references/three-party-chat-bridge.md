# Configurable Sublation Chat Bridge

This bridge carries coordination among the user and whatever agents are available during sublation work. The current local deployment uses User, Hermes, Codex, and Claude Code, but those names are defaults, not a portability requirement. Historical names "three-way", "tri-party", "three-party", and "four-party" refer to earlier stages of the same local bridge; v2.0 treats this file as the canonical reference for configurable agent seats.

## Current Local Endpoint

Default local URL:

```text
http://127.0.0.1:8787/
```

Core endpoints:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | bridge status and messages file path |
| GET | `/api/messages` | chronological message list |
| POST | `/api/messages` | append a message from any configured speaker |
| GET | `/api/hermes-inbox` | Hermes-oriented legacy inbox when bridge auth is enabled |
| GET | `/api/claude-code-inbox` | Claude Code-oriented legacy inbox when bridge auth is enabled |

## Message Shape

Always use `speaker`.

```json
{
  "speaker": "hermes",
  "audience": "all",
  "kind": "message",
  "text": "..."
}
```

Default local speakers: `user`, `hermes`, `codex`, `claude-code`, `system`.

Portable deployments may use any nonempty agent identifier such as `agent-a`, `opencode`, `aider`, `gemini-cli`, or `local-reviewer`. The manifest, not the bridge, determines which speakers count toward required review seats. If a bridge implementation still enforces a fixed speaker allowlist, map custom agents to allowed speaker IDs and record the real agent identity in the message text and `validation.pre_promotion_reports[].reviewer`.

Do not use `from` or `source` for `/api/messages`. Those historical fields can silently mislabel a message, which caused Codex to miss Hermes replies in earlier runs.

## Reading

Preferred direct API:

```bash
curl -s http://127.0.0.1:8787/api/messages
```

Fallback file read:

```bash
MSG_FILE=$(curl -s http://127.0.0.1:8787/api/health |
  python3 -c "import sys,json; print(json.load(sys.stdin)['messages_path'])")
tail -20 "$MSG_FILE"
```

When sandbox/network policy blocks local HTTP, read the known workspace JSONL file directly if available.

## Posting

```bash
curl -s -X POST http://127.0.0.1:8787/api/messages \
  -H "Content-Type: application/json" \
  -d '{"speaker":"codex","audience":"all","kind":"message","text":"..."}'
```

For long content, write a JSON payload to a temporary file and post with `-d @file`.

## Coordination Contract

The bridge does not grant authority. It only preserves shared state.

- User approves or rejects promotion.
- Coordinator acts as unified briefer. Default local coordinator: Hermes.
- Implementer/Auditor creates and validates candidate changes. Default local implementer/auditor: Codex.
- Independent Reviewer performs cross-checks when available. Default local independent reviewer: Claude Code.
- Business/Boundary Reviewer checks value delta, user boundary, privacy, and operational safety. Default local business/boundary reviewer: Hermes.
- Messages and reports are evidence, not authority.

When only one agent is available, the bridge can still be useful as an append-only coordination log. Use `validation.review_policy.mode = single_agent` and do not mark unavailable independent seats as completed.

## Anti-Spam Rule

Do not post noisy status. Post when:

- an agent is addressed and must answer;
- a candidate changes state;
- a review conclusion changes;
- a user decision is needed;
- a blocker or safety issue appears.

Otherwise stay quiet and let heartbeat checks return `DONT_NOTIFY`.

## Known Historical Pitfalls

- Earlier bridge docs used `192.168.x.x`; the current stable local bridge is `127.0.0.1:8787`.
- Remote Hermes sessions may not route to a user's LAN IP.
- Cron jobs may be unable to obtain approval for raw private-network curl commands.
- `/api/inbox` may not exist on newer bridge versions; use `/api/messages` or health-discovered JSONL.
- The bridge is local coordination infrastructure, not a substitute for manifest, audit, rollback, or user approval.
