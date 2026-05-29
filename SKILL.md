---
name: skill-sublation
description: 技能扬弃（Sublation/Aufhebung）——让技能从执行经验中产生观测、候选、验证、复核和晋升记录的可落地治理流程。正式技能目录默认只读；候选层自由打磨；用户可显式委托 Agent 执行低风险晋升。触发词：skill-sublation、技能扬弃、skill evolution、patch proposal、技能治理。
---

# Skill Sublation — 技能扬弃 v3

扬弃不是让 Agent 随手改正式技能，而是把执行经验沉淀成可审计的改进链路：

```
观测 observation -> 候选 candidate -> 验证 validation -> 交叉复核 review
-> 晋升 promotion -> 生产观察窗 observation window
```

NPL monitor 三轮实验只是引子：001 是规范层 `spec-patch`，002 是脚本层 `script-enhance`，003 是部署层 `infra-fix`。主线从现在起回到 skill-sublation 本体能力。

## 核心原则：手段 vs 目的

**用创造 skill 的方式来验证扬弃只是手段，不是目的。** 三场实验的价值不是「又多了三个候选记录」，而是每一场暴露了框架本身的裂缝——这些裂缝才是指向 skill-sublation 需要进化的路标。

**把握主要矛盾的主要方面**：主要矛盾是「sublation 治理框架还不够完善」，主要方面是迭代 skill-sublation 本身。次要方面是「把扬弃应用到其他 skill」——它作为验证手段有用，但一旦验证完就退场，不要沉迷其中。**发现一个新裂缝的价值远大于在同类型 skill 上重复跑扬弃流程。**

**判断标准**：如果你在考虑「下一个该扬弃哪个 skill」，你已经跑偏了。正确的问题是「这三个实验揭示了 sublation 框架的什么弱点，skill-sublation 的 SKILL.md 下一版应该怎么改」。

## 硬边界

1. **正式技能目录默认只读**：Agent/cron 不自行修改 active skill path 下的 `SKILL.md`、`scripts/`、`references/` 等文件。
2. **候选层可自由打磨**：候选副本放在 `~/.hermes/sublation/candidates/<skill>/<candidate-id>/`，且不得出现在 active profile 的技能搜索路径中。
3. **晋升有三种合法模式**：
   - `human_patch`：人类手动合入。
   - `user_delegated_agent_patch`：用户在当前任务中明确授权 Agent 合入，Agent 执行并记录。
   - `rollback`：按 manifest 的 `rollback_hashes` 或备份恢复。
4. **cron 不做自动晋升**：cron 最多创建观测、候选和提案；不能自行合入正式技能。
5. **基础设施问题先走负面清单**：workdir、权限、密钥、网络临时失败、调度器 cwd 漂移，优先修配置或记录待办，不应伪装成技能内容缺陷。
6. **合并删除须用户审批**：候选产出和复核由 Hermes/Codex 自主完成，但原技能删除（promote 时 `absorbed_into` 触发的删除动作）必须经用户明确批准。候选在 `candidates/` 沙盒中不伤原技能，Hermes 复核通过后呈报用户，用户点头才执行删除。流程：observe → candidate → audit → Hermes复核 → **【用户审批删除】** → promote。

## 最小落地命令

从本技能目录运行：

```bash
cd ~/.hermes/skills/hermes-agent/skill-sublation
```

### 1. 写入观测

```bash
python3 scripts/observe.py npl-monitor \
  --skill-path ~/.hermes/skills/legal/npl-monitor \
  --session cron_5deb084e32e9_20260526 \
  --classification defect \
  --reflection-type SKILL_DEFECT \
  --step "脚本状态输出" \
  --status defect_suspected \
  --evidence "数据文件缺少 source_ok/status" \
  --summary "报告层无法区分数据源正常为空和异常为空" \
  --recommendation create_candidate
```

输出写到 `~/.hermes/skill-observations/{skill_hash}/`。

### 2. 创建候选副本

```bash
python3 scripts/candidate.py create npl-monitor \
  --source-path ~/.hermes/skills/legal/npl-monitor \
  --candidate-type script-enhance \
  --agent codex \
  --observation e6a18c28dbcb/observations/20260525-090428-cron_5deb.json
```

输出写到 `~/.hermes/sublation/candidates/<skill>/<candidate-id>/`。

### 3. 审计候选

```bash
python3 scripts/audit.py ~/.hermes/sublation/candidates/npl-monitor/<candidate-id>
```

`audit.py` 默认运行 strict checks。临时诊断旧候选时可用 `--no-strict` 只跑基础结构检查，但晋升前必须通过默认 strict audit。

审计结果三态：

| 状态 | 含义 |
|---|---|
| `passed` | 可进入复核/晋升提案 |
| `conditional` | 可人工判断，但需说明缺口 |
| `failed` | 不应晋升 |

## 八步流程

