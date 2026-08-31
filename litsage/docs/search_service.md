# Search Service

LitSage 的搜索服务位于 `app/services/search_service.py`，接口入口是 `GET /api/search`。

当前策略是“本地数据库优先，外部文献源兜底”：

- 先搜索已经入库的全局文献库。
- 如果本地结果数量不足，或最高相似度低于阈值，再去 arXiv 等外部文献网站搜索。
- 外部结果只作为候选返回，不会自动写入 PostgreSQL 或 Milvus。
- 用户需要入库时，应再走“导入预览 -> 勾选 -> 入库”的流程。

## 检索流程

1. 查询改写
   - 使用 `LLMClient.rewrite_query()` 将用户原始 query 扩展为最多 3 条检索 query。
   - 改写结果默认使用英文科研检索表达；如果用户输入中文，LLM 会先翻译成英文术语再扩展。
   - `/api/search/rewrite` 可单独调试改写结果。

2. 语义召回
   - 每条改写 query 调用 `EmbeddingService.embed_text()` 生成向量。
   - 使用 Milvus `paper_abstracts` 集合做向量相似度检索。
   - 每路召回 Top-100，然后按 `paper_id` 合并，重复命中文献保留最高向量分数。

3. PostgreSQL 混合过滤
   - 根据 Milvus 命中的 `paper_id` 回表查询 `papers`。
   - 支持过滤条件：
     - `year_from`
     - `year_to`
     - `author`
     - `source`
     - `journal`
     - `citation_min`
     - `citation_max`
   - 当前 `journal` 来自 `papers.metadata` 的字符串匹配；如果后续要做严格期刊过滤，建议在 `papers` 表增加独立 `journal` 字段。

4. 本地分数阈值过滤
   - PostgreSQL 回表后，会过滤掉向量相似度低于 `SEARCH_LOCAL_MIN_SCORE` 的本地文献。
   - 前端填写的返回数量是“最多返回 N 篇”，不是“必须凑满 N 篇”。
   - 例如返回数量为 20，但只有 3 篇本地文献分数达到阈值，则本地结果只展示 3 篇。

5. 重排序
   - 当前 `Reranker` 使用本地轻量精排：向量分数 + 标题/摘要/作者词面相关性 + 引用数轻微加权。
   - 结构上已经是“粗召回 Top-100，再返回 Top-N”。如果接入真正 Cross-Encoder，只需替换 `app/llm/reranker.py` 的实现。

6. 缓存
   - Redis key 格式为 `search:{hash}`。
   - hash 内容包含 query、过滤条件、limit 和 user_id。
   - TTL 使用 `.env` 中的 `SEARCH_CACHE_TTL_SECONDS`，默认 600 秒。
   - Redis 不可用时搜索不会失败，只是跳过缓存。

7. 外部文献源兜底
   - 当本地返回数量少于 `SEARCH_LOCAL_MIN_RESULTS`，或最高向量分数低于 `SEARCH_LOCAL_MIN_SCORE`，触发外部搜索。
   - 默认外部源是 arXiv 和 PubMed。
   - 如果搜索接口传入 `source=pubmed`，外部兜底只查 PubMed；传入 `source=arxiv` 时只查 arXiv。
   - 外部补充同样会应用年份、作者、来源、期刊和引用数过滤。
   - 外部补充只补本地结果缺口，不额外设置补充上限。
   - 外部抓取候选数量由 `SEARCH_EXTERNAL_CANDIDATE_MULTIPLIER` 控制，默认抓取缺口数量的 10 倍候选用于过滤和排序。
   - 年份条件会下推到外部 API：arXiv 使用 `submittedDate`，PubMed 使用 `Date - Publication`。
   - 返回字段 `external_stats` 会说明外部需要补多少、抓到多少、通过过滤多少，以及被年份/作者/期刊等条件过滤掉多少。
   - 返回字段为 `external_results`，与本地 `results` 分开。
   - 外部结果不会参与删除、总结或 RAG，除非用户后续主动导入。

## 外部源查询策略

- arXiv：将用户 query 拆成关键词，构造成标题/摘要检索式，并使用相关性排序。
- PubMed：优先构造 `Title/Abstract` 检索式并使用相关性排序；如果严格检索没有 PMID，再回退到 PubMed 原生 query。
- 中文 query：外部搜索优先使用 LLM 生成的英文改写 query，不直接用中文原文查询英文文献网站。
- 多个外部源同时启用时，会先抓取更多候选，再合并、去重、按标题/摘要命中排序，最后截断到展示数量。

## 常用请求

```bash
curl -G "http://127.0.0.1:8000/api/search" \
  -H "Authorization: Bearer <token>" \
  --data-urlencode "q=transformer 在时间序列预测中的应用" \
  --data-urlencode "year_from=2020" \
  --data-urlencode "author=Zhang" \
  --data-urlencode "citation_min=10" \
  --data-urlencode "limit=20"
```

## 注意事项

- 语义搜索依赖导入时已成功写入摘要向量；如果 PostgreSQL 有文献但 Milvus 没有摘要向量，该文献不会被语义召回。
- 当前搜索全局文献库，符合“所有登录用户可查阅和搜索总数据库内容”的权限策略。
- 搜索分数主要来自 Milvus 相似度，精排只改变返回顺序，不会改写数据库。
- 外部搜索依赖网络；如果 VPN 或网络阻塞 arXiv/PubMed，本地搜索仍可返回，只是外部补充可能为空。
