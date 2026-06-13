# 通用域 Skill 筛选方法论

## 筛选流程
1. 全量扫描：排除 legal/stock/canghe/huashu/ljg/khazix 等专属域
2. 去重已 sublate：`ls ~/.hermes/sublation/candidates/` 对比
3. 按脚本密度排序（`.py/.sh/.js` 数量），高者优先
4. 读 SKILL.md 确认外部依赖和风险面

## 批量发送格式
每批 3-7 个，群聊格式：
```
## 夜间 Batch N/M：分类名
1️⃣ skill-name（简述）
   files=N | .py=N scripts
   功能：...
   风险面：...
```

## 已验证产出（2026.6.2-6.3）
- 5 批 23 个法律 skill → 5 候选 + 18 observation-only
- 候选类型：provider-contract (4) + spec-patch (1)
- 金融类 2 个：polymarket (候选) + fincept-macro-swarm (observation)
- provider contract 模式验证闭环：npl-monitor 005a → polymarket → piclist-upload → paddle-ocr → git-batch-commit → video-compressor → tingwu-asr