1. **Observe**：用 `observe.py` 写入结构化观测。
2. **Classify**：区分 `DISCOVERY`、`OPTIMIZATION`、`SKILL_DEFECT`、`EXECUTION_LAPSE`。
3. **Trigger**：单次 `critical` 或同一步骤 ≥3 次可信 defect，才创建候选；用户显式要求可立即创建。
4. **Candidate**：用 `candidate.py` 复制正式技能到候选层，生成 manifest 和说明文件。
5. **Edit**：Agent 只在候选层改动，声明 scope/out_of_scope。
6. **Validate**：只用 fixture、合成输入、临时输出目录；禁止写真实用户数据。
7. **Review + Promote**：交叉 Agent 复核；用户批准或用户委托 Agent 后，才合入正式层。
8. **Production Observation Window**：晋升后至少观察一个生产周期或一次真实调用；未闭合前不得把状态写成完全完成。观察窗必须显式闭合，不能只因为默认队列为空就视为完成。

## 观察窗闭合策略

`observation_window` 是仍需治理判断的状态，不是历史归档。候选晋升后满足下列任一条件，才可闭合：

- 至少一次真实调用或生产周期证明行为稳定；
- Hermes/Codex 复核确认后续 drift 只来自已批准的兄弟候选晋升，且不代表当前候选语义丢失；
- 用户明确确认该候选的实用目标已达成。

闭合前必须记录：

- `closed_at`
- `closure_reason`
- `closure_evidence[]`
- `closure_reviewed_by`
- `closure_policy`

并发观察窗按层级处理：先闭合 `skill-sublation` 框架候选，再闭合被治理对象候选；同层按 `promoted_at` 从早到晚处理。框架候选未稳定前，不应批量闭合依赖该框架语义的业务候选。

使用 `lifecycle.py` 闭合观察窗：

```bash
python3 scripts/lifecycle.py close-observation \
  ~/.hermes/sublation/candidates/<skill>/<candidate-id>/manifest.json \
  --reason "真实调用稳定，后续 drift 来自已批准的兄弟候选" \
  --evidence "audit warning reviewed; no semantic loss" \
  --reviewed-by both
```

先用 `--dry-run` 预览。该命令只允许从 `observation_window` 转到 `closed`，并保留旧 `notes` 后追加闭合说明。

## 晋升后安全网

晋升不是终点。每个候选从 `approved` 进入正式技能后，必须先进入 post-promotion safety net，防止"扬弃完反而退化"。

**必须记录到 `validation.post_promotion_safety`**：

- `rollback_ready`: 已创建 rollback point，且 rollback path 可读。
- `target_path_verified`: 晋升目标路径已确认属于当前 runtime/profile 的正式技能目录。
- `source_path_matches_promotion_target`: 候选来源路径与实际晋升目标一致；如果不一致，必须写 `target_path_note` 说明跨 Agent 同步或 profile 差异。
- `business_smoke_test.status`: `passed | pending | failed | not_required`。
- `business_smoke_test.evidence[]`: 真实调用、半真实 fixture、人工复核报告或用户验收记录。
- `fallback_verified`: 新合约、外部数据源或生成 backend 不可用时，是否会退回旧 workflow 或明确降级。
- `old_capability_retained`: 原技能关键能力是否保留。

**关闭观察窗前的最小门槛**：

1. `rollback_ready == true`。
2. `target_path_verified == true`。
3. `business_smoke_test.status` 是 `passed` 或 `not_required`。
4. 对业务技能，必须证明旧能力保留；对纯框架候选，必须证明后续候选已经使用过该框架能力。
5. 有外部依赖的候选必须证明 fallback 或透明降级存在。
6. 观察窗只能用 `lifecycle.py close-observation` 闭合；不得只手改 `status: closed`。

这条规则来自 `canghe-comic` 路径错配事件：Codex 候选曾指向 Codex skill path，而 Hermes 生产侧实际使用 Hermes skill path。后续跨 Agent 晋升必须显式确认当前 runtime/profile 的正式路径，避免补丁合入了"另一个副本"。

## 三房协作工作流（Hermes ↔ Codex ↔ 用户）

sublation 全流程由 Hermes 和 Codex 分工执行，用户守生产门：

| 阶段 | Hermes 负责 | Codex 负责 |
|---|---|---|
| Observe | 写入结构化观测 (`observe.py`) | — |
| Classify | 区分 defect/optimization/discovery | — |
| Candidate | 判定是否满足触发条件 | 创建候选副本 (`candidate.py`)，实现改动，生成 PATCH.diff |
| Validate | 运行 `audit.py` 审计 | 编写 fixture / EVIDENCE.md / validation/RESULTS.md |
| Review | 交叉复核，写入复核意见到 manifest | 响应 Hermes 复核意见，修改候选 |
| Promote | — | 执行晋升（`user_delegated_agent_patch`）：合入 patch，更新 manifest，建 rollback point |
| Observation | 验证生产稳定性，闭合观察窗 (`status: closed`) | — |

