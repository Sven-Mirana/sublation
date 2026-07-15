---
name: skill-sublation
version: 3.0.0
description: 技能扬弃（Sublation/Aufhebung）——把执行经验沉淀为观测、候选、验证、独立复核、用户批准、晋升和观察窗的可审计治理链路；显式触发时可用 one-shot 控制面自动推进到用户决策门。
author: Sublation contributors
license: MIT
metadata:
  hermes:
    tags: [skill-governance, audit, review, promotion, loop-engineering]
    related_skills: []
---

# Skill Sublation v3.0

Sublation 是技能治理宪法，不是自动改技能的捷径。

它处理的核心矛盾是：Agent 会在执行中发现技能缺陷、边界裂缝和可吸收经验，但正式技能不能被即时、静默、无证据地改写。因此所有改进必须先进入候选层，用证据证明价值，再由用户守住生产门。

标准链路：

```text
Observation -> Candidate -> Validation -> Review-seat reports
-> Coordinator unified brief -> User decision
-> Promotion -> Observation window -> Closure
```

## 1. 宪法

### 1.1 三条根本原则

1. **所有 skill 开发都必须走 sublation 全链路**
   创建、修改、吸收、合并、拆分、删除、发布前清理，都必须留下观测、候选、审计、复核、用户决策、回滚和观察窗证据。小改动可以批处理，但不能绕过账本。

2. **sublation 必须自我扬弃**
   sublation 不是只管别人的治理工具。它自身也是被治理的对象。每次流程暴露裂缝，都要回流为框架改进，并记录在 `references/sublation-self-evolution.md`。

3. **不是管别人，是先被管**
   参与治理的 agent 在要求其他 skill 接受治理前，先接受同一套约束。默认本地席位是 Hermes、Codex、Claude Code；其他用户可以换成自己的 agent，甚至只用一个 agent。自报“已完成”不算证据；grep、read-back、diff、hash、audit、fixture 才算证据。

### 1.2 扬弃的判定

扬弃不是“又多一个候选”，而是旧能力被保留，同时出现可证明的正向增量：

- 能力更强或覆盖更广；
- 边界更清；
- 稳定性、安全性或可维护性更高；
- 治理质量提升；
- 旧 workflow 有 fallback 或明确的用户批准。

没有正向增量，最多记录 observation；退化不叫扬弃。

### 1.3 经验不是权威

任何 agent、外部评估器、benchmark、scorecard 都只能提供证据，不能替代用户决策。晋升权只属于用户，除非用户在当前任务中明确委托 Agent 执行已批准的低风险合入。

## 2. 硬边界

### 2.1 正式技能默认只读

Agent、cron、外部评估器不得自行修改 active skill path 下的 `SKILL.md`、`scripts/`、`schemas/`、`references/`。正式路径只能在用户明确批准晋升或回滚后被写入。

### 2.2 候选层自由

候选副本放在：

```text
~/.hermes/sublation/candidates/<skill>/<candidate-id>/
```

候选目录不得出现在 active profile 的技能搜索路径中。候选可以自由实验，但必须声明 scope/out_of_scope，并保持可回滚。

### 2.3 合法晋升模式

`validation.promotion_mode` 只允许：

- `human_patch`：用户手工合入；
- `user_delegated_agent_patch`：用户在当前任务中明确授权 Agent 合入；
- `rollback`：按 rollback point 或 manifest 恢复。

cron 最多创建观测、候选、报告和提醒；不能自动晋升。

### 2.4 删除和吸收

删除 donor skill、改 alias、改变 active profile、或把 donor 能力吸收到 umbrella skill，都必须有用户批准。候选层可以提出删除或吸收计划，但不能直接执行。

### 2.5 禁止的外部能力

外部评估器默认只读。发现以下能力必须阻断或隔离：

- optimizer 自动改写正式技能；
- iterative loop 写原始文件；
- sync/pull 覆盖本地正式目录；
- `load_skill` 或 active profile 注入；
- 读取、保存或转发用户凭据。

外部评估只进入报告，不进入 authority。

### 2.6 登录墙和 MCP 预留

需要登录、验证码或人工授权的数据源，采用 human-in-the-loop：

