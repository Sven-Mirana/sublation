# Loop Engineering v3 One-Shot Orchestrator

这一层把“把现有技能 sublation 一下吧”变成可恢复的批量运行。用户只负责在开头明确发起扬弃，并在结尾决定是否晋升；中间的观察、候选、审计、独立核盘、返工、边界复核、报告汇总和终报投递由配置好的 agents 自主推进。

它不扩大晋升权限。编排器的最高自动状态是 `USER_DECISION_REQUIRED`，回执解释器的最高自动状态是 `APPROVED_PENDING_EXECUTION`。后者只表示精确授权范围已解析并留证，不等于已经写入正式 skill root。

## 1. 显式入口与确定性范围

One-shot run 必须由显式触发词启动：

- 意图中必须出现 ASCII `sublation` 或中文“扬弃”；
- “检查一下现有技能”“看看有哪些技能”等未带触发词的请求直接拒绝，不把普通盘点升级成治理运行；
- 明确出现一个或多个 configured root 名称时，只处理这些 roots；
- “现有技能”“全部技能”“所有技能”等泛指语句，在已有显式触发词的前提下处理全部 configured roots；
- 未点名 root、但明确要求 sublation/扬弃时，也处理全部 configured roots；
- “深度”“跨技能”“安全”“权限”“供应链”等词把 detail 从 `standard` 升为 `deep`。

解析结果写入 `run.json.scope` 并带 revision。范围不能由 adapter 自行扩张。

默认本机入口是一条命令；未显式传 root 时自动发现已有 Hermes、Codex、Claude Code skill roots：

```bash
python3 scripts/sublation_one_shot.py \
  --intent "把现有技能 sublation 一下吧"
```

需要覆盖默认值时再传 `--root NAME=PATH`、`--roots-file` 或具体 CLI 路径。相同意图若存在尚未生成报告的健康 run，入口自动恢复该 run；已完成的旧 run 不会被误复用。

生产环境也可以用 `--roots-file` 传入 `{name,path}` 数组。启动器枚举每个选中 root 下的真实 `SKILL.md`，每个技能获得稳定的 `A1/A2/...` 编号；namespace 下的嵌套技能单独入账。它按每个 root 最近一次已经生成报告的 inventory 建基线，只为新增、修改、删除或 root-missing 项建任务。窄范围 run 不覆盖其他 root 的增量基线。

## 2. 耐久账本与任务队列

每轮运行至少包含：

- `run.json`：可恢复状态、configured roots、scope revision、稳定项目编号、steps、tasks、报告和批准摘要；
- `journal.jsonl`：append-only hash chain + per-run HMAC，保存运行快照以及 task、step、报告、投递、回执和晋升事件；
- `.control/run-attestation.key`：权限为 `0600` 的每-run HMAC key；worker sandbox 明确禁止读取；
- `report-vN.json` / `report-vN.md`：机器报告和 Hermes 可直接发送的人话报告；
- `approval.json`：解析后的用户事件、逐项决定和授权范围，它不是独立权威源；
- `worker-io/`：每个 task lease 使用独立子目录保存 request、response、只读 source snapshot 和私有 TMPDIR；
- `delivery-io/`：按 report material 保存 delivery request、response 和 adapter evidence；
- `receipt-io/`：保存由可信 channel adapter 从原始用户事件生成的 HMAC 回执证据。

状态更新使用文件锁、原子替换、HMAC journal 和快照。`run.json` 与同 revision journal snapshot 内容不同即拒绝；只在 journal revision 更新时自动恢复落后快照。相同 `(run_id, step_id)` 与相同 payload 重放时幂等；复用 step id 提交不同 payload 时拒绝。每个阶段都有 durable task，保存 role、actor、attempt、lease、dispatch 和 result step。整个 runner 还持有非阻塞 `.orchestrator.lock`，第二个进程不能复用同一 lease 并发调用 worker。

```bash
python3 scripts/sublation_run.py status \
  --run-dir ~/.hermes/sublation/runs/<run_id>
```

`status` 会复验 journal hash chain，并显示下一阶段和等待中的 actor。

## 3. 三席独立与单代理例外

默认映射是：

```text
builder=codex
independent_verifier=claude-code
reviewer=hermes
coordinator=hermes
```