**协作规则**：
- Hermes 自主决定前与 Codex 商议，无分歧直接执行
- 有分歧带报告找用户裁决
- 用户审批报告 + 提要求，不参与逐步骤操作
- Codex 超时（`max_iterations`）时 Hermes 接手完成纯机械步骤（应用 patch、更新 manifest、建 rollback point），不做新语义判断

## 协作安全：委托到外部模型的数据隔离

`delegate_task` 的 `context` 字段发送给外部模型（Codex/GPT-5.5），**绝不能**包含以下本地数据：

- ❌ 本地文件内容（代码、config、笔记正文）
- ❌ 文件路径清单（即使只是路径也会暴露目录结构）
- ❌ 案件信息、客户数据、私密文档
- ❌ workspace 目录树摘要
- ❌ 用户真实文件系统中的任何内容摘要

**正确做法**：`context` 只传任务描述、明确的任务参数（如候选ID、分支名）、和抽象化的技术上下文（如"需要在 audit.py 的 strict_checks 函数中增加一个检查项"）。需要的文件内容由 Codex 在自己 session 中自行读取——不提前推送。

违反这条边界的后果：外部模型在无用户直接授权的情况下获取了本地文件系统信息。

## 外部评估器接入：Darwin Adapter

Darwin 类 skill 的定位是 **外部评估器**，不是晋升者、不是正式技能编辑器。它可以为候选副本生成评分卡、test prompts、反向审计意见和改进建议，但不能绕过 sublation 的候选层、审计层、交叉复核和用户审批。

**硬约束**：

- Darwin 只能读取或评估 `~/.hermes/sublation/candidates/<skill>/<candidate-id>/` 下的候选副本。
- Darwin 不得直接修改 active skill path 下的正式技能目录。
- Darwin 的输出只能作为 `external_evaluations[]` 参考证据写入 manifest，不能把候选状态直接改成 `approved`、`promoted`、`observation_window` 或 `closed`。
- Darwin 若提出改写方案，必须生成 proposal/report，由 Codex/Hermes 在候选层手动吸收；不得由 Darwin 自行应用到正式技能。
- Darwin 使用 git ratchet 时，只能作用于候选副本或临时测试副本；正式晋升仍以 sublation 的 rollback point、manifest 和用户授权记录为准。

**推荐接入方式**：

```json
{
  "external_evaluations": [
    {
      "evaluator": "darwin-skill",
      "target": "candidate",
      "mode": "read_only_scorecard",
      "report_path": "validation/darwin-scorecard.json",
      "formal_skill_modified": false,
      "notes": "Darwin score is reference evidence only; promotion still requires audit/review/user approval."
    }
  ]
}
```

当候选涉及跨技能吸收、合并或从外部 skill 借鉴能力时，manifest 必须记录 `rights_provenance`。这不是形式主义，而是把"吸收思想/接口/流程"和"复制受保护表达或源文件"分清楚：

- 只吸收思想、流程、接口、质量标准：通常记录为 `expression_copied: false`。
- 复制 `SKILL.md` 段落、脚本、模板、素材、图片、配置：必须记录 license / permission basis，并进入人工复核。
- donor skill 的来源、路径、许可状态不明时，不得默认可复制；只能做 proposal 或抽象化重写。

详见 [references/darwin-evaluator-adapter.md](references/darwin-evaluator-adapter.md)。

## 业务烟雾测试

晋升后、关闭观察窗前，必须用 [业务烟雾测试模式](references/business-smoke-test-pattern.md) 验证被扬弃的技能在用户实际运行时仍能工作。audit 证明结构正确，烟雾测试证明操作正确。

## Pitfalls

- **Codex 需要 git 仓库**：委托 Codex 执行合并或晋升任务时，工作目录必须是 git 仓库（`git init`），否则 Codex 拒绝运行并返回 "Not inside a trusted directory"。子仓库的 sublation workspace 初始化后记得 `git add -A && git commit`。

- **Codex 内联提示词中的单引号**：通过 `terminal` 工具传入 Codex 的合并提示词如果包含单引号（如 `don't`、`it's`、中文引号 `'`），bash 会报告 `unexpected EOF while looking for matching`。**正确做法**：将提示词写入临时文件（如 `/tmp/codex-prompt.txt`），再用 `~/.local/bin/codex exec "$(cat /tmp/codex-prompt.txt)"` 传入。不要在 terminal 命令中内联复杂的多行提示词。

- **吸收≠低位阶**：看到两个同域技能时，不要默认"功能少的那个是低位阶"。先读双方 SKILL.md 的实际内容，确认哪一方有另一方缺失的局部优势（如运行时适配、平台约束处理、特定坑位的解决方案）。吸收的正确口径是"target 大体系吸收 donor 的局部经验"，不是"低位阶被吞掉"。如果 donor 全面落后于 target，用 `close-superseded` 而非吸收。

- **`close-superseded` 覆盖旧 notes**：`lifecycle.py close-superseded` 的 `--reason` 参数直接覆写 manifest 的 `validation.notes` 字段，不保留旧值。如果旧 manifest 有重要上下文（如审计结果、复核意见），先人工检查再执行 `--dry-run` 预览。

