# Batch Legal Skill Screening Methodology

## Context
2026-06-02~03: Hermes screened 23 unsublated legal skills across 5 batches for overnight Codex processing.

## Screening Algorithm

1. **Full Scan**: `find ~/.hermes/skills/legal -name 'SKILL.md'` → extract metadata
2. **Exclude Already Sublated**: Cross-reference with `~/.hermes/sublation/candidates/`
3. **Score by Script Density**: `.py` count + `.sh` count + `.js`/`.ts` count
4. **Tier Assignment**:
   - Tier 1 (⭐⭐⭐): ≥5 scripts, complex logic, external API dependencies
   - Tier 2 (⭐⭐): 1-4 scripts, simpler tooling
   - Tier 3 (⭐): 0 scripts, pure documentation

## Batch Assignment

Send 3-7 skills per batch to avoid overwhelming Codex:
- Batch 1: Legal document processing (legal-text-format, paddle-ocr, funasr-transcribe)
- Batch 2: Legal research & tools (repo-research, github-star-manager, git-batch-commit, de-ai-polish)
- Batch 3: Media & content (douyin-batch-download, video-compressor, universal-media-downloader, svg-illustrator)
- Batch 4: External APIs (tingwu-asr, yuandian, zhihe, minimax×2)
- Batch 5: Infrastructure (skill-manager, piclist-upload, clawhub-sync, subtree-publish, etc.)

## Execution Requirements Per Batch

- Each skill: read SKILL.md → identify improvement points → build observation → only create candidate if trigger met
- Priority: provider contract > real bug fix > pycache hygiene > trivial fix
- Don't create candidates just for pycache unless genuinely needed
- Output: candidate + impact report for significant changes
- Notify Hermes for review after each batch

## 2026-06-03 Results

- 5 candidates created: paddle-ocr, git-batch-commit, video-compressor, tingwu-asr, piclist-upload
- 18 observation-only (no fixture or no real defect)
- All 5 candidates passed strict audit 26/26
- Pattern: all followed provider/status contract model established by polymarket/npl-monitor