- Agent 可打开页面、定位控件、建立 provider contract；
- 用户手动输入凭据和验证码；
- Agent 不保存、不读取、不转发明文凭据；
- 状态用 `login_required`、`captcha_pending`、`mcp_placeholder` 等表示。

登录墙不是缺陷；保留 MCP 接口位置，不把它长期当作 PENDING 阻塞污染治理视图。

### 2.7 幻觉声明规则

任何“已写入”“已验证”“已晋升”“路径正确”的声明，都必须能被硬证据复验：

- `rg` / `grep`；
- `diff` / `git diff`；
- hash / tree hash；
- audit 输出；
- fixture / smoke test；
- read-back。

自报不能抵消证据缺失。

### 2.8 委托数据隔离

委托给外部模型、外部评估器或跨 Agent `delegate_task` 的上下文，绝不能包含本地文件内容、本地路径清单、案件隐私、客户数据、workspace 目录树或用户真实文件系统摘要。

正确做法是只传任务描述、候选 ID、抽象技术上下文和必要的非敏感参数；需要读取的文件由被委托方在其授权 session 中自行读取。事故背景见 `references/delegation-data-isolation-incident-20260527.md`。

### 2.9 候选共享根一致性

跨 Agent 协作时，候选的真相源是共享候选根：

```text
~/.hermes/sublation/candidates/<skill>/<candidate-id>/
```

Codex 工作区、Claude Code 临时目录或其他 agent 本地副本只能作为工作副本。任何修复报告必须说明修复发生在哪个 root、是否已同步共享根、共享根 audit/read-back 结果。Hermes 在确认候选状态前必须在共享根复跑，不得只接受 agent 自报。事故背景见 `references/candidate-layer-mirror-drift.md`。

## 3. 可配置协作席位

### 3.1 用户

用户是最终决策者，负责批准或拒绝晋升、删除、能力收缩、跨边界合并和正式路径写入。

### 3.2 Coordinator：统一传达席位

Coordinator 负责流程协调和统一传达。默认由 Hermes 担任；其他部署可以由任意 agent、脚本或用户本人担任。职责是：

- 收齐实现/审计报告；
- 收齐独立复核报告；
- 收齐业务/边界复核；
- 合并、去重、标注分歧和阻塞项；
- 用一份简报发给用户；
- 晋升后确认观察窗、回滚点和证据齐整。

默认 Hermes 办公室主任模式详见 `references/hermes-chief-of-staff.md`。

### 3.3 Implementer/Auditor：实现和审计席位

Implementer/Auditor 负责候选创建、代码/文档实现、PATCH.diff、manifest、审计修复、fixture、smoke test、回滚点和工程风险说明。默认由 Codex 担任；其他部署可以换成任意具备本地文件和审计能力的 agent。

### 3.4 Independent Reviewer：独立交叉验证席位

Independent Reviewer 负责从外部视角审读候选，重点找实现边界、反例、状态漂移、路径错配、未验证声明和回归风险。默认由 Claude Code 担任；其他部署可以换成任何未直接执行该候选改动的 agent。

### 3.5 Business/Boundary Reviewer：业务和边界席位

Business/Boundary Reviewer 负责判断 value_delta 是否真实、用户边界是否被侵蚀、权限/隐私/登录墙是否处理正确。默认由 Hermes 同时承担 coordinator 和业务/边界复核；其他部署可以拆给另一个 agent 或由用户本人复核。

### 3.6 单 agent 和少 agent 模式

如果用户只有一个 agent，不要伪装成三方独立：

- 在 manifest 中设置 `validation.review_policy.mode = single_agent`；
- 记录 `policy_authorized_by = user`，并提供 `authorization_message_id` 或 `authorization_report_path`；
- 把 `required_roles` 降为真实可执行的角色，例如 `combined_review`；
- `pre_promotion_reports[]` 只记录真实存在的 reviewer；
- 报告中明确写出“缺少独立交叉验证”的风险；
- 用户最终批准仍不可省略。

如果用户有多个但不是 Hermes/Codex/Claude Code，也用 `validation.review_policy.mode = configured_multi_agent` 声明实际席位、agent 名和最低报告数。非默认模式必须有用户授权证据；agent 不能通过自改 manifest 来降低自己的复核强度。`cross_reviewed_by = all` 在有 `review_policy` 时表示“所有配置为 required 的角色都已提供最新 approve 报告”，不是固定三元组。

