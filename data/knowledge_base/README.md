# 通用知识库

把业务文档直接放进本目录即可被 `/api/rag/search` 和 `/api/rag/answer` 检索。

## 支持格式

- Markdown（`.md` / `.markdown`）：按 `##` 二级标题切分章节，最适合 Wiki。
- 纯文本 `.txt`、PDF `.pdf`、Word `.docx`、HTML `.html` / `.htm`。

根目录的 `README.md` 不会进入索引；子目录会按相对路径写入 `source` 元数据。

## 推荐结构

```text
data/knowledge_base/
├── README.md
├── product/
│   ├── pricing.md
│   └── faq.md
└── policy/
    └── onboarding.md
```

## 检索配置

- 默认 domain：`general`
- 默认集合：`knowledge_general`
- 如需自定义目录或集合，修改 `.env`：

```bash
KNOWLEDGE_BASE_DIR=data/knowledge_base
KNOWLEDGE_RAG_COLLECTION=knowledge_general
KNOWLEDGE_RAG_TOP_K=5

# 精排；未启动模型服务时自动降级为词项重排
RERANK_ENABLED=true
RERANK_BASE_URL=http://127.0.0.1:8010/v1
RERANK_MODEL=bge-reranker-base
```

检索链路默认是 **dense + BM25 + 元数据** 三路召回，加权 RRF 后交给
BGE-Reranker 精排。当前开发机已下载 `models/bge-reranker-base`；模型或服务不可用时
自动降级为词项重排，检索不中断。

首次检索时才会加载本目录。新增或修改文档后需要重启应用，让 BM25/元数据索引
重新加载；如需让 dense 向量召回也覆盖新文档，再重建 Milvus 索引：

```bash
python scripts/build_knowledge_rag.py --domain general
```