- **顺序晋升导致 `formal_post_promotion` hash 漂移**：当多个候选依次晋升并修改同一文件（典型是 `SKILL.md`），早期候选记录的 `validation.formal_post_promotion.files` hash 会被后续候选的晋升覆盖。`strict_formal_post_promotion_current` 必须按 `validation.status` 判断语义：`closed`、`rejected` 或 superseded 历史候选只报 `WARNING`，表示可能是后续合法晋升造成的记录漂移；`promoted` 或 `observation_window` 仍报 `FAIL`，因为观察窗内候选必须与当前正式状态保持一致。不要因为已关闭历史候选的 warning 回滚正式技能；如需消除警告，再人工更新 manifest 并说明漂移原因。

- **Codex 超时恢复**：当 Codex 通过 `delegate_task` 执行被委派的晋升任务时，可能因为迭代次数上限（`max_iterations`）在晋升步骤完成前退出。此时 Hermes 应检查候选状态：如果候选已通过审计且所有文件改动已完成，Hermes 直接接手完成纯机械步骤——应用 PATCH.diff、更新 manifest 的 `validation` 字段、创建 rollback point。不要重新委派 Codex（会重复工作），不要做新的语义判断（那是 Codex 的领域）。

- **PATCH.diff 格式兼容性**：候选的 PATCH.diff 可能带 bare `@@` 行（缺行号），导致 `git apply` 和 `patch` 命令失败。strict audit 必须在晋升前阻断 bare `@@` 和其他非法 hunk header；旧候选若已带坏 diff，先修 PATCH.diff 再晋升。

- **跨 Agent 晋升路径错配**：当 Codex 在自己的 skill 副本（如 `~/.codex/skills/`）上创建和晋升候选时，`source_skill.path` 可能指向 Codex 副本而非 Hermes 生产副本（如 `~/.hermes/skills/`）。晋升后必须验证正式技能目录确实被修改——`post_promotion_safety.target_path_verified` 和 `source_path_matches_promotion_target` 就是为这个坑设计的。首例：`canghe-comic` 候选晋升到了 Codex 目录，Hermes 目录的 SKILL.md 未被修改，业务验证时才暴露。

- **框架审计全过≠业务技能能跑**：strict audit 22 项全部通过只证明候选结构正确。晋升后必须跑业务烟雾测试（至少 dry-run：检查合约章节存在、workflow 步骤完整、关键能力字面保留）。不要把"audit passed"当成"发布就绪"。在 post-promotion safety net 制度化之前，这个教训代价是一个跨 Agent 路径错配 bug。

- **未入账的内容变更（unledgered formal drift）**：当正式 SKILL.md 或 references 中出现新内容，但没有任何候选 manifest 记录其变更链路时，这是治理账本缺口。对于 sublation 自身来说尤其敏感——治理框架自己的变更必须可审计。修复方式：建 backfill 候选，manifest 标注 `closure_reason: "backfill — content already validated in production; this candidate retroactively documents the governance trail"`，记录 scope、evidence、closure 信息后立即闭合。backfill 不是造假，是补录——内容已经生效且验证通过，差的是纸面记录。不要因为"内容没问题"就跳过补账；sublation 的信用来自每一条变更都可追溯到候选→审计→复核→晋升链路。

- **GitHub 公开发布前的清理与审计**：如果技能要作为独立 repo 发布到 GitHub，必须先过发布清理检查（见 `references/github-release-checklist.md`），然后完成 Codex+Hermes 联合审计并出具 `JOINT-AUDIT.md`（见 `references/pre-release-audit-pattern.md`），用户审批后才推送。完整发布流程见 `references/v1.0-release-process.md`。核心清理项：`__pycache__` 污染、`.orig` 备份文件、硬编码的个人路径、references 中的内部样本标注。联合审计项：内容完整性、隐私/安全、脚本健康、文档质量、结构、治理自洽。发布清理和审计不替代 sublation 治理——先补账再清理再审计。

- **gh auth 跨 session 认证失败 + publish.sh 工作模式**：Hermes 终端 session 无法访问用户本地 macOS 钥匙串中 `gh auth login` 存储的 token，导致 `gh auth status` 始终显示未登录。**不要反复重试 `gh auth login`**——改用 `publish.sh` 脚本模式：将 `git remote add`、`gh repo create --push` 等命令写入 `publish.sh`，让用户在本地终端直接执行。脚本用 `set -e` 确保任何步骤失败立即停止。

## 晋升前清洁检查

候选通过 audit 之后、正式晋升之前，必须做一次 promotion-readiness 检查：

