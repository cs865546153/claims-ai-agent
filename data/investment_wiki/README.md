# 投资知识 Wiki

这是 `claims-ai-agent` 的投资领域 RAG 知识源，内容来自公开投资者教育资料，经过去个性化、去营销化整理。

## 内容边界

- 只提供投资基础、资产配置、风险与适当性、基金费用、行为偏差和诈骗识别等教育性知识；
- 不包含实时行情、具体产品推荐、收益预测或个性化配置比例；
- 不替代基金合同、招募说明书、风险揭示书和持牌机构意见；
- 所有回答都不能承诺收益或保证本金。

## 文件

| 文件 | 主题 |
| --- | --- |
| `01-investment-basics.md` | 收益、风险、时间、复利、流动性 |
| `02-asset-classes.md` | 现金、债券、股票、基金、ETF/LOF |
| `03-allocation-diversification.md` | 资产配置、分散化、相关性、再平衡 |
| `04-risk-suitability.md` | 风险类型、风险等级、适当性 |
| `05-funds-and-fees.md` | 基金类型、指数、费用、定投 |
| `06-behavior-fraud-compliance.md` | 行为偏差、诈骗识别、合规边界 |
| `07-investment-faq.md` | 风险等级、净值、回撤、费用、定投等常见问答 |

`manifest.json` 为每个文件提供标题、主题、更新日期和主要来源 URL。

## 如何进入 RAG

代码入口：`tools/investment_rag.py`。

```text
Markdown Wiki
  → 按章节切分
  → 元数据（doc_id / title / topic / chapter / source_url）
  → BM25 索引
  → BGE-M3 Embedding
  → Milvus 向量索引
  → KnowledgeBase 三路召回（dense + BM25 + metadata）
  → 加权 RRF 融合
  → BGE-Reranker 精排（失败时词项重排兜底）
  → 投资问答 Prompt
```

## 构建向量索引

先启动 BGE-M3 Embedding 服务和 Milvus，然后执行：

```powershell
python scripts/build_investment_rag.py
```

构建索引只需要 embedding + Milvus；在线问答的 BGE-Reranker 由同一个
`scripts/embed_server.py` 提供 `/v1/rerank`。当前仓库已下载并启用
`models/bge-reranker-base`。未启动 Milvus 时，投资问答会自动降级为 BM25 + 元数据
检索，并在调用链路中标记为 `compat`；Reranker 不可用时只影响精排，不会阻断回答。

## 维护建议

- 新增知识时，在 `manifest.json` 注册文件；
- 条款、费率、监管规则变化时更新 `as_of` 和内容；
- 不要写入实时行情、客户隐私、未公开产品或收益承诺；
- 定期用真实问题评测召回率和引用准确性。
