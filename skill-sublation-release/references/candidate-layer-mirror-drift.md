# Candidate-Layer Mirror Drift (候选层镜像漂移)

> 2026-06-11 发现 | v2.0 吸收

## 事件

Claude Code 在评审多个 `review_pending` 候选时发现：Codex 报告候选 manifest 枚举修复通过、audit passed，但 Claude Code 在共享根目录 `~/.hermes/sublation/candidates/` 实跑 audit 显示仍然 FAIL。根因是修复只写在 Codex 工作区，未同步到共享候选根。

Hermes 未经共享根实跑就确认 Codex 自报，违反了“自报不可信，硬证据验证”的宪法原则。

## 根因

这是 `canghe-comic` 跨 Agent 路径错配的候选层复发：

| 层级 | 事件 | 吸收 |
|---|---|---|
| 晋升层 | 候选晋升到 Codex 目录，Hermes 生产目录未修改 | v1.1: strong_path_check + post_promotion_safety |
| 候选层 | 候选修复只在工作区，Hermes 共享根仍是旧版 | v2.0: 共享根 audit/read-back 护栏 |

## v2.0 规则

- 候选修复报告必须声明修复 root、同步 root、共享根 audit 数字。
- Hermes 确认候选状态前必须在共享根实跑 audit/read-back。
- 进入用户统一简报前，`PATCH.diff` 必须能套到当前 formal baseline。
- 报告中的 line count、hash、audit 数字必须来自实测，不转述未验证口径。

## 教训

一条 bug 在晋升层被修了，不代表候选层不会复发。跨 Agent 路径不可信，跨 Agent 工作区也不可信；候选协作的真相源必须收束到共享候选根。