- **正式文本口径**：将 `候选`、实验编号、临时注释等只属于候选层的标记移出将要晋升的正式内容；必要时保留在 `RATIONALE.md`、`EVIDENCE.md` 或 `PATCH.diff`。
- **相邻工作拆分**：如果复核中发现新的后续工作，把它写成下一个候选的待办，不要顺手塞进当前候选。例如完成标准和 provider contract 应分成两个候选。
- **manifest 同步**：复核人、复核结论、audit 状态、promotion mode、用户授权状态必须与事实一致。
- **最终 diff 检查**：晋升前确认 diff 只包含本候选 scope 内的文件和语义；脚本、配置、cron、真实数据输出不能被 spec-patch 顺带改动。

如果清洁检查发现问题，优先小修候选并重新 audit；不要为了赶晋升把候选层术语或未复核的相邻功能带进正式技能。

## strict audit 检查

默认 strict audit 在基础结构检查之外，还必须检查：

- **残留候选标签**：`PATCH.diff` 新增正式内容里不得出现 `（005a 候选）`、`(candidate)` 等候选层标题标记。
- **PATCH.diff 格式**：`PATCH.diff` 的 hunk header 必须是标准 unified diff 形式，例如 `@@ -12,3 +12,4 @@`；bare `@@` 或缺失行号的 hunk header 是 blocking `FAIL`。
- **spec-patch scope**：`spec-patch` 不得改动 `scripts/`、`config/`、`fixtures/`、`schemas/` 等运行面文件。
- **正式基线新鲜度**：晋升前，manifest 记录的 `source_skill.files` 必须与当前正式技能目录一致，避免旧候选晋升时误删新文件。
- **晋升后正式状态**：候选进入 `promoted`、`observation_window` 或 `closed` 后，不再用旧 `source_skill.files` 反查正式目录；改用 `validation.formal_post_promotion.files` 确认晋升记录与当前正式状态一致。`promoted` / `observation_window` 漂移是 blocking `FAIL`；`closed`、`rejected` 或 superseded 历史候选漂移是 non-blocking `WARNING`。
- **manifest 自洽**：`auditor_status`、`cross_reviewed_by`、`promotion_mode`、`status`、`promoted_by/promoted_at` 必须互相一致。
- **跨技能关系自洽**：如果 manifest 写入 `relationships`，必须满足 pattern 枚举、target 必填、cross-skill absorption 至少一个 donor、donor 与 target 不得同名同路径、donor 必须声明 `absorbed_capability`。
- **外部评估器自洽**：如果 manifest 写入 `external_evaluations`，Darwin 等外部评估器只能以 `target: candidate` 和 `mode: read_only_scorecard|proposal_only|dry_run` 进入；报告路径必须在候选目录内，且必须声明未修改正式技能。
- **权利来源自洽**：如果 manifest 写入跨技能 donor 关系，必须记录 `rights_provenance`；新候选缺失该字段是 blocking `FAIL`，历史已晋升候选缺失该字段只作为 warning 处理。
- **晋升后安全网自洽**：如果 manifest 写入 `validation.post_promotion_safety`，必须满足 rollback、路径确认、smoke test、fallback 和旧能力保留记录的自洽性。`closed` 候选缺安全网字段是 warning；安全网字段存在但显示失败是 blocking `FAIL`。

## 候选生命周期管理

候选目录不是待办池；只有仍需决策的候选才进入默认决策队列。使用 `scripts/lifecycle.py` 管理候选状态：

```bash
python3 scripts/lifecycle.py scan
```

默认只列出 `queue`：`active` 与 `stale-active`。查看所有历史候选：

```bash
python3 scripts/lifecycle.py scan --state all
```

观察窗健康扫描：

```bash
python3 scripts/lifecycle.py health --warn-after-days 7
```

`health` 只读扫描，不写 manifest。它必须暴露：

- 仍处于 `observation_window` 的记录；
- 已 `closed` 但缺少 `closed_at`、`closure_reason`、`closure_evidence[]`、`closure_reviewed_by` 或 `closure_policy` 的记录；
- 超过阈值仍未闭合的观察窗。

对策略生效前已经闭合的历史记录，可以显式传入 cutoff，把旧 closure metadata 缺口从当前故障中分离出来：

```bash
python3 scripts/lifecycle.py health \
  --waive-legacy-closed-metadata-before 2026-05-27T17:22:01Z \
  --include-waived
```

waived 记录会进入 `waived_issues`，不计入 `total_issues`，也不会触发 `--fail-on-issues`。cutoff 必须显式传入，避免默认掩盖新产生的缺字段记录。

生命周期状态：

| 状态 | 含义 | 默认进入决策队列 |
|---|---|---|
| `active` | `draft`、`validated`、`review_pending` 或 `approved`，且基线仍新鲜 | 是 |
| `stale-active` | 仍待决策，但 `source_skill.files` 已落后于正式技能 | 是，需先 rebase |
| `promoted` | 已晋升但尚未进入明确观察窗，或历史 promoted 记录 | 否 |
| `observation-window` | 已晋升且仍需闭合判断 | 否，但必须进入健康扫描 |
| `closed` | 观察窗已闭合，后续 drift 按历史记录处理 | 否 |
| `superseded` | 被后续候选吸收，不应再晋升 | 否 |
| `rejected` | 明确驳回或关闭 | 否 |
| `legacy` | 缺 v3 字段或历史字段不完整 | 否，需人工迁移 |
| `invalid` | manifest 无法解析 | 否，需人工修复 |

