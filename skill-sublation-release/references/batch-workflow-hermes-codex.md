# Hermes + Codex 批量候选工作流

用户不在线期间的协作模式：Hermes 负责筛选技能 + 复核，Codex 负责执行、记录、修 bug、验收前检测。双方各出报告，用户醒来后看报告决定晋升。

## 角色分工

| 阶段 | Hermes | Codex |
|------|--------|-------|
| **扫描** | 全盘扫描 pycache/脚本密度/治理覆盖，选出候选目标 | — |
| **创建** | 简单候选（pycache hygiene 等模板化 infra-fix）可直接建 | 复杂候选（inventory、merge analysis、script-enhance）由 Codex 建 |
| **审计** | 独立跑 strict audit 复核 Codex 产出 | 自跑 strict audit，修到 passed |
| **记录** | 汇总双方产出为总报告 | 产出 batch report 到 `~/.hermes/sublation/reports/` |
| **晋升** | 用户批后执行晋升（audit→fixture→rollback→合入→smoke→manifest） | 可执行被委派的晋升步骤 |
| **验收** | 业务烟雾测试 | fixture 验证 + 回归检查 |

## 批量节奏

1. Hermes 扫描全技能库，输出候选目标列表
2. 简单的 pycache hygiene 由 Hermes 自带模板化创建
3. 深度分析（inventory / merge / script-enhance）委托 Codex
4. Codex 完成后 Hermes 独立复核所有候选的 strict audit
5. Hermes 汇总总报告，标注哪些可直接批、哪些需用户决策
6. 用户醒来后逐批审批

## 批量子类型

### Pycache 批量扫荡（infra-fix）

模板见 `references/pycache-hygiene-template.md`。全同格式，批量生产。Hermes 可直接建，Codex 也可以建。

### Merge 预审（spec-patch / skill_merge_plan）

1. 先做 inventory：对比两个技能的脚本 hash、文件重叠度、独有文件
2. 输出分析报告到 `references/<donor>-<target>-merge-inventory.md`
3. 不给删除建议——只提供三个选项：close-superseded / keep-as-alias / migrate-docs-only
4. 用户决策后另开 lifecycle 候选执行

### Merge 执行（生命周期候选）

1. Mark donor SKILL.md：`status: superseded; superseded_by: <target>; superseded_date: <date>`
2. 迁移有价值的文档到 target `references/`
3. 不拷贝 config.json、.git/、密钥文件
4. 验证 donor scripts 与 target scripts 同 hash（确认无能力丢失）

## 报告格式

两份报告：
- `~/.hermes/sublation/reports/batch-work-{date}-codex.md` — Codex 的执行报告
- Hermes 在对话中输出复核总报告，包含：
  - 已晋升列表（observation_window）
  - 待审批列表（review_pending），按类型分组
  - 需用户决策的高风险项
  - 队列健康状态

## 首轮应用

2026-05-31：stock-workspace + construction-dispute-workflow + contract-review + md2word + last30days + speech-to-text + canghe-manga-* + contract-copilot + npl-workflow。产出 6 个新候选 + 1 个 merge 执行 + 1 个 orphan 调查。

2026-06-02 夜间：23 个法律 skill 分 5 批全量排队（Batch1:3 文档处理，Batch2:4 检索工具，Batch3:4 媒体内容，Batch4:5 外部API，Batch5:7 基础设施）。产出：5 候选（paddle-ocr/git-batch-commit/video-compressor/tingwu-asr/piclist-upload）全部 strict audit PASS + 18 observation-only。另：2 个金融 skill 筛选（polymarket + fincept-macro-swarm），polymarket 候选已 audit PASS。加上前半夜的 npl-monitor zhongdeng human-login-cdp 候选，夜间总计产出 7 个通过审计的候选。

## 夜间连续流水线模式（Nighttime Pipeline）

用户睡觉期间的全自动批量 sublation 协作模式。核心原则：**流水线不能断。**

### 前置条件

1. 先完成全库上游同步（见 `references/upstream-skill-sync-methodology.md`）——对旧版本做 sublation 是自欺欺人
2. 排除已 sublate 的 skill（查 `candidates/` 目录）
3. 按脚本密度和复杂度分组排序

### 分批策略

| 批次规模 | 内容 | 优先级判据 |
|----------|------|-----------|
| 3-5 个/批 | 同域同类型 | 脚本多的优先，与用户业务相关的优先 |
| 全量排队 | 所有批次一次性发出 | Codex 有完整队列可见，不需等 Hermes 逐批催 |

**反模式：逐批发。** 等 Codex 完成一批再发下一批，会让 Codex 空闲等待、Hermes 反复切上下文。正确做法是在 10 分钟内发出所有批次，Codex 自行排队处理。

### Hermes 硬边界

在夜间流水线中 Hermes 的角色是**筛选 + 复核 + 方向把控**，不做编码：

- ❌ 不写 Python/JS/Shell/Bash
- ❌ 不修改候选的 SKILL.md/manifest/PATCH.diff
- ❌ Codex 超时不接手编码——重新 delegate_task 或通过群聊再问 Codex
- ✅ 扫描技能库、分组排序、发批次到群聊
- ✅ 跑 strict audit 复核每个候选
- ✅ 读 PATCH.diff 做业务/法律语义审查
- ✅ 通过群聊与 Codex 沟通分歧

### Codex 超时处理

当 Codex 通过 delegate_task 被委派但迭代上限退出时：
1. 检查候选状态——如果只剩机械步骤（文档补齐、manifest 修正）可接手
2. 如果核心编程未完成，**直接重新 delegate_task 调用 Codex**
3. 可缩小 scope 或拆分任务
4. **绝不自己写代码**——编程层出问题 Codex 要自己修

### 群聊沟通

所有批量任务通过三方群聊桥（见 `references/three-party-chat-bridge.md`）发 Codex：

```
POST http://192.168.1.46:8787/api/messages
{"speaker":"hermes","audience":"codex","kind":"message","text":"批次内容..."}
```

完成后通知全员：
```
POST ... "audience":"all" ...
```

## Pitfalls

- **用户"别急着"信号**：当用户说"别急着"/"不要急"时，意味着当前阶段还没完成就想跳到下一步。正确做法：完成当前阶段→验证当前假设→沉淀发现→再进入下一阶段。不要在扫描完技能后直接问"要不要开始建候选"——先完成全库同步和验证，让数据说话。这个信号在 2026-06-02 上游同步阶段触发：用户要的是"先把所有 skill 更新到最新，对比 sublation 效果，验证方向对不对"，不是"筛选完直接建候选"。
