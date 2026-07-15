# Loop Engineering Protocol

四方协作的结构化工程控制面协议。它把普通群聊收束成可审计的工程闭环：intent -> candidate/spec patch -> execution -> verification -> review -> user decision -> observe/rollback。

## 适用范围

适用于会改变技能、候选、自动化、MCP、cron、provider、发布流程或长期协作规则的任务。普通问答、一次性解释、只读查询不需要启动完整 loop。

Loop 是 Sublation 的执行层细化。Sublation 管“扬弃什么”，Loop 管“怎么执行扬弃”。Loop 不能绕过 Sublation 的候选、审计、复核、用户批准、回滚和观察窗纪律。

## 角色划分

| 角色 | 默认席位 | 职责 |
|------|----------|------|
| Approver | user | 目标设定、边界定义、最终裁决、正式晋升授权 |
| Builder | Codex | 主执行：candidate 创建、patch 落地、代码修改、evidence packet 整理 |
| Verifier | Claude Code | 独立核盘：manifest、diff、audit、runtime/service、tree/hash、真实文件状态 |
| Reviewer/Historian | Hermes | 流程纪律、历史对照、风险提醒、Sublation 合规、统一简报 |

任何席位的 PASS、APPROVE、同意、建议都只是 evidence，不是 user 授权。

## 状态机

| 状态 | 含义 | 默认动作 |
|------|------|----------|
| PROPOSED | 任务或改进被提出，scope/out_of_scope 已初步描述 | 等待 builder 建候选或用户收窄边界 |
| BUILT | builder 已创建候选、patch 或实现，并给出自证 evidence | 进入独立 verification |
| VERIFIED | verifier 独立从磁盘或运行态复验通过 | 进入 reviewer/historian 复核 |
| REVIEWED | reviewer/historian 已给出风险、历史对照和统一简报 | 等待 user decision |
| BLOCKED | 必要证据缺失、patch 不适配、source 不可达、权限/登录/根分叉等阻断 | 默认停手，不降级硬做 |
| PARTIAL | 只有部分 root、部分测试、部分 provider 或部分证据通过 | 明确剩余缺口，等待用户决定是否分阶段推进 |
| APPROVED | user 明确批准某一 scope 的晋升、执行或 live validation | 按批准范围执行，不扩张 |
| OBSERVING | 已进入 observation window，记录 rollback、runtime、baseline、异常和关闭条件 | 只按观察窗规则推进或回滚 |

`BLOCKED` 与 `PARTIAL` 是一等状态。不能把它们包装成成功，也不能因为一个 root 通过就强打另一个 root。2026-06-26 双根晋升中 Claude root patch 不适配时，正确动作是停手、报告、等待 user 决定。

## Gate Discipline

1. promote、live validation、formal skill 写入、删除、alias-rewrite、credential/login、外部发布，都需要 user 明确 decision。
2. 默认状态是 review_pending / candidate-only，除非 user 明确推进。
3. agent 不得把转述当作用户授权执行操作。
4. helper script、template、自动化本身也是 tooling 候选，必须走同一套 loop，不能因为“用于治理”就绕过治理。
5. 任何“已写入”“已验证”“已晋升”“路径正确”的声明，都必须可被 read-back、diff、hash、audit、fixture、smoke test 复验。

## 执行闭环

```text
user intent/task
  -> Codex builds candidate/spec patch
  -> Claude Code verifies from disk/runtime
  -> Hermes reviews risk/history and prepares unified brief
  -> user decides
  -> Codex executes approved scope
  -> Claude Code post-verifies
  -> Hermes observes/records
  -> observation window closes or rollback is triggered
```

## 独立核盘硬约束

Verifier 的 PASS 只在“独立从磁盘或运行态回读”后成立。

- manifest/diff/audit：Verifier 自己读取共享候选根，自己运行 audit 或 apply check，不引用 builder 报告的数字。
- runtime/service：Verifier 自己探活，例如进程、端口、HTTP health、UI snapshot、fixture 结果，不引用“已重启”“已运行”的口头声明。
- 文件状态：Verifier 自己列出 `files_actually_read`、changed paths、tree/hash、per-root apply 结果。
- 一次一核：不同 root、不同 provider、不同候选分别核，不批量盖章。
- 自报不能抵消证据缺失。若不能独立复验，结论必须是 `BLOCKED` 或 `PARTIAL`。

## Evidence Packet 最小结构

每个 loop 至少保留以下证据字段；可以写入 manifest、REPORT、群聊消息或 Hermes 统一简报，但必须能回指到具体文件和消息。

```json
{
  "loop_id": "YYYYMMDD-short-topic-agent",
  "intent": {
    "user_message_id": "message-or-thread-id",
    "goal": "what changes",
    "boundaries": ["candidate-only", "no formal write"],
    "out_of_scope": ["credentials", "live scraping", "promotion"]
  },
  "builder_evidence": {
    "agent": "codex",
    "candidate_path": "...",
    "patch_diff": "PATCH.diff",
    "changed_paths": [],
    "audit_report": "...",
    "tool_versions": {},
    "self_report": "short summary"
  },
  "verifier_evidence": {
    "agent": "claude-code",
    "files_actually_read": [],
    "per_root_apply": [],
    "tree_hashes": {},
    "audit_results": [],
    "runtime_probes": [],
    "verdict": "PASS|BLOCKED|PARTIAL"
  },
  "reviewer_evidence": {
    "agent": "hermes",
    "historical_comparison": [],
    "risk_report": [],
    "unified_brief_path_or_message": "..."
  },
  "decision": {
    "by": "user",
    "status": "approved|hold|reject|needs_changes",
    "message_id": "..."
  },
  "observation": {
    "rollback_point": "",
    "acceptance_conditions": [],
    "close_or_rollback_evidence": []
  }
}
```