`builder`、`independent_verifier`、`reviewer` 必须由三个不同 actor 承担。worker config 还必须为每席声明 `principal_id`、`write_roots`、`read_roots` 和 `network_access`；控制面从 argv、cwd 与这些能力边界计算 `adapter_fingerprint`。只有 builder 可绑定候选写根，independent verifier/reviewer 的 write roots 必须为空。三席 principal、adapter fingerprint 与能力绑定首次写入 run 后不可替换；每个 task result 同时记录并复验 actor、principal 和 fingerprint。`candidate_path` 必须位于 builder 的候选写根内，不能落在 durable run 或正式 root。coordinator 可以和 reviewer 同席，因为 coordinator 只负责汇总/阻塞收口；重试耗尽后它不能替代原独立席位提交 PASS。

使用 `--role ROLE=ACTOR` 改名后仍要满足三席独立。只有用户针对当前 run 明确授权降低独立性，才可加 `--allow-single-agent`。账本必须记录：

```json
{
  "mode": "user_authorized_single_agent",
  "independence_required": false,
  "single_agent_user_authorized": true
}
```

没有该显式授权时，重复 actor 配置 fail closed。单代理结果不能表述为独立复核。

## 4. macOS worker 与 delivery 隔离

`scripts/sublation_orchestrate.py` 只接受 argv 数组，不经过 shell。worker 与 delivery adapter 都必须经过 macOS `sandbox-exec`。每次调用动态生成 profile，先禁止全部文件读取与写入，默认禁止网络，再只放行运行时、当前 lease I/O、只读 source/candidate snapshot、显式 read roots、builder 候选写根和 `/dev`。父进程环境只继承 PATH/locale/timezone/user/shell 白名单，每个 task 使用独立 HOME/TMPDIR：

```text
(deny file-read*)
(deny file-write*)
(deny network*)
(allow file-write* (subpath "<current-task-io>"))
(allow file-write* (subpath "<bound-candidate-root>"))
(allow file-read* (subpath "<source-snapshot>"))
(allow file-read* (subpath "<candidate-snapshot>"))
(deny file-write* (subpath "<configured-formal-root>"))
(deny file-write* (literal "<task-request>"))
(deny file-write* (subpath "<source-snapshot>"))
(deny file-read* file-write* (subpath "<run>/.control"))
```

保护范围不是“当前 item 一个目录”，而是整个 configured root 集合、durable run 账本、live candidate 和宿主其他文件。worker request 中的 `target_path` 被替换为 lease-local source snapshot；audit/verify/review 还只接收 lease-local candidate snapshot，候选 evidence path 同步改指快照，正式路径与 live candidate 不作为模型任务字段暴露。两类 snapshot 都保留 symlink identity。控制面在 worker 前后比对 formal、live candidate、request 与 snapshot hashes。配置 read/write root 与 run/formal/home/filesystem root 重叠时，在 claim task 前 fail closed。

这是 fail-closed 门禁：

- 非 macOS 环境、找不到 `sandbox-exec`、profile 无法应用或 adapter 不能在沙箱内运行时，不允许无沙箱降级；
- adapter nonzero、超时、response 缺失或任一 immutable tree hash 漂移按 retry/coordinator/blocker 留证；coordinator 只能把耗尽任务收口为 `BLOCKED`，不能代替原角色 PASS；
- 任何未经用户批准的正式写入都不能被视作合法候选结果。

候选自带 `sublation_local_adapter.py`，可在 run 目录生成临时 worker/delivery config，并发现本机可工作的 Codex、Claude Code、Hermes CLI；它不会改 PATH、launchd/cron、provider 或凭据。Codex 使用 ephemeral + ignore-user-config，Claude Code 使用 safe-mode + no-session-persistence，Hermes 使用 safe-mode + oneshot；外层 sandbox 仍是最终写边界。若用户另选常驻进程、固定配置或新凭据接线，那些仍属于持久控制面，需 user 对当前范围明确批准。

## 5. 阶段推进与状态耦合

默认阶段为：

1. `observe`：读取当前 skill、历史 observation 和触发证据；
2. `candidate`：创建隔离候选，或判定 report-only/no-op；
3. `audit`：复验 manifest、scope、patch、hash、价值增量和边界；
4. `independent_verify`：由非 builder 从共享候选复跑；
5. `candidate_rework`：HOLD/FAIL 自动回到候选层；每次复制上一候选到新的不可变 revision 路径后修订，旧证据目录不得原地改写；
6. `boundary_review`：核对价值、权限、隐私、登录、live action 和 rollback 边界；
7. `aggregate`：全部项目终结后汇总一次报告。

`step_status` 与 `item_status` 强耦合：

