# 上游同步方法论

## 触发条件
全库 skill 筛选前，必须先做上游同步，避免对着旧版本做无用功。

## 源仓库识别
1. 搜 SKILL.md 中的 `github.com` URL
2. 查 `hermes skills tap list` 已注册的 tap
3. 查 skill 目录下是否有 `.git`

## 同步流程
1. `git clone --depth 1 <repo> /tmp/<repo>`
2. `diff -rq /tmp/<repo>/skills/<name>/ ~/.hermes/skills/<path>/<name>/`（排除 __pycache__, .pyc, .DS_Store）
3. 对 SUBLATED 技能：`rsync -a --delete --exclude='<local-artifacts>' /tmp/... ~/.hermes/skills/...`
4. 非 SUBLATED：直接 `rsync -a --delete`
5. 复跑 `lifecycle.py health` 检查 source drift

## 已验证案例（2026.6.2）
- 4 源仓库：JimLiu/canghe-skills, JimLiu/baoyu-skills, cat-xierluo/legal-skills, lijigang/ljg-skills
- 32 skill 同步，5 SUBLATED 全部与上游正交无冲突
- 发现 2 个上游编码 bug 并修复（legal-text-format Python 语法, skill-manager Bash 引号）
- ledger: 97KB JSON, rollback point 已建
