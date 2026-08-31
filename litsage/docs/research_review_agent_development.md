# LitSage 科研文献调研与综述生成 Agent 开发文档

## 1. 项目新定位

原定位：

```text
文献智能搜索与总结系统
```

升级定位：

```text
面向科研选题、文献调研和综述写作的可追溯文献工作流 Agent
```

核心目标不再只是“总结单篇论文”，而是帮助用户完成完整科研调研流程：

```text
Search → Ingest → Understand → Compare → Cite → Write
检索 → 入库 → 理解 → 对比 → 引用溯源 → 综述生成
```

## 2. 核心亮点

### 2.1 可追溯

所有总结、问答和综述内容都要尽量关联到：

```text
paper_id
标题
页码
chunk_id
原文片段
图表编号
数据来源
```

目标是避免大模型“说得像真的，但找不到证据”。

### 2.2 可积累

系统不是一次性 PDF 总结工具，而是长期保存用户的研究项目、文献集合、全文片段、图表解释和笔记。

### 2.3 可比较

支持多篇论文的横向对比：

```text
研究问题
核心方法
数据集
实验指标
创新点
局限性
代码是否开源
适合精读程度
```

### 2.4 可写作

系统最终应能生成带引用依据的：

```text
Related Work 草稿
研究脉络总结
技术路线对比
研究空白分析
未来方向建议
```

## 3. 用户核心场景

### 场景一：新课题调研

用户输入：

```text
扩散模型在医学图像分割中的应用
```

系统输出：

```text
相关论文列表
筛选建议
研究方向聚类
关键论文推荐
综述框架
```

### 场景二：项目文献库建设

用户将一批论文加入某个研究项目，系统自动：

```text
解析摘要和全文
抽取方法/数据集/指标
提取图表信息
建立向量索引
生成结构化卡片
```

### 场景三：多论文对比

用户选择 10-30 篇论文，系统生成对比表：

```text
论文
方法
数据集
指标
优势
局限
证据来源
```

### 场景四：带引用问答

用户提问：

```text
这些论文中哪些方法真正提升了 Dice 指标？
```

系统回答必须附引用：

```text
回答结论
支撑论文
具体片段
页码或 chunk
```

### 场景五：综述草稿生成

用户基于项目文献库生成：

```text
Related Work
研究脉络
方法分类
挑战与未来方向
```

## 4. 功能模块规划

### 4.1 文献检索与导入模块

目标：

```text
从 arXiv / Semantic Scholar / PubMed 等来源获取文献，并统一入库。
```

第一版：

```text
arXiv 真实导入
Semantic Scholar / PubMed 预留接口
无摘要不入库
BGE-M3 embedding 失败不入库
Milvus 写入成功后再提交 PostgreSQL
```

后续增强：

```text
跨源去重
引用数更新
代码仓库链接抽取
会议/期刊字段补全
```

### 4.2 文献理解模块

目标：

```text
将论文从非结构文本转成结构化知识卡片。
```

建议结构化字段：

```text
research_problem
method
contribution
dataset
metrics
main_results
limitations
future_work
keywords
```

输出对象：

```text
PaperInsight
```

### 4.3 图表理解模块

目标：

```text
解析 PDF 中的图表，并让大模型总结图表含义。
```

第一版可先做：

```text
提取图表所在页
保存图表附近文本
让多模态模型解释图表
关联 paper_id 和 page_number
```

后续增强：

```text
图像裁剪
表格结构化抽取
指标表自动转 DataFrame
```

### 4.4 多论文对比模块

目标：

```text
针对一个项目或一组文献，生成横向对比矩阵。
```

典型输出：

```text
method_comparison
dataset_comparison
metric_comparison
limitation_comparison
```

### 4.5 RAG 问答模块

目标：

```text
围绕单篇论文、项目集合或搜索结果进行可追溯问答。
```

必须增强：

```text
引用片段
页码
chunk_id
paper_id
回答置信度或证据充分性
```

### 4.6 综述生成模块

目标：

```text
根据项目文献库生成综述草稿。
```

建议输出：

```text
研究背景
方法分类
代表性工作
对比分析
局限与挑战
未来方向
参考引用列表
```

### 4.7 项目工作台模块

目标：

```text
围绕“研究项目”组织文献、问答、对比表、综述草稿和笔记。
```

项目内应支持：

```text
收藏文献
批量分析
对比表
综述草稿
问答历史
导出 Markdown
```

## 5. 数据库改造建议

现有表：

```text
papers
users
projects
project_papers
summary_tasks
```

建议新增表：

### 5.1 paper_chunks

保存全文分块和页码信息。

```sql
paper_chunks (
    id UUID PRIMARY KEY,
    paper_id UUID REFERENCES papers(id),
    chunk_index INT,
    text TEXT,
    page_start INT,
    page_end INT,
    token_count INT,
    metadata JSONB,
    created_at TIMESTAMP
)
```

