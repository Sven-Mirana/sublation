# Pycache Hygiene Candidate Template

批量复制即可生成 pycache 清理 infra-fix 候选。适合大批量扫荡未治理技能的 bytecode 污染。

## 何时使用

- 技能 `scripts/` 下有 `__pycache__/` 或 `*.pyc` 文件
- 技能没有被 `.gitignore` 保护
- 候选类型固定为 `infra-fix`，`backward_compat: true`

## 模板

每个候选包含 3 个新建文件：

### `.gitignore`
```
__pycache__/
*.pyc
```

### `scripts/clean.sh`
```bash
#!/bin/bash
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
echo "Cleaning bytecode artifacts from $SKILL_DIR ..."
find "$SKILL_DIR" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
find "$SKILL_DIR" -type f -name '*.pyc' -delete 2>/dev/null || true
echo "Done. Bytecode artifacts removed."
```

### candidate-local `references/hygiene.md`
```markdown
# Bytecode Hygiene

{N} bytecode artifacts found in `{skill_name}`. Cleaned by `scripts/clean.sh`.

## Prevention
`.gitignore` excludes `__pycache__/` and `*.pyc` patterns.
```

## Manifest 要点

```json
{
  "candidate_type": "infra-fix",
  "backward_compat": true,
  "validation": {
    "empirical_scorecard": {
      "status": "measured",
      "metric_name": "pycache_artifact_count",
      "baseline_score": <N>,
      "candidate_score": 0,
      "higher_is_better": false,
      "decision": "improved"
    }
  },
  "relationships": {
    "sublation_pattern": "single_skill_patch"
  }
}
```

**注意**：`sublation_pattern` 是 `single_skill_patch`，不是 `infra_fix`。`infra-fix` 是 `candidate_type` 的合法值。

## 晋升步骤

1. 复制 `.gitignore`、`scripts/clean.sh`、candidate-local `references/hygiene.md` 到正式技能目录
2. 运行 `bash scripts/clean.sh` 清理正式技能目录的 bytecode
3. 验证 `find <formal-dir> -name '*.pyc' | wc -l` → 0
4. 更新 manifest：`status: observation_window`、`promotion_mode: user_delegated_agent_patch`、`formal_post_promotion`、`post_promotion_safety`

## 已知应用

- stock-workspace/20260531-pycache-hygiene-codex (6→0)
- contract-review/20260531-pycache-hygiene-hermes (15→0)
- md2word/20260531-pycache-hygiene-hermes (4→0)
- last30days/20260531-pycache-hygiene-codex (48→0)
- speech-to-text/20260531-pycache-hygiene-codex (8→0)
- canghe-manga-drama/20260531-pycache-hygiene-codex (2→0)
- canghe-manga-style-video/20260531-pycache-hygiene-codex (1→0)
