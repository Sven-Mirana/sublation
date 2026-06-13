# GitHub Release Checklist — skill-sublation

在将 sublation 治理的技能作为独立 repo 发布到 GitHub 之前，逐项检查。

## 1. 清理

- [ ] 删除 `scripts/__pycache__/` 和所有 `.pyc` 文件
- [ ] 删除 `SKILL.md.orig`、`*.bak`、`*~` 等备份文件
- [ ] 添加 `.gitignore`（至少覆盖 `__pycache__/`、`*.pyc`、`.DS_Store`）
- [ ] 全局搜索 `/Users/<name>` 硬编码路径，替换为 `~` 或 `$SKILL_ROOT`
- [ ] 检查 references 中是否包含个人案件材料、客户数据、私密信息

## 2. 治理完整性

- [ ] `lifecycle.py health` 通过（`no observation-window health issues`）
- [ ] 决策队列为空（`lifecycle.py scan` 无 active/stale-active）
- [ ] 所有正式 skill 内容都有对应的 candidate→audit→review→promote 链路
- [ ] 如有未入账变更，先建 backfill 候选补账再发布
- [ ] 最近 7 个候选 strict audit 全部 pass

## 3. repo 结构

```
skill-sublation/
├── README.md           ← 独立介绍（不依赖 hermes-agent 上下文）
├── LICENSE             ← MIT
├── CHANGELOG.md        ← 从候选历史提取的版本演进
├── RELEASE-v1.0.md     ← 发布报告 + checklist
├── .gitignore
├── SKILL.md
├── scripts/
│   ├── observe.py
│   ├── candidate.py
│   ├── audit.py
│   └── lifecycle.py
├── schemas/
│   ├── manifest-v3.json
│   └── observation-v3.json
└── references/
    ├── merge-driven-sublation.md
    ├── cross-skill-absorption-*.md
    ├── darwin-evaluator-adapter.md
    ├── post-promotion-safety-net.md
    ├── business-smoke-test-pattern.md
    ├── provider-contract-pattern.md
    ├── system-health-scan-workflow.md
    └── experiments/        ← 标注为 historical example
```

## 4. 不放进 repo

- `candidates/` — 运行态数据（~7MB），内部治理记录。CHANGELOG.md 会提炼关键信息。
- `rollback-points/` — 运行态备份（~3.5MB），无发布价值。
- 任何含个人路径、案件信息、私密数据的文件。

## 5. 联合审计（发布前最后一道门）

在 `git commit` 之后、`git push` 之前，必须完成一轮联合审计：

1. **Codex 一审**：委托 Codex 对 release candidate 做独立审计，检查维度：
   - 内容完整性（SKILL.md 自洽、references 完整、无死链）
   - 隐私/安全（无硬编码路径、无敏感数据、无 token 泄露）
   - 脚本健康（语法编译、`--help` 可用、输入校验）
   - 文档质量（README 清晰、CHANGELOG 准确、LICENSE 存在）
   - 结构（.gitignore 正确、无垃圾文件）
   - 治理自洽（发布 repo 自身是否通过 sublation 标准）
2. **Hermes 二审**：验证 Codex 所有 findings，修复 blocker，重新验证。
3. **联合报告**：将 findings + resolution 写入 `JOINT-AUDIT.md`，交用户审批。
4. **用户批准后才推送**。

本会话首例：Codex 发现 6 个问题（3 HIGH / 2 MEDIUM / 1 LOW），Hermes 逐一修复并验证通过，联合报告批准后发布。其中 candidate.py 复制 `.git/` 和路径穿越是只有独立审计才能发现的盲区。

## 6. 文档要求

- **README.md**：是什么、核心概念（扬弃链路、三房协作、候选生命周期）、快速开始、目录结构
- **CHANGELOG.md**：每个候选 → 版本号 → 一句话变更摘要 → 日期
- **LICENSE**：MIT
- **RELEASE-v1.0.md**：发布声明 + 完整 checklist 通过记录 + 已知局限

## 7. 发布后

- [ ] `git init && git add -A && git commit -m "v1.0.0: initial release"`
- [ ] `git tag v1.0.0`
- [ ] 推送到 GitHub
- [ ] 在 README 中更新安装说明（`hermes skills install <url>` 或 clone 路径）
