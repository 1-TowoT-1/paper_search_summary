# Paper Importer 需求确认文档

本文档用于确认 `app/services/paper_importer.py` 的实现边界。确认后即可按本文档开发文献导入模块。

## 1. 模块目标

文献导入模块负责根据用户输入的检索词，从外部文献数据源抓取文献元数据，写入 PostgreSQL，并生成向量写入向量数据库。

目标流程：

```text
导入请求
→ 调用外部数据源 API
→ 标准化元数据
→ PostgreSQL upsert
→ 标题 + 摘要向量化
→ 写入 paper_abstracts 向量集合
→ 可选下载 PDF
→ PDF 全文解析与分块
→ 写入 paper_chunks 向量集合
→ 返回导入统计
```

## 2. 需要你提供或确认的内容

### 2.1 首批数据源优先级

请确认第一版先实现哪个数据源。

建议：

```text
第一阶段：arXiv
第二阶段：Semantic Scholar
第三阶段：PubMed
```

原因：arXiv API 无需 API Key，适合先跑通完整导入链路。

请确认：

```text
首批真实实现数据源：
是否允许其他数据源先返回空结果：
```

### 2.2 Semantic Scholar API Key

Semantic Scholar 可无 Key 使用，但限流更严格；如果你有 API Key，可以提供环境变量名。

建议环境变量：

```env
SEMANTIC_SCHOLAR_API_KEY=
```

请确认：

```text
是否接入 Semantic Scholar：
是否有 API Key：
```

### 2.3 PubMed 邮箱与 API Key

PubMed / NCBI E-utilities 推荐提供 email，频繁调用建议提供 API Key。

建议环境变量：

```env
PUBMED_EMAIL=
PUBMED_API_KEY=
```

请确认：

```text
是否接入 PubMed：
联系邮箱：
是否有 API Key：
```

### 2.4 PDF 下载策略

`include_pdf=True` 时，模块会尝试下载并解析 PDF。

需要确认：

```text
PDF 下载失败是否允许跳过：建议允许
单篇 PDF 最大文件大小：建议 30MB
PDF 下载超时时间：建议 30s
全文分块大小：建议 1500 字符
全文分块重叠：建议 200 字符
```

### 2.5 向量化策略

目前 `EmbeddingService` 已有占位实现，后续可替换成真实 embedding API。

需要确认：

```text
摘要向量文本格式：建议 title + "\n\n" + abstract
没有 abstract 的文献是否入库：建议入库，但不写摘要向量
embedding 失败是否影响元数据入库：建议不影响
```

### 2.6 向量数据库实现状态

目前 `VectorStore` 是抽象占位实现。

需要确认：

```text
是否本阶段同步实现 Milvus：
Milvus 地址：
abstract collection 名称：
chunk collection 名称：
embedding 维度：
```

默认使用 `.env` 中：

```env
MILVUS_URI=http://localhost:19530
ABSTRACT_COLLECTION=paper_abstracts
CHUNK_COLLECTION=paper_chunks
EMBEDDING_DIM=1024
```

### 2.7 异步任务策略

当前接口 `POST /api/papers/import` 返回 `task_id`，符合异步任务设计。

有两种实现方式：

```text
方案 A：先同步执行导入，再返回统计结果
方案 B：真正接入 Celery，接口立即返回 task_id，后台导入
```

建议：

```text
开发阶段先用方案 A，方便调试；
导入流程跑通后切换到方案 B。
```

请确认：

```text
第一版采用同步导入还是 Celery 异步导入：
```

### 2.8 导入结果返回格式

建议导入接口返回：

```json
{
  "task_id": "uuid",
  "status": "completed",
  "message": "Fetched 20 papers, created 12, updated 8, failed 0",
  "stats": {
    "fetched": 20,
    "created": 12,
    "updated": 8,
    "abstract_vectorized": 20,
    "pdf_processed": 0,
    "failed": 0
  }
}
```

这意味着需要扩展当前 `ImportPapersResponse` schema，增加可选 `stats` 字段。

请确认：

```text
是否接受扩展响应字段 stats：
```

### 2.9 去重规则

建议优先级：

```text
1. DOI 相同视为同一篇
2. source + source_id 相同视为同一篇
3. 标题完全相同且发布日期相同视为疑似同一篇，第一版暂不自动合并
```

请确认：

```text
是否按 DOI 和 source_id 去重：
```

### 2.10 网络访问

文献导入需要访问外部 API：

```text
arxiv.org
api.semanticscholar.org
eutils.ncbi.nlm.nih.gov
PDF URL 对应域名
```

请确认开发环境是否能访问这些地址。

## 3. 第一版建议实现范围

我建议第一版实现：

```text
1. arXiv 真实导入
2. 统一 ImportedPaper 数据结构
3. PostgreSQL upsert
4. 摘要 embedding 调用
5. VectorStore 写入调用
6. PDF 下载与解析工具函数
7. Semantic Scholar / PubMed 留接口占位
8. 返回详细导入统计
```

第一版暂不强制：

```text
1. 真实 Celery 后台任务
2. 真实 Milvus collection 初始化
3. Cross-source 标题模糊去重
4. 大规模并发抓取
```

## 4. 验收标准

完成后应满足：

```text
1. POST /api/papers/import 可以导入 arXiv 文献
2. papers 表中出现真实文献元数据
3. 重复导入同一 query 不产生重复 source_id 数据
4. include_pdf=false 时不下载 PDF
5. 单篇导入失败不影响其他文献
6. 接口返回导入统计
7. Streamlit 前端可以触发导入并展示结果
```

## 5. 你可以直接回复的确认模板

```text
首批真实实现数据源：arXiv
其他数据源先占位：是
Semantic Scholar：暂不接入 / 接入，API Key 为 ...
PubMed：暂不接入 / 接入，email 为 ...
PDF 下载失败是否跳过：是
PDF 最大大小：30MB
分块大小：1500
分块重叠：200
没有 abstract 是否入库：是
embedding 失败是否影响入库：否
本阶段是否实现 Milvus：否 / 是
导入执行方式：同步导入 / Celery 异步
是否扩展 stats 字段：是
去重规则：DOI + source/source_id
```

