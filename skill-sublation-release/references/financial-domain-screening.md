# Financial Domain Screening for Sublation

Standardized methodology for screening finance/stock skills as sublation targets. Companion to `general-domain-screening-methodology.md`.

## When to Use

When the user's focus is on financial-domain skills (A-stock, HK, US markets, macro analysis, portfolio tools). Triggers: "鉴股", "股票", "金融", "investing", "macro".

## Skill Categories

Financial skills fall into four layers — screen from top to bottom:

### Layer 1: Data Source Skills (有脚本, API-dependent)
- **polymarket**: CLOB prediction market API. 1 Python script, external API calls.
- **tushare / akshare-stock**: A-stock data pipelines. Multiple scripts.
- **cn-financial MCP tools**: Live market data (realtime quotes, financials, money flow). Note: MCP tools are NOT skills — sublation does not apply. List them for awareness.

### Layer 2: Analysis Skills (有脚本 or 有方法论, compute/transform)
- **stock-daily-analysis** (superseded by stock-workspace): Technical + fundamental daily reports.
- **stock-workspace**: Unified stock research workspace (already sublated).
- **fincept-macro-swarm**: Multi-agent macro analysis framework. 0 scripts, 2 references.
- **claude-stock-***: 6 skills (analyst committee, DCF, earnings, fundamental, morning note, X sentiment). All merged into stock-workspace. 0 scripts each.

### Layer 3: Portfolio/Modeling Skills (heavy docs, light scripts)
- **financial-modeling**: 3-statement projections, DCF.
- **investment-memo**: VC/PE memo templates.

### Layer 4: Execution/Trading Skills
- **easytrader**: A-stock automated trading framework (同花顺/雪球/广发/华泰). 1 file, 0 scripts.

## Screening Flow

```
1. Filter by domain: 金融/股票/宏观/投资
       ↓
2. Exclude already-sublated/superseded:
   - stock-daily-analysis → superseded by stock-workspace
   - stock-workspace → 2 candidates already (pycache + merge inventory)
   - 6× claude-stock-* → all merged into stock-workspace
       ↓
3. Classify by script presence:
   - Has .py/.sh scripts → ⭐⭐⭐ (defect surface measurable)
   - Has methodology docs only → ⭐⭐ (semantic review only)
   - SKILL.md only, no scripts → ⭐ (superseded or merged)
       ↓
4. Output tiered report → user decision → delegate to Codex
```

## First Application (2026-06-02)

Screened 16 financial skills. Result:
- 2 actionable: polymarket (⭐⭐⭐, 1 script) + fincept-macro-swarm (⭐⭐, methodology)
- 8 excluded: stock-daily-analysis (superseded), 6× claude-stock-* (merged), easytrader (0 scripts)
- 1 toolset noted: cn-financial MCP (not a skill, sublation N/A)
- 4 not found: stock-monitor, tushare, akshare-stock, investment-memo, financial-modeling

Recommended: start with polymarket (only financial skill with real scripts and API surface).

## Pitfalls

- **MCP tools ≠ skills**: cn-financial provides `get_realtime_quote`, `get_financial_indicators`, etc. These are MCP tools, not skills — no SKILL.md, no scripts to patch. Do not waste time trying to sublate them.
- **Superseded skills still exist on disk**: stock-daily-analysis has `status: superseded` in its SKILL.md but the directory still exists. Don't re-screen it — the merge inventory candidate already documented the absorption.
- **Financial screening = user's top priority domain**: The user is transitioning to professional stock analysis (鉴股). Financial skills have equal weight to legal skills. Don't deprioritize financial screening.
