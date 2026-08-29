# 文献删除与向量清理

LitSage 的文献数据分布在两个存储中：

- PostgreSQL：保存论文标题、作者、摘要、来源、发布时间、PDF 地址等元数据。
- Milvus：保存论文摘要向量和 PDF 分块向量，用于语义搜索和 RAG 检索。

如果只删除 PostgreSQL 记录，Milvus 中残留的向量仍可能被语义检索召回，从而影响 RAG 回答质量。因此删除不相关文献时，必须同步清理 Milvus 向量。

## 删除接口

```http
DELETE /api/papers/{paper_id}
```

该接口需要登录后的 Bearer Token。

`paper_id` 指 `papers.id`，是系统内部 UUID，用来精确定位数据库记录和 Milvus 向量。论文 DOI 保存在 `papers.doi` 字段中，不是当前删除接口的路径参数。

## 权限规则

当前系统的 `papers` 表是全局文献库，所有登录用户都可以查阅、搜索和总结全局文献内容。删除是破坏性操作，因此只允许删除“自己项目目录中的文献”。

由于当前表结构没有 `papers.user_id` 字段，删除权限通过项目目录关系判断：

- 该文献必须已经加入当前用户的某个项目。
- 如果该文献没有加入当前用户项目，返回 `403`。
- 如果该文献也被其他用户项目引用，返回 `409`，不会删除 PostgreSQL 记录，也不会删除 Milvus 向量。
- 只有当该文献仅被当前用户项目引用时，才允许执行全局删除和向量清理。

这保证了用户可以使用总数据库做检索和总结，但不能删除其他用户目录中的文献，也不能删除被其他用户共享引用的全局文献。

删除流程：

1. 检查 PostgreSQL 中是否存在该论文。
2. 校验当前账号是否有删除权限。
3. 删除 Milvus `paper_abstracts` 中 `paper_id` 对应的摘要向量。
4. 删除 Milvus `paper_chunks` 中 `paper_id` 对应的全文分块向量。
5. 删除 PostgreSQL `project_papers` 中的项目关联。
6. 删除 PostgreSQL `papers` 中的论文元数据。

接口会先清理 Milvus，再删除 PostgreSQL。这样可以避免 Milvus 删除失败时留下不可见但仍可召回的脏向量。

## 请求示例

```bash
curl -X DELETE "http://127.0.0.1:8000/api/papers/你的-paper-id" \
  -H "Authorization: Bearer 你的-token"
```

## 成功响应示例

```json
{
  "paper_id": "0f15fd1f-95e3-4f56-a0fb-47cb9c86f1c7",
  "deleted": true,
  "project_links_deleted": 1,
  "vector_deleted": true,
  "vector_delete_stats": {
    "paper_id": "0f15fd1f-95e3-4f56-a0fb-47cb9c86f1c7",
    "abstract_collection": "paper_abstracts",
    "chunk_collection": "paper_chunks",
    "abstract_deleted": 1,
    "chunks_deleted": 0
  },
  "vector_delete_error": null
}
```

## Milvus 删除失败

如果 Milvus 不可用或向量删除失败，接口会返回 `deleted=false`，并且不会删除 PostgreSQL 记录。

```json
{
  "paper_id": "0f15fd1f-95e3-4f56-a0fb-47cb9c86f1c7",
  "deleted": false,
  "project_links_deleted": 0,
  "vector_deleted": false,
  "vector_delete_stats": null,
  "vector_delete_error": "Milvus error message"
}
```

这种情况下应先恢复 Milvus，再重新调用删除接口。

## 后续建议

为了减少不相关文献进入系统，建议继续增加“导入预览/确认”流程：先从 arXiv 等数据源抓取候选文献，在前端展示标题和摘要，由用户勾选后再写入 PostgreSQL 和 Milvus。