### 3.7 群聊桥

协作桥可以是四方、三方、双方或单 agent 日志。桥只传递消息和状态，不授予晋升权。详见 `references/three-party-chat-bridge.md`。

### 3.8 Loop Engineering Protocol

Loop Engineering 把协作拆为 Builder、Independent Verifier、Boundary Reviewer 和 Approver 四类责任。实现者自报与独立核盘必须并列，统一简报只汇总已经落盘和可复验的证据。详见 `references/loop-engineering-protocol.md`。

### 3.9 V3 Automation

`scripts/loop_engineering.py` 读取候选、执行硬门禁、聚合证据和复核状态，并生成用户决策包。默认终点是 `USER_DECISION_REQUIRED`；它不得自动晋升、自动登录、自动处理凭据、自动修改 formal skill 或自动发布。

最小调用：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/loop_engineering.py \
  --candidate <candidate-dir> \
  --output-dir <validation-dir>
```

详见 `references/loop-engineering-v3-automation.md`。

### 3.10 V3 One-Shot

`scripts/sublation_one_shot.py` 只在用户明确说出 `sublation` 或“扬弃”时创建或恢复耐久 run。它连续推进 observe、candidate、audit、independent verify、rework、boundary review 和 aggregate，但只在正式晋升或其他受控动作前停到用户决策门。

V3 one-shot 的关键约束：

- 不改 PATH、provider、凭据、launchd 或 cron；
- Builder、Verifier 和 Reviewer 使用不同 actor 和可复验的执行边界；
- 只有 Builder 拥有候选写根，复核席位默认只读；
- 每个 evidence file 在账本中绑定路径和 sha256；
- 返工创建新 revision，不改写已被旧证据引用的候选；
- 报告、回执、批准 scope、baseline 和 candidate hash 相互绑定；
- 否定、暂缓或模糊授权一律 fail closed；
- 正式执行前生成回滚副本，失败时恢复并复验 baseline；
- 重试耗尽后只能进入 `BLOCKED`，Coordinator 不能替代独立席位提交 PASS。

入口与组件：

```text
sublation_one_shot.py      explicit-trigger entrypoint
sublation_run.py           durable run ledger and state machine
sublation_orchestrate.py   bounded worker orchestration
sublation_receipt.py       approval receipt verification
sublation_promote.py       approved-scope promotion and rollback
sublation_local_adapter.py local ephemeral adapter generation
```

完整契约见 `references/loop-engineering-v3-one-shot.md`；运行与 worker 配置分别见 `schemas/run-v1.json` 和 `schemas/worker-config-v1.json`。

## 4. 八步流程

### 4.1 Observe

写入结构化观测，说明触发事件、证据、分类和建议动作：

```bash
python3 scripts/observe.py <skill-name> \
  --skill-path <formal-skill-path> \
  --session <session-id> \
  --classification defect \
  --reflection-type SKILL_DEFECT \
  --step "<step>" \
  --status defect_suspected \
  --evidence "<hard evidence>" \
  --summary "<summary>" \
  --recommendation create_candidate
```

### 4.2 Gate

先判断是否值得建候选：

- 用户显式要求；
- 单次 critical defect；
- 同一步骤 >=3 次可信 defect；
- 明确的正向增量机会；
- 生产事故或治理账本缺口。

如果只是环境、cwd、权限、临时网络、登录墙或没有价值增量，优先记录 observation 或 provider contract，不急着建候选。

### 4.3 Candidate Copy

用候选脚本复制正式技能：

```bash
python3 scripts/candidate.py create <skill-name> \
  --source-path <formal-skill-path> \
  --candidate-type spec-patch \
  --agent codex \
  --observation <observation-id-or-summary>