### 5.2 paper_insights

保存单篇论文结构化理解结果。

```sql
paper_insights (
    id UUID PRIMARY KEY,
    paper_id UUID REFERENCES papers(id),
    research_problem TEXT,
    method TEXT,
    contribution TEXT,
    dataset JSONB,
    metrics JSONB,
    main_results TEXT,
    limitations TEXT,
    future_work TEXT,
    keywords JSONB,
    evidence JSONB,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
)
```

### 5.3 paper_figures

保存图表信息和解释。

```sql
paper_figures (
    id UUID PRIMARY KEY,
    paper_id UUID REFERENCES papers(id),
    figure_label VARCHAR,
    page_number INT,
    caption TEXT,
    surrounding_text TEXT,
    image_path TEXT,
    interpretation TEXT,
    metadata JSONB,
    created_at TIMESTAMP
)
```

### 5.4 comparison_reports

保存多论文对比结果。

```sql
comparison_reports (
    id UUID PRIMARY KEY,
    project_id UUID REFERENCES projects(id),
    paper_ids UUID[],
    report_type VARCHAR,
    result JSONB,
    markdown TEXT,
    created_at TIMESTAMP
)
```

### 5.5 review_drafts

保存综述草稿。

```sql
review_drafts (
    id UUID PRIMARY KEY,
    project_id UUID REFERENCES projects(id),
    title VARCHAR,
    outline JSONB,
    markdown TEXT,
    citations JSONB,
    status VARCHAR,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
)
```

### 5.6 qa_messages

保存项目问答历史。

```sql
qa_messages (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    project_id UUID REFERENCES projects(id),
    session_id VARCHAR,
    role VARCHAR,
    content TEXT,
    citations JSONB,
    created_at TIMESTAMP
)
```

## 6. API 改造建议

### 6.1 文献理解

```text
POST /api/papers/{id}/analyze
GET  /api/papers/{id}/insight
```

### 6.2 图表理解

```text
POST /api/papers/{id}/figures/extract
GET  /api/papers/{id}/figures
```

### 6.3 多论文对比

```text
POST /api/projects/{id}/compare
GET  /api/projects/{id}/comparisons
GET  /api/comparisons/{id}
```

### 6.4 综述生成

```text
POST /api/projects/{id}/review-draft
GET  /api/projects/{id}/review-drafts
GET  /api/review-drafts/{id}
```

### 6.5 项目问答增强

```text
POST /api/qa
GET  /api/projects/{id}/qa-sessions
GET  /api/qa/sessions/{session_id}
```

## 7. Agent 工作流设计

### 7.1 文献调研 Agent

输入：

```text
研究主题
筛选条件
目标数量
```

步骤：

```text
1. 查询改写
2. 多源检索
3. 元数据去重
4. 摘要筛选
5. 导入候选文献
6. 生成研究方向聚类
7. 推荐精读论文
```

### 7.2 单篇理解 Agent

输入：

```text
paper_id
```

步骤：

```text
1. 检索摘要和全文 chunk
2. 抽取结构化字段
3. 提取支撑证据
4. 保存 PaperInsight
```

### 7.3 对比分析 Agent

输入：

```text
project_id 或 paper_ids
```

步骤：

```text
1. 加载 PaperInsight
2. 缺失 insight 则自动补分析
3. 生成对比矩阵
4. 标注证据来源
5. 保存 comparison report
```

### 7.4 综述写作 Agent

输入：

```text
project_id
写作目标
语言
篇幅
```

步骤：

```text
1. 加载项目文献
2. 加载结构化 insight
3. 加载对比报告
4. 生成大纲
5. 生成分节草稿
6. 添加引用标注
7. 输出 Markdown
```

## 8. 前端改造建议

当前 Streamlit 前端主要是接口调试台。

建议改造成项目工作台：

```text
首页：研究项目列表
项目页：文献列表 + 调研状态
文献页：摘要、全文片段、结构化卡片、图表解释
对比页：多论文对比矩阵
问答页：项目级 RAG
写作页：综述草稿生成与编辑
```

## 9. 分阶段开发计划

### 阶段一：可靠文献库

目标：

```text
能稳定导入 arXiv 文献，写入 PostgreSQL + Milvus。
```

任务：

```text
1. 完善 paper_importer
2. 完善 BGE-M3 embedding
3. 完善 Milvus 检索
4. SearchService 从 Milvus 命中回表
5. Streamlit 展示真实搜索结果
```

### 阶段二：单篇理解

目标：

```text
生成可保存的 PaperInsight。
```

任务：

```text
1. 新增 paper_insights 表
2. 新增 analyze_service
3. 新增 /api/papers/{id}/analyze
4. 前端展示结构化论文卡片
```

### 阶段三：项目级对比

目标：

```text
对项目内多篇论文生成对比矩阵。
```

任务：

