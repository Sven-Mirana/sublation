# 跨技能吸收首例：canghe-comic ← baoyu-comic

日期：2026-05-27
候选：`canghe-comic/20260527-baoyu-prompt-only-contract-codex`

## 背景

Hermes 扫描 324 个已安装技能找 sublation 候选时，最初将 `baoyu-comic` 归类为 `canghe-comic` 的"低位阶替代"。Codex 读实际 SKILL.md 后发现反转：baoyu-comic 的 Hermes 适配做得比 canghe-comic 更好——canghe-comic 假设工具是 `npx -y bun ... --ref`，在 Hermes 的 `image_generate`（prompt-only，不接受参考图）上完全不可用。

## 吸收方向

**target**: `canghe-comic`（大体系：多画风/分镜/预设 + EXTEND.md + PDF 合图）
**donor**: `baoyu-comic`（Hermes 适配：prompt-only 合约 + 绝对路径下载 + 参考图文字提取 + clarify 超时处理）

吸收 baoyu 的以下 Hermes 适配经验到 canghe-comic：
1. image_generate prompt-only 合约（不接受 --ref，参考图→文字特征→嵌入 prompt）
2. 绝对路径下载铁律（curl -o 必须绝对路径，含踩坑记录）
3. 宽高比映射表（storyboard ratio → portrait/landscape/square）
4. Prompt 文件先行规则（调用 image_generate 前必须写 prompts/*.md）
5. clarify 超时逐题默认 + 可见回声策略
6. minimalist 画风 + concept-story/four-panel 预设
7. 源内容脱敏（strip secrets）

## 不吸收的内容

- canghe-comic 的 EXTEND.md 偏好系统（保留）
- canghe-comic 的 merge-to-pdf.ts（保留）
- canghe-comic 的 config/ 体系（保留）
- baoyu-comic 的 PORT_NOTES.md（平台特定，不适用）

## 关键教训

1. **不要从描述推断位阶**——必须读实际 SKILL.md。baoyu 在 skills_list 中描述为 "Knowledge comics"，canghe 描述为 "Knowledge comic creator supporting multiple art styles"——看不出 baoyu 有更完善的 Hermes 适配。
2. **吸收的正确口径**：不是"baoyu 低位阶被吸收"，而是"canghe 大体系吸收 baoyu 的 Hermes 适配优势"。
3. **两个技能的 reference 文件大量同哈希**——画风/基调/布局定义完全相同，说明它们同源。这降低了吸收的语义冲突风险。
