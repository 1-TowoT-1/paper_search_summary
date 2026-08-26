# Paper Importer 实现说明

当前已实现 `app/services/paper_importer.py` 的第一版同步导入流程。

## 已实现能力

- arXiv 真实导入
- Semantic Scholar / PubMed 预留接口
- 无摘要文献跳过，不入库
- BGE-M3 embedding 失败跳过，不入库
- Milvus 摘要向量写入成功后再提交 PostgreSQL
- PDF 下载失败允许跳过
- 可选 PDF 全文解析、分块、embedding、写入 Milvus
- `POST /api/papers/import` 同步返回导入统计

## 关键配置

```env
EMBEDDING_PROVIDER=local_bge
EMBEDDING_DIM=1024
BGE_BASE_URL=http://localhost:8001
BGE_EMBEDDING_PATH=/embed
BGE_REQUEST_FORMAT=bge
BGE_TIMEOUT_SECONDS=60

MILVUS_URI=http://localhost:19530
ABSTRACT_COLLECTION=paper_abstracts
CHUNK_COLLECTION=paper_chunks
MILVUS_METRIC_TYPE=COSINE

EXTERNAL_API_TIMEOUT_SECONDS=30
PDF_MAX_SIZE_MB=30
PDF_DOWNLOAD_TIMEOUT_SECONDS=30
PDF_CHUNK_SIZE=1500
PDF_CHUNK_OVERLAP=200

SEMANTIC_SCHOLAR_API_KEY=
PUBMED_EMAIL=
PUBMED_API_KEY=
```

## BGE-M3 HTTP 服务格式

默认请求：

```http
POST {BGE_BASE_URL}{BGE_EMBEDDING_PATH}
Content-Type: application/json

{
  "texts": ["需要向量化的文本"]
}
```

支持的响应格式之一：

```json
{
  "embeddings": [[0.1, 0.2]]
}
```

也支持：

```json
{"embedding": [0.1, 0.2]}
```

```json
[[0.1, 0.2]]
```

```json
{
  "data": [
    {"embedding": [0.1, 0.2]}
  ]
}
```

如果你的 BGE 服务是 OpenAI-compatible embeddings 接口，配置：

```env
BGE_REQUEST_FORMAT=openai
BGE_EMBEDDING_PATH=/v1/embeddings
EMBEDDING_MODEL=bge-m3
```

请求会变成：

```json
{
  "model": "bge-m3",
  "input": ["需要向量化的文本"]
}
```

## Milvus 行为

首次写入时会自动创建：

```text
paper_abstracts
paper_chunks
```

两个 collection 都使用：

```text
FLOAT_VECTOR dim=1024
metric_type=COSINE
index_type=AUTOINDEX
```

如果后续更换 embedding 维度，需要删除或重建 Milvus collection。

## 导入接口返回示例

```json
{
  "task_id": "uuid",
  "status": "completed",
  "message": "Fetched 10 papers, created 8, updated 2, skipped no abstract 0, skipped embedding/vector 0, failed 0.",
  "stats": {
    "fetched": 10,
    "created": 8,
    "updated": 2,
    "skipped_no_abstract": 0,
    "skipped_embedding_failed": 0,
    "abstract_vectorized": 10,
    "pdf_processed": 0,
    "pdf_skipped": 0,
    "failed": 0,
    "errors": []
  }
}
```