`superseded` 不作为 `validation.status` 新枚举写入，避免破坏 v3 schema。正式记录方式是：

```json
{
  "validation": {
    "status": "rejected",
    "promotion_mode": "none",
    "rejection_reason": "obsolete_superseded",
    "superseded_by": "<new-candidate-id>"
  }
}
```

标记旧候选被新候选吸收：

```bash
python3 scripts/lifecycle.py close-superseded \
  ~/.hermes/sublation/candidates/<skill>/<candidate-id>/manifest.json \
  --superseded-by <new-candidate-id>
```

闭合观察窗：

```bash
python3 scripts/lifecycle.py close-observation \
  ~/.hermes/sublation/candidates/<skill>/<candidate-id>/manifest.json \
  --reason "<why this observation window can close>" \
  --evidence "<production call, review note, or drift explanation>" \
  --reviewed-by hermes \
  --dry-run
```

### Legacy manifest 迁移规划

历史候选如果仍是 v2 或缺少 v3 必填字段，不应直接批量改写。先生成只读迁移规划：

```bash
python3 scripts/lifecycle.py plan-legacy
```

输出只是一份计划，不写任何 manifest。计划中每条记录必须包含：

- `action`: `plan_v3_migration`、`skip` 或 `manual_repair`
- `write_allowed: false`
- `confidence`
- `proposed.schema_version`
- `proposed.candidate_type`
- `proposed.validation`
- `blocked_reasons`

如果 `blocked_reasons` 非空，表示该条历史记录需要人类或交叉 Agent 复核后才能迁移。

## 候选类型

| 类型 | 用途 | 常见验证 |
|---|---|---|
| `spec-patch` | 只改 `SKILL.md` 或文档规范 | diff + 人工语义审查 |
| `script-enhance` | 改脚本行为或输出契约 | fixture + 临时输出 |
| `infra-fix` | workdir、cron、profile、配置路径 | 配置检查 + 不写真实数据 |
| `tooling` | 改 sublation 自身脚手架/审计工具 | 语法检查 + fixture/dry-run |

## manifest v3 要点

`manifest.json` 必须包含：

- `schema_version: 3`
- `candidate_type`
- `source_skill.files` 和 `rollback_hashes`
- `scope.changes` / `scope.out_of_scope`
- `validation.auditor_status`: `passed | conditional | failed`
- `validation.cross_reviewed_by`: `none | hermes | codex | both | user-waived`
- `validation.promotion_mode`: `none | human_patch | user_delegated_agent_patch | rollback`
- `validation.status`: `draft | validated | review_pending | approved | promoted | observation_window | closed | rejected`
- 观察窗闭合字段：`closed_at`、`closure_reason`、`closure_evidence[]`、`closure_reviewed_by`、`closure_policy`
- 跨技能关系字段（可选）：`relationships.sublation_pattern`、`relationships.target_skill`、`relationships.donor_skills[]`

完整 schema 见 `schemas/manifest-v3.json`。

## 观测 schema

观测记录使用 `schemas/observation-v3.json`。核心字段：

- `classification`: `clean | partial | defect | critical`
- `reflection_type`: `DISCOVERY | OPTIMIZATION | SKILL_DEFECT | EXECUTION_LAPSE`
- `recommendation`: `obs_only | flag_for_review | create_candidate`
- `step_details[]`: 记录具体步骤、证据、置信度

## 设计模式

### Provider Contract（direct / mcp / disabled）
外部数据源不绑定特定实现。详见 `references/provider-contract-pattern.md`。npl-monitor 005a 首次应用。

### 跨技能吸收（Cross-Skill Absorption）

当两个技能在同一领域重叠、但各有优势时，sublation 不只处理"单技能内部改进"——也处理"一个技能吸收另一个技能的局部经验"。这更接近黑格尔 Aufhebung 的本义：保留、超越、提升，而非消灭。

**吸收模型**：

```
donor skill (只读) ──提取局部优势──→ target skill (候选层修改)
                                          │
                                    candidate manifest 记录 donor 关系
                                          │
                                    验证 donor 零影响
                                          │
                                    晋升只改 target
```

**核心约束（三方基本规则）**：

1. **不误伤原则**：donor skill 在 sublation 全程保持完整可用，只读不写。任何步骤不得修改 donor 的任何文件。
2. **吸收不删除**：target skill 接收 donor 的经验，donor 不做任何修改、删除或降级。吸收完成后 donor 仍可独立使用。
3. **第一轮只做 spec-patch**：跨技能吸收首轮不改 scripts/、不生成实际产出（如图片/PDF），只改 SKILL.md + references。等 spec-patch 稳定后，后续候选可以扩展到脚本层。

