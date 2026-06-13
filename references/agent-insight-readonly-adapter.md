# Agent-Insight Read-Only Evaluator Adapter

## 来源

- 项目：openEuler/witty-skill-insight (Agent-Insight)
- 仓库：https://atomgit.com/openeuler/witty-skill-insight
- 许可：MIT
- 定位：Agent 全生命周期可观测、评估与优化平台

## 与 Sublation 的关系

sublation 是治理驱动：candidate -> audit -> review -> promote。
Agent-Insight 是评估驱动：ingest -> static evaluation -> issues/scorecard -> report。

两者可以互补，但职责不能混同：

| 维度 | sublation | Agent-Insight |
|------|-----------|---------------|
| 核心问题 | 该不该晋升 | 候选结构和执行证据是否健康 |
| 强项 | 候选隔离、rollback、交叉复核、人类审批 | 静态合规、触发分析、benchmark、A/B 证据 |
| 边界 | 决定晋升流程 | 只能提供证据 |

## 吸收模式：Read-Only Evaluator Adapter

取精华：

- L1 静态合规检查；
- trigger / skill flow 分析；
- benchmark 与 A/B 评估思想；
- 结构化 `external_evaluations[]` 和 `validation.empirical_scorecard` 证据。

去糟粕：

- 不吸收 optimizer 晋升权；
- 不吸收会写正式技能目录的 mutator；
- 不吸收覆盖本地技能的同步命令。

## 硬边界

1. **只接受候选副本路径**：输入必须是 `~/.hermes/sublation/candidates/<skill>/<candidate-id>/`、fixture 或 `/private/tmp` 中由候选复制出的临时目录。
2. **拒绝正式技能路径**：不得把 `~/.hermes/skills/`、`~/.codex/skills/`、`~/.agents/skills/` 下的 active skill 目录作为 Agent-Insight 输入。
3. **默认 `enableL2:false`**：首轮只跑 native static evaluation，不调用 LLM evaluator。
4. **禁止 optimizer 写入模式**：不得运行 `skill-optimizer` 的 DiagnosticMutator、`iterative-optimizer`、`skill-sync pull`、`load_skill.sh`。
5. **证据不是权力**：Agent-Insight 分数或 issue 数只能写入 `external_evaluations[]` / `empirical_scorecard`，不能自动改变候选状态。
6. **报告必须可追溯**：记录 skill id、version、evaluation id、content hash、issues count、severity histogram、输入路径和 formal path 未使用声明。

## 隔离部署流程

```bash
# 1. 隔离 clone。不要运行 npx install/activate telemetry。
git clone https://atomgit.com/openeuler/witty-skill-insight.git ~/Documents/Codex/tools/witty-skill-insight

# 2. 独立数据目录。
mkdir -p ~/Documents/Codex/data/witty-insight-isolated

# 3. .env 中显式指定隔离 SQLite。
DATABASE_URL="file:$HOME/Documents/Codex/data/witty-insight-isolated/witty_insight.db"

# 4. 关 Next.js telemetry 后启动。
NEXT_TELEMETRY_DISABLED=1 npm run dev -- -p 3000
```

`/skill-insight` 是该项目的 URL prefix；探活应访问：

```bash
curl -L http://localhost:3000/skill-insight
```

## 候选导入：官方 API 优先

先复制候选到临时目录，必要时只修改临时副本 frontmatter `name` 以避免与既有导入记录冲突：

```bash
CAND=~/.hermes/sublation/candidates/<skill>/<candidate-id>
TMP=/private/tmp/witty-import/<skill>-<candidate-id>
cp -R "$CAND" "$TMP"
```

使用官方 automation import API：

```bash
curl -sS -X POST \
  http://localhost:3000/skill-insight/api/skills/automation/import \
  -H 'Content-Type: application/json' \
  --data '{
    "path": "/private/tmp/witty-import/<skill>-<candidate-id>",
    "user": "codex@subation.dev"
  }'
```

成功响应示例：