| 结果类型 | 允许的 `step_status` | 典型 `item_status` |
| --- | --- | --- |
| 正向推进 | `pass` | `OBSERVED`、`CANDIDATE_READY`、`AUDIT_PASSED`、`VERIFY_PASSED`、`REVIEW_PASSED`、终态成功 |
| 候选返工 | `hold` 或 `fail` | `REWORK_REQUIRED` |
| 事实性阻塞 | `blocked` 或 `fail` | `BLOCKED` |

phase 还有自己的允许状态集合。`pass + REWORK_REQUIRED`、`hold + VERIFY_PASSED`、跨 phase 跳态等组合均拒绝。

每个正向 step 必须提交至少一个真实 evidence file。CLI 接受路径，账本保存为：

```json
{
  "path": "/absolute/run-or-candidate/path/evidence.json",
  "sha256": "sha256:..."
}
```

证据必须真实存在，并位于 run root 或该 item 的 candidate root 内；边界外路径拒绝。记录时计算 sha256，finalize 前重新读取并校验。缺失文件、被改写的 hash、伪路径或没有 task/result 绑定都会阻断终报。

## 6. 自动 worker loop

默认入口自动发现本机 Codex、Claude Code、Hermes CLI，为当前 run 生成 `local-worker-config.json`，然后连续运行 worker loop：

```bash
python3 scripts/sublation_one_shot.py \
  --intent "把现有技能 sublation 一下吧"
```

临时配置只写在 run 目录内，不进入 PATH、launchd/cron、provider 或凭据配置。Codex 使用 app 内置或显式指定的 `codex exec --ephemeral --ignore-user-config`，Claude Code 使用 safe-mode/print/json-schema/no-persistence，Hermes 使用 safe-mode oneshot。三者都必须返回同一机器 schema；CLI 自报不是控制面证据，runner 仍会复验 task lease、principal/fingerprint/write roots、evidence hash、formal tree hash、不可变 task input 和状态转换。

也可以显式提供已经批准的 config：

```bash
python3 scripts/sublation_orchestrate.py \
  --run-dir ~/.hermes/sublation/runs/<run_id> \
  --worker-config /approved/local/worker-config.json
```

配置必须同时包含 `workers` 和 `delivery`。worker argv 使用 `{request}`、`{response}`；delivery argv 可使用 `{request}`、`{response}`、`{report}`。`read_roots` 与 `network_access` 必须显式声明并进入 adapter fingerprint，缺省网络为 deny。Runner 自动执行 claim → sandboxed adapter → response validation → evidence capture → record → next task。verify/review 的 HOLD/FAIL 自动派生新的不可变 `candidate_rework` revision，不向用户抛中间选择。候选没有安装常驻服务，也没有真实调用本机三个模型 CLI；builder 验证只覆盖可执行文件发现、实际 `--help` 旗标核对和完全离线的 fake-CLI E2E。真实模型调用属于运行时行为，必须受当时的凭据、网络和当前范围约束。

项目最终收敛到：

- `APPROVAL_READY`：三席证据齐全，需要用户批准正式晋升；
- `CLOSED_REPORT_ONLY`：报告或规范证据已闭环；
- `CLOSED_NOOP`：无需变更；
- `BLOCKED`：当前边界内无法解决的事实性阻塞。

只要还有非终态 item、活动 task、缺失 role/result/evidence 或 hash 漂移，`report` 就拒绝 finalize。`APPROVAL_READY + BLOCKED` 生成 `PARTIAL`，只允许批准报告中明确列出的 ready 项。

## 7. Material-idempotent 单报告

终报的 `material_hash` 由 scope revision、run state、items、approval items 和 boundary 计算。重复 finalize 时：

- material 未变，返回现有同一 report version/hash，不生成伪 `report-v2`；
- material 真正变化，才允许生成下一版本；
- 现有 report hash 无法复验时直接拒绝。

因此“单报告”指同一材料只对应一份终报，而不是禁止有证据变化后的显式新版本。

## 8. Hermes delivery adapter 与回执绑定

全部 item 终态后，runner 自动调用配置中的 delivery adapter，不要求人工再执行 `deliver`。delivery adapter 必须：

- `actor` 等于 run 的 coordinator，默认是 Hermes；
- 发送 `report-vN.md` 的唯一人话终报；
- 返回 configured sender actor、真实 `message_ref`、`report_body_hash` 和完整通道文本 `delivery_text_hash`；
- 使用由 report version/hash 派生的 idempotency key；
- 把 response 保存为 `{path, sha256}` adapter evidence；
- 在 report 与 journal 中记录 channel、message_ref、authorized reply senders、正文/文本 hash 和 delivery evidence；
- 同一 idempotency marker 已存在时，只有完整文本逐字节相同才能复用，否则拒绝。

