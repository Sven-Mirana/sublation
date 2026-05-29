# System Health Scan — 只读系统健康扫描工作流

首次执行于 2026-05-27，由 Hermes 主导、Codex 辅助验证。

## 目的

定期扫描整个 sublation 治理系统 + 技能目录的健康状态，发现积压观察窗、stale-active 候选、孤立观测记录、审计盲区、脚本语法错误、文件热点竞争、Pitfalls 缺失。

## 扫描维度（7 项）

| 维度 | 检查项 | 方式 |
|------|--------|------|
| 环境 | config 警告、cron 健康、依赖完整性 | cron 运行日志 + config.yaml 审计 |
| 候选队列 | stale-active、未闭合观察窗 | `lifecycle.py scan --state all` |
| 观测记录 | 孤立项、误分类、reflection_type 缺失 | `find ~/.hermes/skill-observations` |
| 审计覆盖率 | 最近暴露问题是否被 audit 规则捕获 | 对比 session 问题 vs audit.py |
| 技能目录 | 脚本语法错误、悬空引用 | `compile()` 全量扫描 + 引用匹配 |
| 文件热点 | 多候选竞争同一正式文件 | `grep -l` 遍历所有 PATCH.diff |
| Pitfalls | 真实教训是否进入 SKILL.md | 对比 session 踩坑 vs Pitfalls 节 |

## 输出格式

按 `🟢健康 / 🟡需关注 / 🔴需修复` 三级，附带优先级建议（P0/P1/P2/P3）。
