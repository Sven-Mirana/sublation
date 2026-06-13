# External Skill Evaluation Pattern

## User rule (2026.6.1)

When user drops a GitHub link:

1. **Clone** — shallow clone, no submodules
2. **Read** — README + structure + key files
3. **Assess** — value for user's domains (法律/鉴股)
4. **Install or skip** — useful → install immediately; not useful → explain why and skip
5. **Do NOT suggest sublation** — user triggers sublation themselves. Agent does not initiate absorption analysis unless user says "这个能不能吸收" or similar explicit trigger.

## Evaluation dimensions

| Question | Signal |
|----------|--------|
| Does it overlap with existing tools? | Check installed skills first |
| Does it fill a gap in user's workflow? | Legal or investing domain |
| Is it installable? | Check deps, license, platform |
| License compatible? | MIT/Apache 2.0 ✅, CC BY-NC-ND ⚠️ (install OK, no absorption), GPL/AGPL ⚠️ |
| Install complexity? | pip install → go ahead. Complex setup → flag it |

## Common verdicts

- "不装。功能覆盖了" — existing tools cover it
- "装。互补不重叠" — fills a gap
- "不装。不匹配" — irrelevant to user's domains
- "装。100% overlap → flag for sublation" — only when user explicitly asks for absorption

## Session examples

- crawl4ai ✅ — fills gap (no crawler), installed
- liteparse ❌ — docling already covers it
- graphify ✅ — complementary (HTML visualization), installed  
- Anthropic Cybersecurity ❌ — irrelevant (security operations)
- Legal-Skills-Chinese ✅ — high value, CC BY-NC-ND (install only, no absorption)
- TencentDB Agent Memory ✅ — solves memory overflow, Hermes native plugin
- book-to-skill ✅ — converts books into structured skills, complementary
