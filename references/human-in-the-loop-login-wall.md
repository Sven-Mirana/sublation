# Human-in-the-Loop Pattern for Login-Walled Data Sources

## Problem

Some high-value NPL data sources (e.g., 中登网/动产融资统一登记公示系统) require user login with captcha before querying. The naive approach of trying to OCR captchas and automate login is both unreliable and violates security boundaries.

## Solution: Human-in-the-Loop Provider Contract

Rather than attempting full automation, model the login requirement as a provider state:

### Provider States

| status | meaning | can report "no new data"? |
|--------|---------|--------------------------|
| `ok` | logged in, query succeeded, has data | report by new count |
| `no_new` | logged in, query succeeded, no new data | yes |
| `login_required` | user must complete login first | no |
| `captcha_pending` | waiting for user to complete human verification | no |
| `blocked` | access restricted, session invalid | no |
| `parse_empty` | page accessible but no results parsed | no |
| `error` | network/dependency/runtime error | no |
| `disabled` | intentionally skipped this round | no, must state recovery condition |

### Implementation Pattern

1. **Script scaffold**: Create `scripts/<source>_monitor.py` with `--fixture` mode first
2. **Live placeholder**: Real mode returns `login_required` immediately — does NOT attempt auto-login
3. **CDP bridge**: After user completes login in browser, use CDP to detect login state and query
4. **Provider contract**: Output JSON with `source_ok`, `status`, `error_type` following the same schema as yindeng/auction monitors

### Security Boundaries

- Agent NEVER stores, forwards, or reads plaintext credentials
- Agent NEVER attempts to bypass or solve captchas
- User manually enters username, password, and captcha in browser
- After login, only the current browser session is used for queries
- Scripts MUST NOT accept `--username`/`--password` CLI arguments

### Case Study: 中登网 (2026-06-02)

- Site: https://www.zhongdengwang.org.cn/
- Login form: username + password + captcha (can be math or Chinese character based)
- 7 registration types: equipment mortgage, receivables pledge, warehouse receipt pledge, finance lease, factoring/transfer, retention of title, other
- Candidate: `npl-monitor/20260602-zhongdeng-human-login-cdp-codex`
- Script: `scripts/zhongdeng_monitor.py` — fixture-first, live mode returns `login_required`
- CDP implementation deferred to next phase after user completes browser login

### Why Not Visual Coordinate Login

Hermes's strength is business review and legal judgment, not login page coordinate conversion. Login pages with input fields, captchas, buttons, zoom, and overlays make coordinate-based login unreliable. The correct division of labor:

- **Codex**: Browser/CDP/DOM positioning, scripts, fixtures, audit
- **User**: Enter credentials, complete captcha
- **Hermes**: Judge registration results' significance for NPL/construction-law work