```

不要手写只含部分文件的 `source_skill.files`。完整 source hashes 是回滚和 drift 检查的根。

### 4.4 Edit Candidate

只改候选目录。更新：

- `SKILL.md` / `scripts/` / `schemas/` / `references/` 中属于 scope 的文件；
- `RATIONALE.md`；
- `EVIDENCE.md`；
- `manifest.json`；
- `PATCH.diff`。

明确写出 `scope.changes` 和 `scope.out_of_scope`。

### 4.5 Validate

验证只用 fixture、临时副本、合成输入和 dry-run。禁止把验证写进真实用户数据或正式技能目录。

必跑：

```bash
python3 scripts/audit.py <candidate-dir> --json
find <candidate-dir> \( -name '__pycache__' -o -name '*.pyc' -o -name '*.pyo' \) -print
```

跨 Agent 候选还必须在共享候选根复跑同一组检查，确认工作区副本和共享根没有漂移。

涉及代码时，还要跑语法、单元、smoke、回归和业务最小路径。

### 4.6 Review-Seat Reports

晋升前必须有配置中要求的复核意见。默认本地配置需要三类证据：

- `implementation_audit`：实现、审计、回滚、工程风险；
- `independent_review`：独立反例、边界、回归风险；
- `business_boundary`：业务价值、用户边界、流程合规。

2026-06-11 后进入 `approved`、`promoted`、`observation_window`、`closed` 的候选，manifest 必须记录 `validation.pre_promotion_reports[]`。报告可以有分歧；分歧本身也是证据。其他部署应在 `validation.review_policy` 中声明实际席位，而不是把不存在的 Hermes/Codex/Claude Code 硬填进去。

### 4.7 Coordinator Unified Brief

Coordinator 收齐配置中要求的报告后，只向用户发一份统一简报。其他 agent 不再各自给用户重复汇总。详见第 5 章。

### 4.8 Promote and Observe

用户批准后才可晋升。晋升前必须建 rollback point；晋升后必须更新 manifest：

- `validation.status = observation_window`
- `validation.promoted_by`
- `validation.promoted_at`
- `validation.formal_post_promotion`
- `validation.post_promotion_safety`

观察窗至少需要一次真实调用、一个生产周期、或用户/配置复核席位确认目标已达成，才能闭合。

## 5. 统一晋升汇报

### 5.1 原则

旧方式：多个 agent 各自向用户汇报，用户看多份重复内容。

新方式：配置中的复核席位各自评估，但最终面向用户的晋升建议由 coordinator 汇总为一份简报。

这只改变呈报方式，不改变治理权力：

- 配置中的复核席位仍各自报告；
- evidence-not-authority 不变；
- 用户最终决定不变；
- 无用户批准不 formal promotion；
- value-delta gate、rollback、observation window 不变。

### 5.2 简报模板

Coordinator 给用户的统一简报建议不超过一屏：

```text
候选：<candidate-id>
目标：<one-line goal>

复核结论：
- <role>/<agent>：APPROVE / HOLD / REJECT — <one-line reason>
- <role>/<agent>：APPROVE / HOLD / REJECT — <one-line reason>
- <role>/<agent>：APPROVE / HOLD / REJECT — <one-line reason>

价值增量：<positive delta summary>
主要风险：<top risks or "none beyond observation window">
阻塞项：<blocking issues or "none">
回滚：<rollback readiness>
建议动作：请用户批准晋升 / 要求修订 / 暂缓 / 拒绝