adapter response/evidence 只允许以下四个字段，缺失、额外字段或任一绑定不一致都拒绝：

```json
{
  "message_ref": "<channel-message-id>",
  "sender_actor": "hermes",
  "report_body_hash": "sha256:<report-vN.md-bytes>",
  "delivery_text_hash": "sha256:<exact-posted-channel-text>"
}
```

runner 对 response 文件记录 `{path, sha256}`，并要求这四个值与 adapter 配置、确定性 Markdown、真实通道消息、report delivery 数组和 HMAC journal 的 `report_delivered` payload 全部一致。response/evidence 不是 reviewer PASS，也不产生 promotion authority。

名义配置示例：

```json
{
  "delivery": {
    "actor": "hermes",
    "channel": "quadchat",
    "authorized_reply_senders": ["user"],
    "argv": ["/approved/hermes-delivery", "{request}", "{response}", "{report}"]
  }
}
```

终报同时给出最新 `approval_code`（例如 `SR-1A2B3C4D`）。支持原生 reply metadata 的 channel 必须绑定原生 `in_reply_to=<message_ref>`；当前本地四方群聊没有不可伪造的原生 reply 字段，因此可信 loopback adapter 从原始 room event 中提取 sender、event id、时间和消息正文，并要求正文包含最新 approval code，再生成 HMAC 回执证据。调用者不能自行传入这些身份字段。

```bash
python3 scripts/sublation_local_adapter.py attest-quadchat-receipt \
  --run-dir ~/.hermes/sublation/runs/<run_id> \
  --event-id <raw-room-user-event-id>

python3 scripts/sublation_receipt.py apply \
  --run-dir ~/.hermes/sublation/runs/<run_id> \
  --receipt-evidence ~/.hermes/sublation/runs/<run_id>/receipt-io/<event-id>.json
```

回执 attestation 的构造链固定为：读取唯一 raw room event；校验 `sender_id` 在本报告 authorized reply sender 中；校验 event 时间晚于 delivery；校验正文包含最新 `approval_code`；复验 delivery message 的 speaker、exact text hash 与上面四字段 evidence；再落盘 `schema_version`, `adapter_id`, `channel`, `event_id`, `sender_id`, `in_reply_to`, `message`, `received_at`, `source_event_hash`, `report_version`, `report_hash`, `report_body_hash`, `scope_revision`, `approval_code`，最后对完整 payload 写入 `attestation_mac`。`sublation_receipt.py` 复验 HMAC、证据文件 path/sha256、raw event/report/delivery 全绑定后才解析正文。

解析器规范化中文标点，未点名项保持 pending；逗号列表只继承唯一无歧义动作，冲突方向或排除式表达拒绝猜测。拒绝/暂缓修饰词与 `批准`、`同意`、`通过` 先组合成完整动作，再进入任何正向 token 匹配；剩余正向 token 还检查同一 item 边界内最近 24 个字符的否定/暂缓上下文。因此 `不要批准`、`请勿批准`、`不同意批准`、`先不要批准`、`别批准`、`暂缓批准`、`不建议批准`、`not approved`、`do not approve` 等只会得到 reject/hold。“全部批准”只推进到 `APPROVED_PENDING_EXECUTION`，parser 不调用 promotion。

本地 room 的信任边界是当前 macOS 用户账户及其 loopback 服务；HMAC 证明“受信 adapter 处理了这份原始事件”，不把任意本地进程变成加密身份。需要更强身份保证时，应接入平台原生签名/reply metadata；安装常驻 watcher、平台凭据或外部 channel adapter 仍需 user 对持久控制面明确批准。

## 9. HMAC journal 与 Approval 重放防伪

`approval.json` 是缓存，不是晋升凭证。`sublation_promote.py` 在任何正式写入前从耐久证据重建授权：

1. 用 `.control/run-attestation.key` 复验整个 journal 的 hash chain 和逐事件 HMAC；单纯重算公开 hash 不能伪造新事件；
2. 核对最新 report version/hash、确定性 `report-vN.md` body hash、scope revision 和 approval code；
3. 对每个 approval item 复验 report 内的 target、candidate tree、PATCH/baseline、disposition 和 `approval_snapshot_hash`，拒绝终报后在 run 中偷换 item；
4. 复验可信 channel adapter 生成的 receipt evidence HMAC、raw event hash、sender、channel、event id、message、时间、delivery message_ref、report body hash 和 report binding；
5. 复验 delivery adapter evidence 的 path/sha256、body/text hash，并确认 delivery 存在于 journal；
6. 重新解析受 attestation 绑定的原始用户 message，并与 event 中的 parsed decisions 对照；
7. 对照对应的 `approval_receipt_recorded` journal payload；
8. 严格按 HMAC journal 中 `approval_receipt_recorded` 的顺序重放 decisions；`approval.json.events` 的可编辑顺序不具权威，事件集合必须与当前报告的 journal 记录完全一致；
9. 重建 `authorized_scope`，再与 `approval.json` 和 `run.json` 对照；
10. 从绑定当前 report version/hash/scope/approval snapshot 的 promotion journal 重建执行状态，不信任旧报告事件或 `approval.json.execution=succeeded` 缓存；即使已成功，也重新核对 formal post hash 和 rollback baseline。

