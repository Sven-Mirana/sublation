# Agent Bridge — WeChat / REST Pattern

Codex 搭建的轻量 HTTP 桥，让 Hermes（终端 session）能参与 WeChat 平台上的多人 AI 群聊。

## 架构

```
Codex (WeChat bot)
  │
  ├── GET /api/hermes-inbox     → Hermes 拉取未读消息 + 共享状态
  └── POST /api/hermes-webhook  ← Hermes 写回群聊
```

Hermes 终端 session 无法直接接入 WeChat 平台，但可以通过 HTTP 轮询和写回参与同一消息流。

## 端点

### 读取群聊

```bash
curl -s http://<host>:8787/api/hermes-inbox
```

返回 JSON：

```json
{
  "room": { "room_name": "...", "project": "...", "participants": [...] },
  "messages": [ { "speaker": "codex|hermes|user", "text": "...", ... } ],
  "state_md": "# Shared State\n...",
  "decision_queue_md": "# Decision Queue\n..."
}
```

`state_md` 和 `decision_queue_md` 是 Codex 维护的共享状态和决策队列，Markdown 格式。

### 写回群聊

```bash
curl -s -X POST http://<host>:8787/api/hermes-webhook \
  -H "Content-Type: application/json" \
  -d '{"text":"你的消息","source":"hermes-wechat"}'
```

`source` 固定为 `hermes-wechat`，用于群聊中标识消息来源。

## 边界

- 只读/写聊天消息，不授权修改文件
- 不绕过 sublation 审批
- IP 和端口由 Codex 在 WeChat 端配置，每次启动可能变化
- curl 到本地 IP（192.168.x.x）会被 Hermes 安全拦截，需用户手动批准

## 使用模式

1. 先 `GET inbox` 读最新的共享状态和决策队列
2. 对照自己的本地审计结果
3. 通过 `POST webhook` 写回建议，供 Codex 和用户在群聊中看到
4. 用户最终决策后，Codex 执行晋升/修复，更新共享状态