证据位置：manifest / audit report / report message ids
```

### 5.3 分歧处理

任一 required role HOLD 或 REJECT 时，coordinator 不粉饰分歧：

- 如果是可修复实现问题，交回 implementer/auditor 修；
- 如果是价值或边界问题，呈报用户裁决；
- 如果最新报告从 HOLD 变 APPROVE，manifest 保留历史 HOLD，但 audit 以同一 reviewer 最新有效结论为准；
- user/external 记录可以作为 info 并存；是否计入 `cross_reviewed_by = all` 由 `validation.review_policy.required_roles` 决定。

## 6. 候选生命周期

### 6.1 状态

`validation.status`：

- `draft`
- `validated`
- `review_pending`
- `approved`
- `promoted`
- `observation_window`
- `closed`
- `rejected`

`observation_window` 不是完成态。闭合前必须记录：

- `closed_at`
- `closure_reason`
- `closure_evidence[]`
- `closure_reviewed_by`
- `closure_policy`

### 6.2 候选类型

- `spec-patch`：只改文档、schema、流程说明或规则文本；
- `script-enhance`：改脚本逻辑；
- `infra-fix`：修调度、路径、配置、运行环境；
- `tooling`：新增或修改治理工具。

spec-patch 不等于低风险；如果改变晋升规则、删除能力或扩大权限，仍需配置中要求的复核报告和用户批准。

### 6.3 Manifest v3 要点

关键字段：

- `source_skill.path/tree_hash/files`
- `candidate.path/tree_hash/files`
- `rollback_hashes`
- `scope.changes`
- `scope.out_of_scope`
- `relationships`
- `rights_provenance`
- `validation.value_delta`
- `validation.empirical_scorecard`
- `validation.pre_promotion_reports[]`
- `validation.review_policy`
- `validation.formal_post_promotion`
- `validation.post_promotion_safety`

常见枚举：

- `cross_reviewed_by`: `none | hermes | codex | both | claude-code | all | configured | user-waived`
- `promotion_mode`: `none | human_patch | user_delegated_agent_patch | rollback`
- `empirical_scorecard.status`: `measured | not_applicable | not_measured`
- `relationships.sublation_pattern`: `single_skill_patch | cross_skill_absorption | skill_merge_plan | skill_split_plan`

`validation.review_policy` 可声明默认三 agent、多 agent 替代、单 agent 或用户豁免模式。没有该字段时，audit 保持本地默认三席：`claude-code`、`codex`、`hermes`。任何非默认模式必须记录用户授权证据。

完整 schema 见 `schemas/manifest-v3.json`。


### 6.4 决策历史与非作者复跑

2026-06-11 后的新候选应把复核、修订和观察窗学习写成可追溯因果链：

- `validation.decision_history[]`：记录 `diagnosis -> action -> evidence -> outcome`，并用 `trigger.id` 链接报告、审计、用户决定或观测。
- `validation.independent_reproduction`：晋升前至少一名非作者复跑。初始门槛为一人；若再次出现镜像漂移或复核逃逸事故，再提高到两人。
- `validation.rejected_alternatives[]`：只记录有意义的设计分叉、spec-patch、吸收、review conflict 或 routing 取舍；小修小补不强制。
- `redacted_reporting`：在 manifest 顶层标注可共享证据与本地敏感上下文，登录墙、cookie path、page body、用户数据等不得直接进入用户简报。

`observation_window` 的后续学习也写入 `decision_history[]`，使用 `phase: observation_window`，不要另造平行四元组。缺少 `decision_history[]` 的 post-rule 晋升候选先给三个月 warning 过渡，再升级为 hard fail。

### 6.5 Strict Audit

默认 `audit.py` 是 strict。晋升前不要用 `--no-strict` 逃避问题。重点检查：

- 候选不在 formal path；
- 无 bytecode；
- PATCH.diff hunk header 合法；
- source baseline 未漂移；
- formal_post_promotion 当前；
- manifest 自洽；
- rights/provenance；
- post-promotion safety；
- empirical scorecard；
- value_delta；
- pre_promotion_reports。

### 6.6 顺序晋升和漂移

同一 skill 的多个候选依次晋升时，后一个候选可能改变前一个候选记录的正式快照。观察窗内候选出现 `formal_post_promotion` drift 必须解释：刷新快照、缩小检查范围、闭合观察窗或创建治理候选。不要为了消除 warning 回滚已批准的正向晋升。

### 6.7 候选层镜像漂移

候选层也会发生路径错配。工作区 audit passed 不等于共享根 audit passed。进入 coordinator unified brief 前必须确认：

- workspace candidate 与 shared-root candidate 的关键文件一致；
- shared-root candidate 也能通过 strict audit；
- **audit report 的 `candidate_path` 必须指向共享根，而非 agent workspace**——如果 audit report 里的 `candidate_path` 是 Codex/Claude Code 的本地工作区路径，说明该 audit 从未在共享根上跑过，不得采信为"共享根已通过"；
- `PATCH.diff` 能在当前 formal baseline 上 dry-run/apply-check；
- 删除文件不会留下零字节空壳；
- 报告中的 line count、hash、audit 数字来自实测。

这条是 post-promotion strong path check 在候选层的等价护栏。

**常见漂移模式**：agent 在工作区删除 `__pycache__`/`.pyc` 后跑 audit → audit passed，同步到共享根时遗漏了删除动作 → 共享根 audit 仍显示 passed（如果 audit script 的 bytecode 检测不覆盖该路径），但 `find` 仍能找到残留字节码。检测方法：`find <shared-root> \( -name '__pycache__' -o -name '*.pyc' \) -print`，不应依赖 audit 的 `no_bytecode_artifacts` 单点。

## 7. 设计模式

### 7.1 Provider Contract

数据源技能必须区分：

- `ok`：数据源正常；
- `empty`：正常为空；
- `blocked`：来源阻断；
- `login_required`：需要人工登录；
- `captcha_pending`：需要用户完成验证码；
- `disabled`：明确停用；
- `mcp_placeholder`：预留接口，不追踪为缺陷。

参考 `references/provider-contract-pattern.md` 和 `references/human-in-the-loop-login-wall.md`。

### 7.2 Cross-Skill Absorption

吸收不是吞并。target 吸收 donor 的局部优势，同时保留 target 的主结构和 donor 的关键能力。必须记录：

- donor skill；
- absorbed capability；
- retained boundary；
- rights/provenance；
- fallback；
- 用户批准删除或 alias 改动。

参考 `references/cross-skill-absorption-canghe-baoyu-comic.md` 和 `references/absorbed-target-routing.md`。

### 7.3 Skill Merge and Split

合并候选必须证明：

- 合并后入口更清；
- 旧 workflow 有映射；
- 能力没有静默收缩；
- donor 删除另行批准；
- 观察窗可以覆盖主要路径。

拆分候选必须证明拆分降低复杂度，而不是制造更多治理对象。

### 7.4 Spec-Only Candidate

纯文档候选也要有价值增量。典型用途：

- 补治理账本；
- 明确边界；
- 归档过时经验；
- 更新汇报/复核流程；
- 将分散规则收束到 reference。

### 7.5 External Evaluator Adapter

外部评估器只能读候选、产报告、给风险评分。禁止安装时写 formal skill，禁止 optimizer/sync/load_skill 自动落地。参考 `references/external-evaluator-adapter-agent-insight.md` 和 `references/darwin-evaluator-adapter.md`。

### 7.6 Business Smoke Test

框架 audit 全过只证明结构正确，不证明业务可用。晋升后必须跑业务烟雾测试，至少覆盖：

- 合约章节存在；
- workflow 步骤完整；
- 关键能力字面保留；
- 正/负 fixture；
- 真实路径最小调用。

参考 `references/business-smoke-test-pattern.md`。

### 7.7 Upstream Sync

对外部来源或上游 repo 做 sublation 前，先确认本地不是旧版本。`hermes skills update` 对 local source 返回 No updates 不代表最新。需要 clone/diff/rollback 证据。参考 `references/upstream-skill-sync-methodology.md`。

### 7.8 发布前清理

发布到 GitHub 或公开分发前，必须清理：

- `__pycache__`、`.pyc`、`.orig`；
- 个人路径和内部样本；
- 过时候选；
- 未入账正式漂移；
- README、LICENSE、audit report。

参考 `references/github-release-checklist.md`、`references/pre-release-audit-pattern.md`、`references/github-release-workflow.md`。

## 8. V3 发布验证

- [ ] `SKILL.md` frontmatter 与 Markdown 链接有效；
- [ ] `scripts/test_*.py` 全量通过且不生成 bytecode；
- [ ] 候选目录已通过 `scripts/audit.py --strict`，发布目录已通过 `scripts/release_audit.py`；
- [ ] `schemas/manifest-v3.json`、`schemas/run-v1.json`、`schemas/worker-config-v1.json` 可解析；
- [ ] one-shot 未经显式触发时 fail closed；
- [ ] 自动化停在用户决策门，不自行晋升；
- [ ] formal root、候选、run 账本和 rollback root 的写边界彼此隔离；
- [ ] release 包不含个人绝对路径、凭据、会话、候选正文或内部聊天记录；
- [ ] `PACKAGE-MANIFEST.json` 与 `checksums.sha256` 已按最终文件重新生成。
