# Provider Contract 模式

源自 npl-monitor 实验 005a，适用于任何技能需要对接外部数据源但不想绑定特定实现的场景。

## 三种模式

| 模式 | 含义 | 行为 |
|---|---|---|
| `direct` | 技能内置的默认实现 | 能跑就跑，失败报告 status=blocked/error |
| `mcp` | 用户通过 MCP 协议接入的外部数据源 | 技能只定义 contract，数据源由用户选择 |
| `disabled` | 显式关闭 | 报告中标注覆盖不完整，不伪装正常 |

## 契约要求

无论哪种模式：
- 必须输出结构化 status 字段（ok/no_new/blocked/error/disabled）
- blocked 时不得伪装成 no_new
- 报告中标注当前 provider 模式

## --json-status 实现模式

多个技能已验证的统一实现方式：添加 `--json-status` CLI flag，输出结构化状态 JSON：

```json
{
  "provider": "polymarket",
  "status": "ok",
  "source_ok": true,
  "command": "search",
  "text_output": "<legacy human-readable output>"
}
```

状态枚举（所有 provider 统一）：
- `ok` — 数据源正常，有数据
- `no_new` — 数据源正常，无新增
- `empty_result` — 数据源响应但无匹配
- `http_error` / `network_error` / `parse_error` — 源不可靠
- `blocked` — 反爬/验证码拦截
- `login_required` — 需用户先登录（human-in-the-loop）
- `captcha_pending` — 等待用户完成人机校验
- `disabled` — 本轮明确停用

旧 CLI 行为保持不变：不加 `--json-status` 时输出完全不变。

## 验证链（2026-06-02 生产验证）

从 npl-monitor 005a 开始，同一模式被 7 个 skill 继承并全部通过生产验证：

```
npl-monitor 005a (银登网 source_ok=true ✅, 阿里拍卖 blocked ✅)
    ↓
polymarket 20260602 (--json-status, 6 status types)
    ↓
paddle-ocr 20260602 (config status, 4 modes)
git-batch-commit 20260602 (--dry-run --json)
video-compressor 20260602 (--dry-run --json will_encode)
tingwu-asr 20260602 (auth status, cookie_ok)
piclist-upload 20260602 (--dry-run offline, macOS bash fix)
    ↓
npl-monitor zhongdeng 20260602 (login_required, 8 status types)
```

验证结论：provider contract 模式在 data API、auth API、CLI tool、browser-based service 四类场景中全部正确运行。

## 何时使用

- 技能依赖外部 API/网站/数据源
- 数据源可能不可用、被反爬、需要认证
- 用户可能有不同的数据供应商偏好
- 技能要面向多人使用（每个人的 MCP/数据源不同）
- **新场景**：需要区分\"没数据\"和\"数据源挂了\"的 cron/monitoring 场景（核心价值）
