# Agent-Insight 外部项目吸收分析

## 发现背景

2026-06-02 夜间，从 openEuler 社区的 `witty-skill-insight` 项目发现了 Agent-Insight——一个完整的 Agent Skill 评估与观测平台。

## 项目概览

- 来源：openEuler（华为主导的开源社区）
- 许可：MIT
- 技术栈：Next.js + Prisma + TypeScript
- 安装方式：隔离 `git clone` + 手动 `npm install` / `npm run dev`。禁止运行一键 install。
- 框架兼容：OpenCode / Claude Code / Hermes / LangChain / OpenClaw
- 核心：观测（Observability）+ 评测（Evaluation）+ Skills 优化（Optimization）

## 内置 8 个 Skill

| Skill | 功能 | 风险 |
|-------|------|------|
| skill-optimizer | 静态合规检查(L1) + LLM质量评估(L2) + trace优化 | DiagnosticMutator 可修改目标 Skill 目录 |
| skill-generator | 从描述/文档自动生成 Skill | 低风险 |
| skill-benchmark-generator | 生成 routing+outcome 双评测集 | 低风险 |
| skill-sync | Skill 仓库同步 | pull 会覆盖本地同名文件 |
| agent-debug-diagnosis | Agent 调试诊断 | 低风险 |
| routing-benchmark-generator | routing 专项评测 | 低风险 |
| outcome-benchmark-generator | outcome 专项评测 | 低风险 |
| iterative-optimizer | 迭代优化器 | 优化后会直接修改原始 skill 文件 |

## 三条红线（Codex 源码分析结论）

经 Codex 阅读源码后确认的三条红线：

1. ❌ **DiagnosticMutator 改正式目录** → skill-optimizer 的 DiagnosticMutator 可修改目标 Skill 目录下的 SKILL.md 及辅助文件。必须禁止直接作用于正式技能。
2. ❌ **iterative-optimizer 直接写原始文件** → 优化后会直接修改原始 skill 文件。必须禁止。
3. ❌ **skill-sync pull 覆盖本地** → 有覆盖本地同名文件的风险。必须禁止。

## 吸收方向：Read-Only Evaluator Adapter

Codex 建议的集成模式：

- 只读候选副本/fixture/由候选复制出的 `/private/tmp` 临时目录
- 使用官方 `automation/import` API 导入候选副本
- 使用 native static evaluation API，默认 `enableL2:false`
- 产出 `external_evaluations[]` + `validation.empirical_scorecard`
- 禁止：`load_skill`、`skill-sync pull`、`iterative-optimizer`、DiagnosticMutator、正式目录写入
- 首个试跑样本使用 `piclist-upload/20260602-dry-run-offline-codex`

## 与 sublation 的关系

| 维度 | sublation | Agent-Insight |
|------|-----------|---------------|
| 驱动 | 治理（人审+规范） | 数据（运行trace+评测） |
| 核心动作 | candidate→audit→promote | trace→benchmark→optimize |
| 问的是 | "该不该晋升？" | "改得好不好？" |
| 强项 | 过程可审计、回滚可追溯 | 量化评测、A/B对比 |

两者互补，不是替代。吸收后 sublation 可以同时具备治理驱动和数据证据两条腿，但 Agent-Insight 的数据证据不能替代 sublation 的晋升门。

## 吸收流程（当前状态）

```
1. 外部项目发现 ✅
2. 源码评估（Codex 已完成）✅
3. 三条红线确认 ✅
4. 隔离安装方案确认 ✅
5. 隔离服务启动与 DB 路径核验 ✅
6. 候选副本官方 API 导入 ✅
7. Native L1 静态评估 `enableL2:false` ✅
8. 待：创建 read-only evaluator adapter 候选并交叉复核
9. 待：用户批准后再晋升到正式 `skill-sublation`
```

## 首个 native L1 验证

2026-06-03，Codex 用 `piclist-upload/20260602-dry-run-offline-codex` 候选副本完成 Agent-Insight native static evaluation：

- 导入 API：`POST /skill-insight/api/skills/automation/import`
- 评估 API：`POST /skill-insight/api/skills/<id>/versions/0/evaluate`
- `enableL2`: `false`
- evaluation id：`cmpxpsq1p000513zcivc3ylqm`
- issues：`0`
- severity：`high=0, medium=0, low=0`
- 正式技能目录未作为输入，未修改

报告：`coordination/tri-party-room/agent-insight-piclist-native-static-20260603.md`

## 吸收作为 sublation 自进化的案例

这次吸收本身就是一个 sublation 候选：

> 外部项目 → 评估 → read-only adapter → candidate → audit → promote → sublation 自进化

"取其精华去其糟粕自进化是扬弃的精髓" —— 用户原话，2026-06-02。
