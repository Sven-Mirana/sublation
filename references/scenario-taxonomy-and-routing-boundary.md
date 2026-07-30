# Scenario Taxonomy And Routing Boundary

## Controlled Vocabulary

| ID | Label | Boundary |
|---|---|---|
| `governance` | Skill 治理 | candidate、audit、review、promotion、rollback |
| `legal_research` | 法律检索与法源核验 | 法规、案例、效力层级、检索溯源 |
| `litigation_workbench` | 诉讼工作底稿 | 请求、争点、证据、程序与策略工作底稿 |
| `document_processing` | 文档处理 | OCR、转换、结构化、排版与本地交付 |
| `article_writing` | 文章写作 | 选题、研究、起草、编辑与润色 |
| `wechat_publishing` | 微信发布 | 公众号版式、素材与发布前检查 |
| `market_daily` | 市场日报 | 市场数据、日报分析与定时交付 |
| `media_generation` | 媒体生成 | 图片、音频、视频与视觉资产 |
| `software_delivery` | 软件交付 | 代码实现、测试、构建与发布准备 |
| `general_research` | 通用研究 | 不属于专门领域的资料研究与综合 |

The vocabulary describes user workflow context, not implementation language or
runtime ownership. Additions require a new reviewed candidate; free-form aliases
must not silently expand the controlled set.

## Routing Boundary Contract

Every mapped Skill declares:

- `primary_when`: affirmative conditions for selecting it;
- `not_when`: conditions that exclude it;
- `handoff_to`: another Skill and a precise handoff condition;
- `clarify_when`: ambiguity that requires user clarification.

The route map is advisory. It does not call Skills, merge governance objects,
grant provider access, or establish that a business smoke test passed.

## Trigger-Term Discipline

`trigger_terms` are optional, user-language examples. Their presence is not a
coverage score. A future quality test may compare them with authorized fixtures,
but this v1 candidate does not infer intent from private conversations.