Builder 字段与 verifier 字段必须并列呈现。user 应能一眼看出“实现者自报”和“独立核盘”是否对得上。

## Historian 职责

每次 decision 关口前，Reviewer/Historian 必须对照上一次同类 decision 的 outcomes、rollbacks、事故或长期后果：

- 上次类似决定导致了什么结果？
- 是否出现过 drift、噪音、误报、权限扩张、root 分叉、候选共享根不一致？
- 本次是否需要更窄 scope、更长观察窗、更强 rollback 或更多证据？

历史对照只提供 evidence，不替代 user 裁决。

## 统一简报

避免每个 agent 分别向 user 呈报造成重复和口径不一致：

1. Codex 执行或建候选后提供 builder evidence。
2. Claude Code 独立核盘后提供 verifier evidence。
3. Hermes 复核风险、历史和流程纪律。
4. Hermes 汇总三方 evidence 成一份统一简报。
5. user 基于统一简报一次决定。

如果 Hermes 简报与磁盘证据冲突，以磁盘证据为准，并在群聊更正。

## Evidence-First 用户报告协议

当 loop 需要向 user 报告进度、结论、交付状态，或包含文件/磁盘/仓库/服务事实断言时，先走 evidence-first 报告协议。这个协议不是额外审批层；它是防止事实错报进入用户界面的执行层门槛。

适用：

- 进度/状态报告；
- 交付报告；
- 统一简报；
- 对 candidate、manifest、diff、audit、git、服务健康、候选共享根状态的结论；
- 会影响 user 是否批准晋升、同步、回滚或继续批处理的事实判断。

不适用：

- 例行 ACK；
- 简短 @回复；
- reviewer 初步意见；
- 提醒某个 agent 去补证据；
- 不含文件/磁盘事实断言的一般讨论。

### DRAFT -> Confirm -> Final

1. **DRAFT**：先在群聊发布草稿，标题明确写 `DRAFT`。每条事实断言必须带 evidence anchor。
2. **Confirm**：Codex 和 Claude Code 逐条确认事实断言。Hermes 不得把沉默当成同意；Codex/Claude 也不应把 routine ACK 变成不必要的阻塞。
3. **Final**：只有被确认的事实可进入给 user 的终版报告。未确认项保持 `unverified`、`PARTIAL` 或 `needs_provenance`。

最低 evidence anchor：

- `command`：实际跑过的命令；
- `key_output`：支撑结论的关键输出行；
- `path`：manifest、audit、PATCH.diff、报告或候选路径；
- `message_id`：群聊事实来源；
- `status_term`：使用 `CLOSED`、`PARTIAL/needs_provenance`、`USER_DECISION_REQUIRED` 等状态词时的证据来源。

示例结构：

```text
DRAFT:
- 事实：shared candidate audit passed
  evidence: `PYTHONDONTWRITEBYTECODE=1 python3 .../audit.py <candidate> --strict --json`
  key_output: `"auditor_status": "passed"`
  path: `~/.hermes/sublation/candidates/.../validation/audit-report-...json`
```

### 状态词约束

- `CLOSED`：只能用于磁盘/运行态证据存在，且三方确认闭合的事项。
- `PARTIAL/needs_provenance`：来源、root、diff、审计或 reviewer 链路不完整；这不是失败，但不能包装成闭合。
- `REVIEW_REQUIRED`：候选已可复核，但 reviewer evidence 未齐。
- `USER_DECISION_REQUIRED`：所有必要 evidence 已足够支撑用户裁决；仍然不能自动晋升。
- `PASS/APPROVE`：只是复核证据，不是 user 批准。

### 脏仓库和同步建议

涉及 `git pull`、stash/pop、sync、upstream merge、重复 clone 合并等建议时，默认只读。任何执行建议必须先给出：

1. 本地变更导出或保护方案；
2. upstream touch-set 或影响面；
3. 冲突预测依据；
4. 出错回滚路径；
5. 是否需要 user 明确批准。

没有这些证据时，结论只能是 `PARTIAL/needs_provenance` 或 `read-only recommendation`，不能写成 `CLOSED`、`safe to pull` 或 `冲突概率低`。

## Signal Discipline

Loop 控制面必须防噪音。群聊不是心跳垃圾桶。

- 无活动任务、无状态变化、无待决策事项时，不发送例行“无新消息”“一切正常”。
- 有活动任务时，可按任务需要轮询；连续两轮没有 task-flow 变化后停止自动询问，直到出现新消息、新候选、新 review、新 blocker 或用户指令。
- NPL 日报最多一天一次；cron 每轮状态不得刷屏。
- 每条自动状态消息应带 task fingerprint 或 change summary；相同 fingerprint 默认静默。
- 只有状态跃迁、证据更新、异常、阻塞、需要 user 决策、需要其他席位复核时才发言。

重复消息本身是控制面故障，应进入 observation 或 remediation。

## 群聊桥边界

四方群聊桥是通信基础设施：http://127.0.0.1:8787/

桥只传递消息和状态，不授予晋升权，不扩大文件权限，不授权 credential/login，不授权 live validation。桥恢复只代表通信恢复，不代表任务完成。
