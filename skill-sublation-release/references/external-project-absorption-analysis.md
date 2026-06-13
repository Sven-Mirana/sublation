# External Project Absorption Analysis

How to evaluate an external open-source project for absorption into Sublation — without scope creep, without copying code, without abandoning governance discipline.

## When to Evaluate

User points to a GitHub repo and says "看看有没有能被 sublation 扬弃的东西" or similar.

Evaluation targets: **sublation framework itself**, not individual business skills. If the project is about creating/optimizing skills but not about governing them, the analysis must still answer "does this fill a governance gap?"

## Three-Question Gate

Before reading any code:

1. **Does this project solve a problem that sublation currently cannot solve?** If the answer is "Sublation already covers this" or "this is outside sublation's domain (governance)," stop. No candidate.

2. **If yes, is the gap a real governance crack exposed by practice, or just a "nice to have"?** Sublation v1.0 maintenance mode only admits changes driven by real skill practice exposing cracks. "This looks cool" is not a trigger.

3. **If a real gap, what is the minimum viable absorption?** Never absorb the whole project. Pick the smallest contract/pattern that fills the gap.

## Analysis Steps

### Step 1: Surface Read

Clone --depth 1. Read README, top-level structure, key source files. Answer:
- What does it do? (one sentence)
- How does it do it? (pipeline/steps)
- What's the novel idea?

### Step 2: Gap Map

Overlay on sublation's current capabilities:
- What sublation already does that overlaps → no need to absorb
- What sublation cannot do that this project can → potential absorption
- What this project does that sublation should NEVER do → boundary marker

### Step 3: Absorption Scoping

For each potential absorption:
- **Absorbed category**: `interface_contract` (preferred) | `workflow_pattern` | `runtime_adapter`
- **Expression copied**: must be `false` for first round (spec-patch only)
- **Rights**: license, provenance URL, permission basis
- **Hard boundary**: what must NOT be absorbed (e.g., "no auto-optimizer")

### Step 4: Candidate Decision

| Signal | Action |
|--------|--------|
| Real governance gap + minimal pattern available | Create observation → candidate |
| Interesting but no real gap | Record as observation (DISCOVERY), no candidate |
| Outside sublation domain entirely | Record as note, no candidate |
| Would expand scope beyond governance | Reject explicitly with reason |

## Worked Examples

### SkillOpt (Microsoft) → ABSORBED

- **What**: ML-inspired skill optimization loop (Rollout→Reflect→Aggregate→Select→Gate)
- **Gap found**: sublation can prove structure correct + no regression, but cannot prove improvement
- **Absorbed**: Gate pattern → `empirical_scorecard` (optional manifest field)
- **Rejected**: Auto-optimizer, rank/select/clip, slow-update markers, meta-skill
- **Candidate**: `20260531-empirical-scorecard-gate-codex`

### crawl4ai (unclecode) → INSTALLED, NOT ABSORBED

- **What**: 50k+ star async web crawler (Playwright pool → LLM-ready Markdown)
- **Verdict**: Crawling/infrastructure tool, not governance. Complements Scrapling (anti-bot) for large-scale structured crawling.
- **Action**: Installed (`pip install crawl4ai`), no sublation candidate.

### liteparse (run-llama) → REJECTED

- **What**: Rust-native PDF parser (PDFium + Tesseract OCR), Python bindings
- **Verdict**: Existing tools (docling, pdfminer, document-ocr) already cover this ground. No new capability.
- **Action**: Not installed. Revisit if existing PDF parsing becomes a bottleneck.

### book-to-skill (virgiliojr94) → REJECTED

- **What**: Book→structured skill converter
- **Verdict**: Skill creation pipeline, not governance. Zero overlap with sublation's domain.
- **Action**: Installed as user skill (productivity/book-to-skill), no sublation candidate

### Graphify (safishamsi, YC S26) → REJECTED

- **What**: Multi-modal knowledge graph builder (code/docs/PDFs/images/videos → interactive HTML + JSON graph)
- **Verdict**: Analysis/comprehension tool, not governance.
- **Action**: Installed as user skill (research/graphify via `uv tool install graphifyy`), no sublation candidate

## Decision Authority

**Agent must not autonomously route external tools into sublation — and must not force-fit absorption where none exists.** The user decides whether an installed tool warrants governance treatment. The evaluation loop is: clone → read → assess value → install if useful → skip if redundant → **stop**. Do not then say "but maybe sublation could absorb the methodology of X" unless the user explicitly asks. When a project is genuinely irrelevant to sublation (book-to-skill = skill creation, not governance; liteparse = redundant with existing tools), say so honestly and move on. Only when the user says "这个能不能被 sublation 扬弃" or "安全审查的方法论可以提取" does the absorption analysis proceed to observation and candidate.

## Pitfalls

- **Don't absorb because it's from Microsoft/Google/etc.** Authority bias. Evaluate the idea, not the brand.
- **Don't absorb an entire optimizer when you only need a gate.** Sublation is governance, not a training loop.
- **Don't skip rights provenance.** Even MIT-licensed projects need `expression_copied: false` and `absorbed_category` recorded.
- **Don't let "evaluation mode" become "feature creep mode."** Maintenance mode discipline says: real cracks only.