伪造 decision、伪造 authorized scope、只重算公开 event hash、插入未进 journal 的 event、替换 delivery/receipt evidence、终报后重绑 item 或伪造 succeeded cache 都导致零正式写入。

## 10. 崩溃与并发恢复

Runner 对三个关键中断点有显式恢复语义：

1. **worker 尚未写 response**：request 与 lease 已持久化；恢复后继续同一 task，不生成第二个 task/step；
2. **worker 已写 response、尚未 record step**：恢复时复用同一个 response，不再次调用 worker；
3. **delivery 已发送、尚未 record delivery**：恢复时复用 delivery response 和 report-derived idempotency key，通道只出现一条消息，再补记 report/journal delivery。
4. **delivery 已写 report、尚未 append journal**：恢复时不重复发送；复验已有 response 后补齐缺失 journal event。

此外，journal 中较新的 run snapshot 可以修复落后的 `run.json`；同 revision 内容不一致则判为篡改，不自动覆盖。runner 持有非阻塞 `.orchestrator.lock`，并发第二进程直接失败，不能复用同一 lease 双重调用。恢复不能绕过 `sandbox-exec`、HMAC、evidence hash、task lease、report hash 或 approval replay 门禁。

## 11. 两阶段晋升

回执解析和正式写入严格分离。只有 approval journal 重放通过、目标项明确为 approve，且用户对当前 report 的授权仍有效时，才可运行：

```bash
python3 scripts/sublation_promote.py execute \
  --run-dir ~/.hermes/sublation/runs/<run_id> \
  --rollback-root ~/.hermes/sublation/rollback-points \
  --allowed-target A1=/exact/formal/skill/path
```

执行器还要核对 exact allowed target、candidate/formal 隔离、PATCH.diff path/hash、formal baseline hash、symlink-preserving rollback hash 和临时副本 `git apply --check`/expected post hash。apply 或 post-hash 失败时，先从 rollback 复制到同父目录 staging、复验 baseline，再以 quarantine + rename 恢复 formal 并复验；不能留下半写状态。未知漂移停止，不自动覆盖或删除目标。

## 12. Revision 3 验证状态

Revision 2 的旧 hash/review 因七项 P1 失效；第一份 Revision 3 package 又因五项 P1 跟进审查而失效：否定批准误判、终报正文未绑定、审查者未绑定不可变候选、宿主读取/环境/网络过宽、symlink rollback 与失败恢复不安全。修复时还发现 coordinator 可能替代耗尽的独立席位。当前 package 同时关闭两轮问题，旧 hash/PASS 不可复用。

2026-07-10 当前 builder 已得到以下证据：

- core run/receipt/promotion：`78 tests OK`，含完整声明的中文 reject/hold 修饰词 × 三动作矩阵；
- orchestrator 外层 sandbox suite：`17 tests OK`，含 candidate snapshot、host read/env、零写 reviewer、coordinator non-substitution 和 symlink-preserving source；
- local adapter + fake loopback：`8 tests OK`，含 marker/text collision、tampered body receipt denial、root-bound resume 和 HOLD→不可变 rework E2E；
- 既有 Loop Engineering/review-policy/strong-path 门禁：`4 tests OK`；
- 完整 outer `unittest discover`：`107 tests OK`；
- run schema（含 worker identities/write roots）与实际发现的临时 worker config：均通过 schema validation。

实际生成的 run/config 已通过当前 schema validation，本地 strict audit `37/37`，当前 formal baseline 的临时副本重建后 83 个 runtime 文件逐字节、逐 mode 一致。共享根同步/audit 与 fresh rereview 仍须针对 exact package 完成；旧 package 结果均为 stale。真实模型 CLI 没有调用模型或触发登录/凭据动作。

Claude Code 与 Hermes 对 Revision 3 的全新独立 rereview 均为 pending；当前不得表述为最终独立复核 PASS，也不得据此执行晋升。
