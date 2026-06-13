# TencentDB Agent Memory Setup

## What it is

TencentDB Agent Memory replaces Hermes' flat MEMORY.md with a four-layer pyramid:
- L0: Conversation store (SQLite + JSONL) — raw dialogue
- L1: Episodic extraction (LLM + vector dedup) — atomic facts
- L2: Scene blocks (Markdown) — contextual patterns  
- L3: Persona synthesis (persona.md) — user identity

## Performance

- Token reduction: 30-61% (vs flat injection)
- Task success: +7-51% (relative, per benchmark)
- Long-term recall: 48% → 76% (PersonaMem)

## Installation

```bash
# Prerequisites: Node.js >= 22 (user has v24.14.1)
npm install -g @tencentdb-agent-memory/memory-tencentdb@latest

# Run auto-installer
bash scripts/install_hermes_memory_tencentdb.sh

# Config switch
memory:
  provider: memory_tencentdb
  memory_char_limit: 50000
  user_char_limit: 10000

# Restart Hermes to activate
```

## Architecture

```
Hermes Agent → MemoryTencentdbProvider (Python HTTP client)
  └─ GatewaySupervisor (auto-start Node.js sidecar)
       └─ memory-tencentdb Gateway (Node.js :8420)
            └─ SQLite local storage
```

## Health check

`curl http://127.0.0.1:8420/health`

## Migration from old memory

Use `scripts/migrate-sqlite-to-tcvdb/` to transfer existing MEMORY.md content.

## Pitfalls

- Requires Hermes restart (`/reset` or new session) after config change
- Node.js gateway auto-starts via supervisor; if port 8420 is occupied, check process
- First session after switch: old MEMORY.md is NOT auto-migrated; run migration script
