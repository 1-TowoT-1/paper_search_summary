# 文献预览与勾选入库

导入模块现在支持两步流程，避免不相关文献直接进入 PostgreSQL 和 Milvus。

## 流程

1. 前端输入导入查询，例如 `liver cancer`。
2. 调用预览接口抓取候选文献，但不写入数据库。
3. 前端展示标题、作者、摘要、DOI、来源 ID、发布时间。
4. 用户排序并勾选需要的文献。
5. 调用确认入库接口，只导入勾选文献。

## 预览接口

```http
POST /api/papers/import/preview
```

请求：

```json
{
  "query": "liver cancer",
  "sources": ["arxiv"],
  "limit": 20,
  "include_pdf": false
}
```

该接口只返回候选文献，不生成 embedding，不写 PostgreSQL，不写 Milvus。

## 勾选入库接口

```http
POST /api/papers/import/selected
```

请求：

```json
{
  "include_pdf": false,
  "papers": [
    {
      "title": "Paper title",
      "authors": [{"name": "Author"}],
      "abstract": "Paper abstract",
      "doi": null,
      "source": "arxiv",
      "source_id": "2608.00001",
      "published_date": "2026-08-01",
      "pdf_url": "https://arxiv.org/pdf/2608.00001",
      "citation_count": 0,
      "metadata": {}
    }
  ]
}
```

该接口会对勾选文献执行正式入库流程：

- 生成标题和摘要 embedding。
- 写入 Milvus `paper_abstracts`。
- 如果 `include_pdf=true`，解析 PDF 并写入 `paper_chunks`。
- 写入 PostgreSQL `papers`。

## 重复文献策略

正式入库前会先检查 PostgreSQL 是否已有相同文献。判定规则：

- `source + source_id` 相同。
- 或者 DOI 相同。

如果判定为重复文献，默认会直接跳过：

- 不更新 PostgreSQL。
- 不生成 embedding。
- 不写入 Milvus。
- 统计中增加 `skipped_duplicate`。

这样可以避免不同用户重复导入同一篇公开文献时反复访问 embedding 模型和向量数据库。

如果用户勾选 `include_pdf=true`，重复文献会额外检查 Milvus 中是否已经存在全文分块：

- PostgreSQL `metadata.pdf_status=completed`，并且 Milvus 中存在 `paper_chunks`：跳过 PDF，统计中增加 `pdf_already_processed`。
- 没有完成标记，或 Milvus 中不存在 `paper_chunks`：先清理该文献可能残留的旧 `paper_chunks`，再重试 PDF 下载、解析、分块和 chunk embedding，统计中增加 `pdf_retried`。

这种情况下仍然不会更新 PostgreSQL，也不会重建摘要向量。它只用于补救此前“元数据和摘要向量入库成功，但 PDF 解析失败”的文献。

PDF 处理结果会写入 PostgreSQL 的 `papers.metadata`：

- `pdf_status`: `completed` 或 `failed`
- `pdf_chunk_count`: 成功写入的全文分块数量
- `pdf_last_error`: 最近一次 PDF 失败原因

历史数据如果只有残留 chunks，但没有 `pdf_status=completed`，不会被认为已经处理完成。

## 旧接口

```http
POST /api/papers/import
```

旧接口仍保留，会搜索后直接入库。调试或正式使用时，建议优先使用预览和勾选入库流程。