```text
1. 新增 comparison_service
2. 新增 comparison_reports 表
3. 新增项目对比 API
4. 前端展示对比表
```

### 阶段四：可追溯 RAG

目标：

```text
回答带 paper_id、chunk_id、页码和证据片段。
```

任务：

```text
1. PostgreSQL 保存 paper_chunks
2. RAGService 回表取 chunk
3. QAResponse 增加 evidence 字段
4. 保存 qa_messages
```

### 阶段五：综述生成

目标：

```text
生成带引用的 Related Work / 综述草稿。
```

任务：

```text
1. 新增 review_service
2. 新增 review_drafts 表
3. 生成大纲
4. 生成分节草稿
5. 引用校验
6. Markdown 导出
```

## 10. 原项目需要改动的模块清单

### 10.1 `app/models/db.py`

需要新增：

```text
PaperChunk
PaperInsight
PaperFigure
ComparisonReport
ReviewDraft
QAMessage
```

同时建议给 `papers` 表补充：

```text
venue
publication_type
code_url
landing_url
import_status
analysis_status
```

### 10.2 `app/models/schemas.py`

需要新增：

```text
PaperInsightRead
PaperAnalyzeResponse
PaperFigureRead
ComparisonRequest
ComparisonResponse
ReviewDraftRequest
ReviewDraftResponse
EnhancedCitation
EvidenceSnippet
```

需要增强：

```text
QAResponse
SearchResult
PaperRead
```

### 10.3 `app/services/paper_importer.py`

需要继续增强：

```text
跨源去重
Semantic Scholar 导入
PubMed 导入
PDF chunk 同步写 PostgreSQL
导入状态字段
失败原因持久化
```

### 10.4 `app/services/vector_store.py`

需要增强：

```text
按 paper_id 删除旧 chunk 向量
返回 chunk_id、page_start、page_end
支持 metadata filter
支持 collection 重建/健康检查
```

### 10.5 `app/services/search_service.py`

需要重写为真实搜索：

```text
查询改写
BGE-M3 embedding
Milvus 召回
PostgreSQL 回表
过滤条件
去重
排序
返回真实 SearchResult
```

### 10.6 `app/services/rag_service.py`

需要增强为可追溯 RAG：

```text
检索 chunk
回表拿原文片段和页码
构造带 citation marker 的 prompt
回答后绑定 citations
保存 QA 历史
```

### 10.7 `app/services/summary_service.py`

需要升级：

```text
单篇结构化总结
项目聚合总结
对比性总结
引用证据绑定
Markdown 导出
```

### 10.8 新增 `app/services/analyze_service.py`

负责：

```text
单篇论文结构化理解
证据抽取
PaperInsight 保存
```

### 10.9 新增 `app/services/figure_service.py`

负责：

```text
PDF 图表附近文本提取
多模态图表解释
PaperFigure 保存
```

### 10.10 新增 `app/services/comparison_service.py`

负责：

```text
多论文对比矩阵
方法/数据集/指标/局限横向分析
ComparisonReport 保存
```

### 10.11 新增 `app/services/review_service.py`

负责：

```text
综述大纲生成
Related Work 草稿生成
引用校验
ReviewDraft 保存
```

### 10.12 `app/api/routes/papers.py`

需要增加：

```text
POST /api/papers/{id}/analyze
GET  /api/papers/{id}/insight
POST /api/papers/{id}/figures/extract
GET  /api/papers/{id}/figures
```

### 10.13 `app/api/routes/projects.py`

需要增加：

```text
POST /api/projects/{id}/compare
GET  /api/projects/{id}/comparisons
POST /api/projects/{id}/review-draft
GET  /api/projects/{id}/review-drafts
```

### 10.14 `app/api/routes/qa.py`

需要增强：

```text
返回 evidence snippets
保存 session
支持项目级历史查询
```

### 10.15 `frontend/streamlit_app.py`

需要从接口调试台升级为研究工作台：

```text
项目总览
文献库
单篇分析页
图表理解页
对比矩阵页
问答页
综述写作页
```

### 10.16 `migrations/versions`

需要新增迁移：

```text
paper_chunks
paper_insights
paper_figures
comparison_reports
review_drafts
qa_messages
papers 表字段扩展
```

### 10.17 `docs`

需要补充：

```text
Agent 工作流文档
数据库设计文档
API 设计文档
前端页面设计文档
验收测试文档
```

## 11. 优先级建议

最推荐的开发顺序：

```text
1. SearchService 接真实 Milvus + PostgreSQL 回表
2. paper_chunks 落 PostgreSQL，RAG 可追溯
3. PaperInsight 单篇结构化理解
4. Project Comparison 多论文对比
5. ReviewDraft 综述生成
6. Streamlit 改成项目工作台
7. Celery 异步化
```

原因：

```text
先保证文献库和检索真实可用
再做理解和对比
最后做综述生成
```

