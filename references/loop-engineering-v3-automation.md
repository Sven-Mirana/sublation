# Loop Engineering v3 Automation

Loop Engineering v3 的目标不是让 agent 自动晋升 skill，而是让 Sublation 启动后自动把工程流程推进到“只剩 user 审批”的状态。

这层自动化吸收 6/28 `loop-engineering-protocol` 的角色和状态机，把人工口头流程固化为可运行的候选门禁、证据包和审批包。

## 目标

启动 Sublation loop 后，系统应自动完成：

1. 读取候选目录和 manifest；
2. 核对候选不在正式 skill root 内；
3. 计算候选与 source baseline 的 changed paths；
4. 检查 value-delta、scope/out_of_scope、candidate-copy input、no formal write、no credential/login、no live validation、no optimizer/iterative/sync/load_skill 等硬边界；
5. 检查 review policy 和三方 evidence 是否齐备；
6. 生成机器可读 `loop_report.json`；
7. 生成给 user 审批用的 `PROMOTION_DECISION_PACKET.md`；
8. 在 `USER_DECISION_REQUIRED` 前停止。

自动化不得把 reviewer PASS 当作用户授权，不得把群聊桥联通当作任务完成，不得把候选层验证当作正式晋升。

## 状态机

| 状态 | 含义 | 下一步 |
|---|---|---|
| `BLOCKED` | 硬门禁失败，例如 manifest 缺失、候选在正式 root 内、value-delta 缺失、patch 不可复验、边界不清 | 停止，修候选 |
| `REVIEW_REQUIRED` | 候选和本地门禁通过，但三方 evidence 或统一简报未齐 | 请求 Claude Code / Hermes 复核 |
| `USER_DECISION_REQUIRED` | 本地门禁通过，三方 evidence 齐，审批包已生成 | user 决定 approve / hold / request changes / reject |
| `APPROVED_SCOPE_READY` | user 明确批准某一晋升 scope | 只执行被批准的 scope |
| `OBSERVING` | 已晋升并进入 observation window | 记录 rollback、baseline、异常和关闭条件 |

`USER_DECISION_REQUIRED` 是自动化默认终点。任何更进一步的状态都必须引用 user 的当前轮授权消息。

## 输入契约

最小输入：

```bash
python3 scripts/loop_engineering.py run \
  --candidate /path/to/candidate \
  --output-dir /path/to/candidate/validation/loop-v3 \
  --no-room
```

可选输入：

- `--room-health-url http://127.0.0.1:8787/api/health`：只读检查四方群聊桥健康；
- `--formal-root /path/to/formal/root`：覆盖 manifest.source_skill.path 作为 apply/read-back 根；
- `--allow-mirror`：显式允许从共享候选镜像复核；
- `--json-only`：只输出 JSON，不写 Markdown 审批包。

## 硬门禁

必须通过：

- `manifest.json` 可解析，`schema_version=3`；
- `candidate.path` 指向当前候选目录，或当前目录是与 manifest 路径有效内容一致的共享候选镜像；
- 候选目录不在 `source_skill.path` 或显式 `formal_root` 内；
- `validation.promotion_mode=none`，除非已经进入用户明确批准后的执行阶段；
- `validation.value_delta.status=positive_delta`，且包含证据、回滚或 fallback；
- `scope.changes` 和 `scope.out_of_scope` 非空；
- `out_of_scope` 明确排除 formal write、promotion without approval、credential/login、live scraping/validation、optimizer/iterative/sync/load_skill；
- `PATCH.diff` 非空，且可在 source/formal copy 上 `git apply --check`；
- 如果三方 review 未齐，状态只能是 `REVIEW_REQUIRED`；
- 如果三方 review 已齐，状态只能推进到 `USER_DECISION_REQUIRED`。

## 审批包

`PROMOTION_DECISION_PACKET.md` 必须并列展示：

- candidate id；
- changed paths；
- value-delta 摘要；
- hard gates；
- builder evidence；
- verifier evidence；
- reviewer/historian evidence；
- unresolved blockers；
- explicit user choices。

用户选择必须保留四种：

- approve exact promotion scope；
- hold；
- request changes；
- reject。

审批包不得写“建议自动晋升”。可以给出推荐，但必须停在用户选择。

## 四方分工

- Codex：生成候选、运行 `loop_engineering.py`、整理 builder evidence；
- Claude Code：从共享候选根独立复跑脚本、`git apply --check`、hash/read-back；
- Hermes：做 historian/reviewer，统一成用户可读简报；
- user：最终决定是否晋升。

如果 Hermes 统一简报与磁盘证据冲突，以磁盘证据为准。

## 噪音控制

v3 automation 只在状态改变时发言：

- `BLOCKED`；
- `REVIEW_REQUIRED`；
- `USER_DECISION_REQUIRED`；
- `APPROVED_SCOPE_READY`；
- `OBSERVING`；
- `ROLLBACK_REQUIRED`。

相同 fingerprint 的 no-change 状态默认静默。群聊桥恢复只算通信恢复，不算任务完成。

## 非目标

v3 automation 不做：

- 自动写正式 skill；
- 自动晋升；
- 自动关闭 observation window；
- 自动读取/保存/转发 credential、cookie、token、login session；
- 自动绕过 CAPTCHA、登录墙、反爬或风控；
- 自动调用 optimizer、iterative loop、sync pull、load_skill；
- 自动外部发布。

这些能力即使技术上可做，也必须作为独立候选进入 Sublation，不得混入 v3 自动化入口。
