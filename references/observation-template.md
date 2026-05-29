# Observation Record Template

```json
{
  "schema_version": 2,
  "timestamp": "ISO-8601",
  "skill_name": "skill-name",
  "skill_content_hash": "sha256:xxxxxxxxxxxx",
  "source_session_hash": "sha256:xxxxxxxxxxxx",
  "classification": "clean|partial|defect|critical",
  "reflection_type": "DISCOVERY|OPTIMIZATION|SKILL_DEFECT|EXECUTION_LAPSE",
  "confidence": 0.0,
  "trace_completeness": 0.0,
  "step_details": [
    {
      "step": "技能中的具体步骤描述",
      "status": "followed|partial|bypassed|tool_failure|skipped|defect_suspected",
      "sub_label": "env_mismatch|permission_denied|timeout|logic_error|null",
      "evidence_short": "关键证据摘要",
      "confidence": 0.0
    }
  ],
  "summary": "一句话总结",
  "recommendation": "obs_only|flag_for_review|create_candidate"
}
```

## Status 定义

| status | 含义 | 示例 |
|---|---|---|
| `followed` | 技能步骤被完整正确执行 | 脚本跑通了，输出到正确路径 |
| `partial` | 执行了但结果不完整 | yindeng_monitor 跑通了但数据不完整 |
| `bypassed` | agent 跳过了该步骤 | 应该做 but agent 没做 |
| `tool_failure` | 工具/脚本/API 故障 | 反爬拦截、404、500 |
| `skipped` | 合法跳过（条件不满足） | 无新增公告所以跳过报告 |
| `defect_suspected` | 怀疑技能本身有问题 | URL 硬编码在脚本里导致失效 |

## Classification 定义

| classification | 含义 | 线 2 升级 |
|---|---|---|
| `clean` | 完美执行，无任何问题 | 不需要 |
| `partial` | 大体遵循但有改进空间 | 同类 >=3 次 |
| `defect` | 技能内容确认有缺陷 | 单次即可触发 |
| `critical` | 技能导致数据丢失/错误输出/安全风险 | 立即触发 |
