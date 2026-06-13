# Sublation 自我扬弃记录

sublation 是它自己治理的第一个 skill。每一次流程裂缝都必须回流到框架本身，形成新的候选、审计、复核和晋升记录。

## 演进表

| 版本 | 日期 | 触发事件 | 吸收内容 |
|---|---|---|---|
| v1.0 | 2026-05-25 | 初始发布 | 候选、审计、复核、晋升、观察窗的基础框架 |
| v1.1 | 2026-05-28 | 跨 Agent 路径错配 | post_promotion_safety、formal_post_promotion、rollback 证据 |
| v1.2 | 2026-06-02 | 全库上游同步 | sync-before-screen、rollback/backfill、上游 drift 处理 |
| v1.3 | 2026-06-04 | “为扬弃而扬弃”风险 | value_delta_gate，无正向增量不进晋升 |
| v1.4 | 2026-06-10 | Claude Code 首日幻觉 | 自报声明必须用 grep/read-back/diff 硬证据验证 |
| v1.5 | 2026-06-10 | 用户任命 Hermes 为办公室主任 | Hermes 统一汇总、合规确认、群聊管理 |
| v1.6 | 2026-06-11 | 四方治理讨论 | Codex/Hermes/Claude Code 三方独立报告，用户最终决定 |
| v1.7 | 2026-06-11 | 报告刷屏与角色不清 | Hermes 汇总三方报告，用户只看一份简报 |
| v1.8 | 2026-06-11 | NPL 登录墙重复追踪 | MCP 留位模式，登录墙不污染治理视图 |
| v1.9 | 2026-06-11 | 群聊被业务状态污染 | 群聊只承载候选评估、晋升审批、框架修订和宪法变更 |
| v1.10 | 2026-06-11 | 候选层镜像漂移 | 共享根 audit/read-back 护栏，工作区自报不等于候选真相 |
| v2.0 | 2026-06-11 | 系统性重构 | 宪法化、硬边界收束、七章结构、pitfalls 归档、候选共享根一致性 |

## 关键吸收

### 1. 三方治理

单一复核视角会漏实现边界、业务边界或事实核验。现在晋升前必须有 Codex、Hermes、Claude Code 各自的价值/风险报告。

### 2. 观察窗分界

复核通过不等于生产完成。晋升后必须进入 `observation_window`，用真实调用、生产周期或用户确认闭合。

### 3. 登录墙 MCP 预留

登录墙不是缺陷，而是设计约束。保留 MCP/provider contract 接口，不保存凭据，不把 human-login 长期写成阻塞缺陷。

### 4. 幻觉核实

Agent 自报不可信。任何“已完成/已写入/已验证”必须被 read-back、diff、grep、hash、audit 或 fixture 支撑。

### 5. 路径强校验

manifest path 不是事实。跨 Agent 根、source/target 不一致、正式路径未被修改，必须由 filesystem-derived check 捕获。

### 6. 价值增量门

候选通过 audit 只表示结构可审，不表示值得晋升。正向增量、旧能力保留、fallback、观察窗验收标准必须写清。

### 7. 统一汇报

三方仍独立评估，但最终呈报用户的晋升建议由 Hermes 汇总。这样用户只看一份去重、标注分歧、带阻塞项的简报。

### 8. 候选共享根

候选工作区不是事实源。跨 Agent 修复必须同步到 `~/.hermes/sublation/candidates/`，并在共享根复跑 audit/read-back。否则 Codex、Hermes、Claude Code 可能基于不同副本得出互相矛盾的结论。

## 循环

```text
经验暴露裂缝 -> 建候选修框架 -> 三方复核 -> 用户批准
-> 晋升观察 -> 新经验暴露新裂缝
```

这个循环不能只用于其他 skill。sublation 的可信度来自它自己也被同一循环治理。
