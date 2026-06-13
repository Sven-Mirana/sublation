# 实验 002：NPL Script Status Contract + Fixture

日期：2026-05-26
状态：✅ 已晋升

## 做了什么

为 auction_monitor.py 和 yindeng_monitor.py 添加：
- `--fixture <file>` — 离线验证，不访问真实网络
- `--output-dir <dir>` — 输出到临时目录，不碰 data/npl
- 结构化输出：source_ok / status / error_type / error_message / items / new_items

核心突破：**blocked ≠ no_new**。反爬拦截时输出 source_ok=false, status=blocked，不再伪装成「今日无新增」。

## 晋升历程

| 步骤 | 谁 | 结果 |
|---|---|---|
| 创建候选 | Codex | 候选区 + 脚本改动 + 6 fixtures + validation |
| 复核 | Hermes | PASS：安全边界全过，fixture 6/6，manifest 含显式 out_of_scope |
| 审批 | 用户 | 批准 |
| 合入 | Hermes | SKILL.md + 2 脚本 + fixtures/ 晋升，回滚点保留 |

## 回滚点

```
SKILL.md:                  sha256:cb873edb...
auction_monitor.py:        sha256:6162681a...
yindeng_monitor.py:        sha256:c95fad2c...
```

## 与实验 001 的对比

| | 实验 001 | 实验 002 |
|---|---|---|
| 层级 | 规范层（SKILL.md） | 脚本层（Python） |
| 谁主创 | Hermes | Codex |
| 谁复核 | Codex | Hermes |
| 验证方式 | 人工审查 | fixture 自动化 |
| out_of_scope | 隐式 | manifest 显式声明 |

## 下一步

- NPL cron 明天跑时验证脚本层 status 字段是否正常
- 实验 003：yindeng_monitor.py URL 外置（脚本配置化）