**验证要点**：
- diff 确认 donor 目录无任何变化（`git diff --stat <donor-path>` 为空）
- manifest 的 `relationships` 必须声明 target skill、donor skill、吸收模式和具体吸收能力
- 晋升前 strict audit 额外检查：donor skill 目录与 baseline hash 一致

**manifest relationships 格式**：

```json
{
  "relationships": {
    "sublation_pattern": "cross_skill_absorption",
    "target_skill": {
      "name": "canghe-comic",
      "path": "~/.codex/skills/canghe-comic"
    },
    "donor_skills": [
      {
        "name": "baoyu-comic",
        "path": "~/.codex/skills/baoyu-comic",
        "absorbed_capability": "Hermes prompt-only image generation contract",
        "retained_boundary": "donor remains read-only and independently usable"
      }
    ],
    "note": "Preserve target workflow; absorb donor runtime contract."
  }
}
```

`relationships` 是候选级元数据，不表示 donor 被替换、删除或降级。`cross_skill_absorption` 必须至少有一个 donor，且 donor 的 `name` / `path` 不得与 target 相同。

**何时使用吸收 vs 单技能改进**：

| 信号 | 模式 |
|------|------|
| 两个技能在同域有重叠功能 | 跨技能吸收 |
| 一个技能有另一个缺少的运行时适配（如 Hermes vs 通用工具约束） | 跨技能吸收 |
| 只有一个技能需要改进，无外部参考 | 单技能改进 |
| donor 明显是 target 的上位替代 | 不是吸收，是候选 superseded |

**反模式**：不要把"吸收"当成"donor 低位阶被吞掉"。吸收的前提是 donor 有 target 值得学习的局部优势——如果 donor 全面落后，应该用 `close-superseded` 标记而非吸收。吸收的价值在于双方各有值得保留的东西。

首例：`canghe-comic ← baoyu-comic`（canghe 吸收 baoyu 的 Hermes prompt-only 适配经验），详见 `references/cross-skill-absorption-canghe-baoyu-comic.md`。

### 技能合并（Skill Merging）

当两个或更多技能在同一领域互补且各有脚本/工具时，不是吸收（donor→target），而是**合并成一颗新技能**。合并后的技能覆盖所有输入技能的使用场景，但更简洁、更强、入口统一。

**何时合并 vs 吸收**：

| 信号 | 模式 |
|------|------|
| 多个技能做同一件事（如四种 OCR 引擎） | 合并 |
| 技能形成天然管道（URL→MD→格式化MD→HTML） | 合并 |
| 技能是同一动作的不同平台后端（微信发布 / X 发布） | 合并 |
| 一个技能有另一个缺少的局部优势 | 跨技能吸收 |
| 只有一个技能需要改进 | 单技能改进 |

**合并方法论**（详见 `references/merge-driven-sublation.md`）：

1. **筛选**：扫描技能库，找出有实际脚本（.py/.sh/.ts）的功能性技能；纯文档技能合并价值低，跳过。
2. **聚类**：按功能域分组（OCR、格式转换、发布、技能管理等），评估合并价值（互补性、覆盖面、减负效果）。
3. **委托**：将聚类后的合并簇批量委托给 Codex，每个簇给一个合并任务（读源技能→分析重叠→设计合并方案→产出合并 SKILL.md）。
4. **收尾**：Codex 产出的合并候选进入标准 sublation 候选层（audit → review → promote → observation window）。

**合并成功的标准**：
- 输入技能数 > 输出技能数（做了减法）
- 合并后功能覆盖所有输入场景，无退化
- 用户使用时只需一个入口，不用纠结选哪个

**合并产出复核清单**（Hermes 审核 Codex 合并产出时必须逐项检查）：

1. **功能完整性**：所有源技能的核心功能是否在合并技能中保留？对照源 SKILL.md 逐项确认。
2. **入口统一**：是否有清晰的决策树/路由表，让 Agent 根据用户意图自动选择正确的工作流？
3. **脚本适配**：合并后的脚本是否通过了语法验证（`python3 -m py_compile` / `node --check`）？路径引用是否已更新？
4. **配置统一**：多个源的配置是否已合并到统一的 `config/` 下，避免用户需要维护多份 `.env`？
5. **降级策略**：如果某个引擎/后端不可用，合并技能是否明确说明降级路径，而非静默失败？
6. **元数据一致**：`absorbs` 字段是否在 SKILL.md 顶层而非嵌套在 `metadata` 内？`version`、`author`、`homepage` 是否已从源技能继承/修正？
7. **不误伤**：合并候选只存在于 `candidates/<name>-merge/`，源技能目录完全未触碰。

**首轮应用**（2026.5.28，15→5，减负 67%）：
- OCR 管道：`ocr-and-documents + mineru-ocr + paddleocr-doc-parsing + paddle-ocr` → `document-ocr`（4→1）
- 格式转换：`canghe-url-to-markdown + canghe-format-markdown + canghe-markdown-to-html + markitdown` → `universal-converter`（4→1）
- 内容发布：`canghe-post-to-wechat + canghe-post-to-x` → `content-publisher`（2→1）
- 技能管理：`skill-creator + skill-manager` → `skill-lifecycle`（2→1）
- 媒体工具：`universal-media-downloader + douyin-batch-download + video-compressor` → `media-toolkit`（3→1）

