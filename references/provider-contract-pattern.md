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

## 何时使用

- 技能依赖外部 API/网站/数据源
- 数据源可能不可用、被反爬、需要认证
- 用户可能有不同的数据供应商偏好
- 技能要面向多人使用（每个人的 MCP/数据源不同）