```json
{
  "success": true,
  "skill": {
    "id": "cmpxpsdqz000113zc7nbbfxus",
    "name": "piclist-upload-codex-native-20260603"
  },
  "version": 0,
  "status": "created"
}
```

## Native L1 静态评估

使用 import 返回的 `skill.id` 和 `version` 调用 native static evaluation：

```bash
curl -sS -X POST \
  http://localhost:3000/skill-insight/api/skills/<skill-id>/versions/<version>/evaluate \
  -H 'Content-Type: application/json' \
  --data '{
    "user": "codex@subation.dev",
    "enableL2": false
  }'
```

再读取 summary：

```bash
curl -sS \
  'http://localhost:3000/skill-insight/api/skills/<skill-id>/versions/<version>/evaluation-summary?user=codex@subation.dev'
```

和 detail：

```bash
curl -sS \
  'http://localhost:3000/skill-insight/api/evaluation/<evaluation-id>'
```

## Sublation 记录格式

把 Agent-Insight 输出记录为外部证据：

```json
{
  "external_evaluations": [
    {
      "evaluator": "agent-insight",
      "target": "candidate",
      "mode": "read_only_scorecard",
      "input_path": "/private/tmp/witty-import/<skill>-<candidate-id>",
      "formal_skill_modified": false,
      "enable_l2": false,
      "skill_id": "<agent-insight-skill-id>",
      "version": 0,
      "evaluation_id": "<evaluation-id>",
      "content_hash": "<content-hash>",
      "issues_count": 0,
      "severity_histogram": {
        "high": 0,
        "medium": 0,
        "low": 0
      },
      "report_path": "validation/agent-insight-native-static.json",
      "notes": "Evidence only; promotion still requires audit, review, and user approval."
    }
  ]
}
```

可衡量时，同时补 `validation.empirical_scorecard`：

```json
{
  "status": "measured",
  "evaluator": "agent-insight",
  "baseline": {
    "label": "candidate structural audit baseline",
    "score": 1.0
  },
  "candidate": {
    "label": "native static evaluation",
    "score": 1.0
  },
  "metrics": [
    {
      "name": "native_static_issues",
      "result": 0,
      "passed": true
    }
  ],
  "decision": "improved",
  "notes": "Scorecard supports the candidate as evidence, but does not approve promotion."
}
```

## 已验证案例

2026-06-03，Codex 对 `piclist-upload/20260602-dry-run-offline-codex` 进行了只读 native L1 评估：

- 候选原件：`~/.hermes/sublation/candidates/piclist-upload/20260602-dry-run-offline-codex`
- 临时副本：`/private/tmp/witty-piclist-clean-import-20260603/piclist-upload-codex-native-20260603`
- Agent-Insight skill id：`cmpxpsdqz000113zc7nbbfxus`
- version：`0`
- evaluation id：`cmpxpsq1p000513zcivc3ylqm`
- generator：`static-evaluator@0.1`
- issues：`0`
- severity：`high=0, medium=0, low=0`
- L2：未启用
- 正式技能目录：未作为输入，未修改

工作区报告：

`coordination/tri-party-room/agent-insight-piclist-native-static-20260603.md`

## Pitfalls

- **不要用 SQLite 直插作为标准导入路径**：直接写 `SkillVersion.content` 容易把 Markdown 写成 Blob/base64，导致 Prisma 读取时报类型错误。仅可作为被明确批准的故障诊断手段。
- **不要把 audit.py 报告误称为 Agent-Insight native L1**：sublation audit 可以作为 baseline/safety evidence；native evidence 必须来自 Agent-Insight evaluation API。
- **不要把 404 当作 API 不存在**：本项目使用 `/skill-insight` prefix，完整路径是 `/skill-insight/api/...`。
- **不要把 root `/` 404 当成服务失败**：应探测 `/skill-insight`。
- **不要保留 telemetry 默认开启状态**：下次重启前设置 `NEXT_TELEMETRY_DISABLED=1`。
- **不要把评估结果等同于晋升结论**：0 issues 只能证明这一次静态评估没有发现问题，不能替代 Hermes/Codex 复核和用户审批。