**第二轮应用**（2026.5.28，17→6）：
- 语音转文字：`funasr-transcribe + tingwu-asr` → `speech-to-text`（2→1，本地/云端自动路由）
- 文档生成：`docx + md2word + docx-generator` → `document-generator`（3→1，markdown→专业docx管道）
- 法律研究枢纽：`legal-research + yuandian-law-search + zhihe-legal-research` → `legal-research-hub`（3→1，多数据源统一入口）
- 法律文档摄入：`legal-text-format + wechat-article-fetch` → `legal-document-ingest`（2→1，抓取→格式化管道）
- 股票工作台：`stock-daily-analysis + claude-stock-fundamental-analysis + claude-stock-earnings-analysis + claude-stock-morning-note + claude-stock-dcf-valuation` → `stock-workspace`（5→1，技术面+基本面+估值合一）
- 合同审查：`contract-copilot + claude-commercial-contract-review` → `contract-review`（2→1，17脚本引擎+审查框架）

**累计**：两轮 32→11，总量 -66%。

### 跨技能吸收的权利与许可（Rights & Provenance）

跨技能吸收涉及两个独立的技能，必须尊重各自的权利来源。manifest 的 `relationships.donor_skills[]` 应记录以下字段以防止误伤原作者权益：

```json
{
  "donor_skills": [
    {
      "name": "baoyu-comic",
      "path": "/path/to/donor",
      "absorbed_capability": "Hermes prompt-only contract",
      "rights": {
        "license": "MIT",
        "provenance": "https://github.com/JimLiu/baoyu-skills",
        "absorbed_expression": false,
        "absorbed_category": "interface_contract"
      }
    }
  ]
}
```

| 字段 | 含义 |
|------|------|
| `license` | donor 的开源许可（MIT/Apache-2.0/AGPL-3.0 等） |
| `provenance` | donor 的原始来源 URL |
| `absorbed_expression` | 是否复制了受版权保护的表达性内容（代码、文本段落）；`false` 表示只吸收思想/流程/接口契约 |
| `absorbed_category` | 吸收内容的类型：`interface_contract`（接口契约）、`workflow_pattern`（流程模式）、`style_profile`（风格配置）、`runtime_adapter`（运行时适配） |

吸收精神：**优先吸收思想、流程和接口契约，避免直接复制受保护的表达性内容。** 如果必须复制代码或大段文本，`absorbed_expression` 设为 `true` 并在 RATIONALE.md 中说明合理性。

### 外部评估器集成（Evaluator Adapter）

sublation 的治理框架可以集成外部质量评估器（如 Darwin Skill、SkillLens）。核心原则：**评估器负责"变异和评分"，sublation 负责"晋升和生杀"。**

```
正式技能
  ↓ 只读观察
sublation 创建候选副本
  ↓
外部评估器对候选打分/提出优化建议（只读，不写）
  ↓
sublation audit 严审（评估报告作为参考证据，不替代 audit）
  ↓
Hermes/Codex 复核
  ↓
用户批准后晋升
```

**评估器适配的约束**：

1. **只能作用于候选副本**：评估器永远不能直接修改正式技能目录。如果评估器设计上会编辑文件，必须限制其工作在 `~/.hermes/sublation/candidates/<skill>/<candidate-id>/` 下。
2. **评分报告作为参考证据**：audit.py 可以引用外部评估器的评分报告作为晋升证据，但评分不能替代 audit 检查或交叉复核。
3. **运行时中立**：评估器不得硬编码特定平台的路径（如 `.claude/skills`），必须适配到 Hermes/Codex 的 skill root 相对路径。
4. **git 假设隔离**：评估器自带的 git 工作流不应与 sublation 的 rollback-points + manifest hash 回滚机制冲突。两套机制独立运行。

适用于：集成 `darwin-skill` 等外部评估器到 sublation 流程中。

## 实战案例

NPL monitor 三个闭环实验保存在 `references/`：

- `experiment-001-npl-cron-failure.md`: `spec-patch`
- `experiment-002-script-status-fixture.md`: `script-enhance`
- `experiment-003-cron-workdir-contract.md`: `infra-fix`

canghe-comic / canghe-article-illustrator / canghe-infographic 三连吸收（`cross_skill_absorption`，从 baoyu-* 吸收 Hermes prompt-only 适配经验）是第一种跨技能 sublation 样本。首例文档见 `references/cross-skill-absorption-canghe-baoyu-comic.md`。

以后不要让 NPL 继续占主线。新增实验使用 `references/experiment-template.md`，把具体技能当样本，不当框架本身。

## 系统健康扫描

定期系统健康扫描工作流见 `references/system-health-scan-workflow.md`。
