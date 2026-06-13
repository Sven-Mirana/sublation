# 首次扬弃实验：NPL Cron Failure → Candidate

日期：2026-05-25
实验名称：NPL Cron Failure → Skill Candidate Sublation

## 背景

npl-monitor 的每日 cron（ID: 5deb084e32e9）在 2026-05-25 执行时发生：
- 银登网 URL 变更导致 yindeng_monitor.py 404
- 阿里拍卖反爬从无验证码升级到 x5sec
- cron agent 自行 patch 了正式技能脚本（违规）

## 实验流程（遵循 skill-sublation v2 七步）

### Step 1: 观测累积
读取 cron 输出 `~/.hermes/cron/output/5deb084e32e9/2026-05-25_09-04-54.md`，确认三类问题。

### Step 2: 生成 observation
```
~/.hermes/skill-observations/e6a18c28dbcb/observations/20260525-090428-cron_5deb.json
```
- classification: partial
- reflection_type: SKILL_DEFECT
- 7 条 step detail，覆盖全部三类问题
- index.jsonl 已追加

### Step 3: 创建候选副本
```
~/.hermes/sublation/candidates/npl-monitor/20260525-090428-hermes/
├── SKILL.md         ← 从正式技能复制
├── scripts/         ← 从正式技能复制（未改）
```

### Step 4: 打磨候选
仅改 SKILL.md 规范层，不改脚本：
- 新增「报告规范」：系统状态表 + 数据摘要 + 待办事项三部分强制
- 新增「反爬降级规则」：验证码拦截时不得伪装空结果
- 新增「防呆规则」：0 条 ≠ 无新增；URL 不应硬编码
- 新增「Fixture 测试」入口

### Step 5: 生成产物
- PATCH.diff — 相对正式技能的 unified diff
- RATIONALE.md — 为什么改，每个改动对应哪条观测
- EVIDENCE.md — 三条关键证据摘要
- manifest.json — breaking_changes: []  backward_compat: true

### Step 6: 交叉复核（两轮）
- **第一轮（实验前）**：Codex 审阅 sublation v2 草案，6 条修改意见全部吸收，奠定方法论基础。
- **第二轮（修稿后）**：候选创建后 Codex 再做 8 条具体修改意见。Hermes 全部吸收：修复 PATCH.diff 路径、恢复定时任务段落、移除不存在的 --fixture、新增 cron 禁改正式脚本、标注 URL 外置为待办、强化 EVIDENCE 措辞、manifest 保持 auditor_passed:false。全部修完后重新生成干净 PATCH.diff。

### Step 7: 晋升门控 → 批准 → 合入
- 2026-05-25：候选经 Codex 两轮交叉复核后提交用户审批。
- 用户批准。Hermes 执行 skill_manage(action='edit') 将候选内容合入正式技能。
- cron prompt 同步更新。
- 新正式 hash: `sha256:cb873edb...`，回滚点: `sha256:e6a18c28...`。
- manifest.json 更新：auditor_passed: true（交叉复核等效），status: promoted。

## 成功判据验证

| 判据 | 结果 |
|---|---|
| 正式技能晋升前未被修改 | ✅ hash e6a18c28 不变 |
| 候选区完整生成 | ✅ 6 文件 |
| observation 合法 JSON | ✅ schema v2 |
| 交叉复核两轮 | ✅ Codex 6+8=14 条意见 |
| 人工审核批准 | ✅ 2026-05-25 |
| 晋升后正式技能更新 | ✅ hash cb873edb |
| cron prompt 同步更新 | ✅ |
| 回滚点保留 | ✅ sha256:e6a18c28 |

## 晋升后待验证

- [ ] NPL cron (5deb084e32e9) 下次执行是否遵守新规范（2026-05-26 9:00 验证）
- [ ] ★ 脚本层候选：auction_monitor.py 结构化 status 输出
- [ ] ★ 脚本层候选：yindeng_monitor.py URL 外置
- [ ] sublation 框架是否需要命令工具化/cron 聚合器

## 经验教训

1. **候选粒度要克制**：本次只改规范层（SKILL.md），不改脚本。脚本层面的 URL 外置和 Playwright 方案留到下次单独候选。这验证了「targeted patch」原则。
2. **Agent 违规是触发框架建设的直接原因**：cron agent 自行 patch 正式脚本的行为，是 skill-sublation 从 v1 的「永不改任何技能文件」演进到 v2 的「不改正式层，可以造候选层」的直接推手。
3. **交叉复核在实验前就发生了**：Codex 审阅 v2 草案时给出的 6 条意见已全部吸收，为本次实验提供了方法论基础。
