# 合并驱动扬弃（Merge-Driven Sublation）

## 动机

传统 sublation 每次只处理一个技能的单一改进。但当技能库膨胀后，大量技能在同一领域重叠（多种 OCR 引擎、多种格式转换工具），逐个改进无法解决问题——需要**合并**。

合并驱动扬弃的核心思想：**不是修技能，是熔技能**。把 2-4 个功能互补的技能熔成一颗新技能，覆盖所有原始场景但更简洁。

## 方法论

### 1. 筛选（Screening）

扫描整个技能库，只挑有实际脚本（`.py`/`.sh`/`.js`/`.ts`）的功能性技能。纯文档技能（只有 SKILL.md、无工具）合并价值低——知识可以吸收，但工具需要合并。

筛选命令参考：
```bash
find ~/.hermes/skills -name 'SKILL.md' -exec dirname {} \; | while read d; do
  scripts=$(find "$d" -name '*.py' -o -name '*.sh' -o -name '*.ts' -o -name '*.js' | wc -l)
  [ "$scripts" -gt 0 ] && echo "$scripts scripts: $d"
done | sort -rn
```

### 2. 聚类（Clustering）

将有功能重叠的技能按域分组。判断标准：

| 聚类类型 | 特征 | 示例 |
|---|---|---|
| 同质引擎 | 做同一件事的不同实现 | 四种 OCR 引擎 |
| 天然管道 | A 的输出是 B 的输入 | URL→MD→格式化MD→HTML |
| 平台分身 | 同一动作的不同后端 | 微信发布 / X 发布 |
| 生命周期 | 不同阶段但同一对象 | 创建→安装→更新→审计 |

跳过：
- 内容创作类技能（用户不用的领域，如 canghe/huashu/kangarooking）
- 单脚本技能无合并伙伴（如独立的 CLI 工具）
- 跨领域技能（功能域不同，强行合并反而混乱）

### 3. 委托（Delegation）

将聚类后的合并簇批量委托给 Codex。每簇一个独立 task，并行运行。

**Codex 提示词模板**：
```
MERGE TASK X: <cluster name> -> "<merged skill name>"

Merge N skills into ONE at candidates/<name>-merge/

SOURCES:
1. <path1> (<description>, N scripts)
2. <path2> (<description>, N scripts)

DO THIS:
1. Read all SKILL.md and scripts
2. Design unified skill with clear routing/pipeline
3. Write merged SKILL.md to candidates/<name>-merge/SKILL.md
4. Copy/adapt scripts
5. 5-line summary at end

MERGED SKILL: <name> | category: <category>
ABSORBS: <skill1>, <skill2>, ...
```

**防坑**：
- 提示词不要含单引号——写入 `/tmp/codex-prompt.txt`，用 `codex exec "$(cat /tmp/codex-prompt.txt)"` 传入
- 工作目录必须是 git 仓库（`git init && git add -A && git commit`）
- 用 `background=true notify_on_complete=true` 并行跑，用 `process poll` 跟踪进度

### 4. 收尾（Wrap-up）

Codex 产出的合并候选进入标准 sublation 管线：
```
candidate → audit → Hermes review → 【用户审批】→ promote → observation window → close
```

安全规则：
- 候选在 `candidates/<name>-merge/` 沙盒，原技能不触碰
- promote 时才标记 `absorbed_into`，用户审批后才删除原技能

### 5. 复核清单（Review Checklist）

Hermes 审核 Codex 合并产出时必须逐项检查：

1. **功能完整性**：所有源技能的核心功能是否保留？
2. **入口统一**：是否有决策树/路由表，Agent 根据用户意图自动选择工作流？
3. **脚本适配**：`python3 -m py_compile` / `node --check` 是否通过？路径引用是否更新？
4. **配置统一**：多源配置是否合并到统一 `config/` 下？
5. **降级策略**：引擎/后端不可用时是否明确降级路径？
6. **元数据一致**：`absorbs` 是否在顶层而非嵌套？`version`/`author` 是否修正？
7. **不误伤**：源技能目录是否完全未触碰？（`diff -qr` 确认）

## 实战记录

### 第一轮（2026.5.28）：15→5

| 合并后技能 | 输入 | 脚本 | 核心设计 |
|---|---|---|---|
| document-ocr | ocr-and-documents + mineru-ocr + paddleocr-doc-parsing + paddle-ocr (4→1) | 16 | 引擎自动路由表 |
| universal-converter | canghe-url-to-markdown + canghe-format-markdown + canghe-markdown-to-html + markitdown (4→1) | 34 | pipeline.ts 管道编排器 |
| content-publisher | canghe-post-to-wechat + canghe-post-to-x (2→1) | 39 | 统一入口 + 平台路由 |
| skill-lifecycle | skill-creator + skill-manager (2→1) | 13 | lifecycle.sh 六阶段调度 |
| media-toolkit | universal-media-downloader + douyin-batch-download + video-compressor (3→1) | 18 | 决策树查表选脚本 |

### 第二轮（2026.5.28）：17→6

| 合并后技能 | 输入 | 核心设计 |
|---|---|---|
| speech-to-text | funasr-transcribe + tingwu-asr (2→1) | 本地/云端自动路由 |
| document-generator | docx + md2word + docx-generator (3→1) | markdown→专业docx管道 |
| legal-research-hub | legal-research + yuandian-law-search + zhihe-legal-research (3→1) | 多数据源统一入口 |
| legal-document-ingest | legal-text-format + wechat-article-fetch (2→1) | 抓取→格式化管道 |
| stock-workspace | stock-daily-analysis + claude-stock-* ×4 (5→1) | 技术面+基本面+估值合一 |
| contract-review | contract-copilot + claude-commercial-contract-review (2→1) | 17脚本引擎+审查框架 |

**累计**：两轮 32→11，总量 -66%。

## 成功标准

一次成功的合并驱动扬弃应满足：
1. 输入技能数 > 输出技能数（做了减法）
2. 合并后覆盖所有输入场景，无功能退化
3. 用户使用单一入口，不必纠结选哪个技能
4. Agent 上下文负担减轻（skill 列表更短，加载更快）
5. 合并后技能比任一源技能更强（吸收了互补优势）
