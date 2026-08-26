# Paper Importer 问答确认文档

本文档整理你对 `paper_importer.py` 的确认项，以及对应的设计回答。阅读确认后，我们再进入代码实现阶段。

## Q1：首批数据源优先级怎么安排？

建议保持原方案：

```text
第一阶段：arXiv
第二阶段：Semantic Scholar
第三阶段：PubMed
```

原因：

- arXiv API 无需 API Key，最适合先跑通完整链路。
- Semantic Scholar 可无 Key 调用，但限流更严格，因此先预留 `SEMANTIC_SCHOLAR_API_KEY`。
- PubMed 推荐提供 email/API Key，因此先预留 `PUBMED_EMAIL` 和 `PUBMED_API_KEY`。

第一版实现策略：

```text
arXiv：真实实现
Semantic Scholar：预留配置和接口结构
PubMed：预留配置和接口结构
```

## Q2：PDF 下载失败是否应该跳过？

应该允许跳过。

建议策略：

```text
PDF 下载失败：跳过该文献的全文解析
元数据与摘要向量：如果已成功，则保留
接口整体任务：继续处理其他文献
```

建议默认配置：

```text
PDF 最大文件大小：30MB
PDF 下载超时：30s
全文分块大小：1500 字符
全文分块重叠：200 字符
```

原因：

- PDF 下载失败很常见，比如链接失效、反爬、重定向、无权限。
- PDF 是增强能力，不应该阻塞基础文献导入。
- 只要摘要质量足够，仍可用于初级搜索和摘要级检索。

## Q3：没有摘要的文献是否入库？

按照你的要求：不要入库。

最终策略：

```text
没有 abstract 的文献：跳过，不写入 PostgreSQL
abstract 为空字符串：跳过
abstract 只有空白字符：跳过
```

原因：

- 当前系统的核心检索依据是 `title + abstract`。
- 没有摘要时，语义向量很容易只依赖标题，表达不足。
- 这会增加搜索噪声，也可能让后续总结或问答产生误导。

## Q4：embedding 失败也不要入库吗？为什么之前建议“不影响元数据入库”？

你当前的决策是：embedding 失败不要入库。这个决策是合理的，尤其适合当前项目阶段。

我之前建议“embedding 失败不影响元数据入库”，主要是从生产系统的容错角度考虑：

```text
先保存元数据
后续通过补偿任务重新向量化
避免外部 embedding 服务短暂故障导致文献数据丢失
```

这种策略适合更成熟的系统，因为它通常会配套：

- `embedding_status` 字段
- 失败重试队列
- 后台补偿任务
- 管理后台查看失败原因

但当前第一版项目还没有这些补偿机制。如果 embedding 失败仍然入库，会带来几个问题：

- 数据库里有文献，但语义搜索搜不到。
- 用户以为文献已经完整可用，但实际上向量缺失。
- 后续 RAG 或总结链路状态不一致。
- 需要额外字段标记“未向量化”，增加第一版复杂度。

所以按照你的目标，第一版更建议采用强一致策略：

```text
abstract 存在
→ embedding 成功
→ PostgreSQL 入库
→ Milvus 写入

任一关键步骤失败
→ 跳过该文献
→ 记录 failed 统计和错误原因
```

这个策略更干净，适合早期开发和调试。

## Q5：现阶段是否同步实现 Milvus？

可以，同步实现 Milvus 是合理的。

实现范围建议：

```text
1. 初始化/连接 Milvus
2. 创建 paper_abstracts collection
3. 创建 paper_chunks collection
4. 写入摘要向量
5. 写入 PDF chunk 向量
6. 支持按向量相似度检索
```

需要注意：

- Milvus collection 的向量维度必须和 embedding 输出维度一致。
- 当前 `.env` 默认 `EMBEDDING_DIM=1024`，如果后续使用 OpenAI `text-embedding-3-large`，实际维度通常可能不一致，需要统一配置。
- 如果 embedding 模型变化，Milvus collection 可能需要重建。

建议后续确认：

```text
最终 embedding 模型：
实际 embedding 维度：
Milvus 是否允许自动创建 collection：
```

## Q6：第一版采用同步导入还是 Celery 异步？

按照你的确认：第一版采用同步导入。

也就是：

```text
POST /api/papers/import
→ API 请求中直接执行导入
→ 执行完成后返回统计结果
```

优点：

- 调试简单。
- 错误直接返回。
- 不需要同时启动 Celery worker。
- 适合先跑通 arXiv + PostgreSQL + Embedding + Milvus 主链路。

缺点：

- 大批量导入时请求会等待较久。
- 不适合生产环境长任务。

后续切换 Celery 时，可以保留同一套内部导入函数，只把入口从同步调用换成任务投递。

## Q7：是否扩展 `stats` 字段？

接受扩展 `stats` 字段是正确的。

建议响应格式：

```json
{
  "task_id": "uuid",
  "status": "completed",
  "message": "Fetched 20 papers, created 12, updated 5, skipped 3, failed 0",
  "stats": {
    "fetched": 20,
    "created": 12,
    "updated": 5,
    "skipped_no_abstract": 2,
    "skipped_embedding_failed": 1,
    "abstract_vectorized": 17,
    "pdf_processed": 0,
    "failed": 0
  }
}
```

建议同时保留简单的 `message`，这样 Streamlit 前端展示更友好。

## Q8：去重规则怎么定？

按照原建议：

```text
1. DOI 相同，视为同一篇文献
2. source + source_id 相同，视为同一篇文献
3. 标题完全相同且发布日期相同，暂不自动合并，只记录为潜在重复
```

第一版建议实际执行：

```text
优先按 source + source_id upsert
如果 DOI 存在，再按 DOI 辅助判断
```

原因：

- arXiv、PubMed、Semantic Scholar 都有自己的稳定 ID。
- DOI 有时为空，有时格式不统一。
- 标题匹配容易误伤，例如预印本和正式发表版本标题很接近但不完全等价。

## 最终暂定实现决策

```text
首批真实实现数据源：arXiv
Semantic Scholar：预留 API Key 和接口
PubMed：预留 email/API Key 和接口
PDF 下载失败：允许跳过
PDF 最大大小：30MB
PDF 下载超时：30s
分块大小：1500 字符
分块重叠：200 字符
无摘要文献：不入库
embedding 失败：不入库
本阶段实现 Milvus：是
导入执行方式：同步导入
响应字段：扩展 stats
去重规则：DOI + source/source_id
```

## 待你最终确认的问题

在正式写代码前，还需要你确认两个关键点：

```text
1. 你的 embedding 模型最终用哪个？
2. 该 embedding 模型输出维度是多少？
```

Milvus collection 必须提前知道向量维度。如果维度配置错，写入会失败。

