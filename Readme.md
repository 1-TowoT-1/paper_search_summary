文献智能搜索与总结 Agent 项目描述模板

项目概述

项目名称：LitSage —— 基于大模型的文献智能搜索与总结系统

项目定位：面向科研人员的智能文献助手，支持自然语言检索、多维筛选、自动摘要与知识问答。

核心价值：将传统关键词检索升级为语义检索，将逐篇阅读压缩为智能总结，显著提升文献调研效率。

技术栈

层级 技术选型 用途说明
后端框架 FastAPI 提供 RESTful API 与 WebSocket 接口
任务队列 Celery + Redis 异步处理文献抓取、向量化等耗时任务
缓存层 Redis 缓存热点查询结果、用户会话、API 限流计数
关系数据库 PostgreSQL 存储文献元数据、用户信息、项目/收藏关系
向量数据库 Milvus 存储文献 embedding，支持语义相似度检索
大模型 OpenAI / 本地 ollama 部署 摘要生成、查询改写、RAG 问答
嵌入模型 BGE-M3 / text-embedding-3-large 文献标题/摘要向量化
RAG 框架 LangChain / LlamaIndex 检索增强生成的编排与 Prompt 管理
文献数据源 arXiv API / Semantic Scholar / PubMed 外部文献数据获取

核心功能模块

1. 文献数据管理模块

· 支持从 arXiv、Semantic Scholar、PubMed 等数据源批量抓取文献元数据（标题、作者、摘要、发表时间、DOI 等）
· 文献入库时自动向量化（标题 + 摘要拼接后生成 embedding），写入向量数据库
· 支持 PDF 全文解析（PyMuPDF），全文切片后存入向量库以支持深度问答
· PostgreSQL 存储完整元数据，与向量库通过文献 ID 关联

2. 智能搜索模块

· 语义搜索：用户输入自然语言描述（如 "transformer 在时间序列预测中的应用"），系统使用 embedding 进行向量相似度检索
· 混合搜索：结合 PostgreSQL 关键词过滤（年份、作者、期刊、引用数）与向量相似度排序
· 查询改写：使用 LLM 对用户原始 query 进行扩展和改写，生成多路检索查询，提升召回率
· 重排序（Rerank）：粗召回 Top-100 后使用 Cross-Encoder 模型精排，返回 Top-20

3. RAG 文献问答模块

· 用户可针对单篇文献或一个文献集合（如某个搜索结果）进行问答
· 检索流程：用户问题 → 向量检索相关文献片段 → 拼接上下文 → LLM 生成回答（带引用标注）
· 支持对话记忆（Redis 存储会话历史），多轮追问
· 回答中引用具体文献和片段位置，保证可溯源性

4. 智能总结模块

· 单篇总结：对文献全文或摘要生成结构化总结（研究背景、方法、创新点、局限）
· 批量总结：对一组文献生成综述性对比总结（研究脉络、主流方法、待解决问题）
· 总结结果支持 Markdown 格式导出
· 总结任务通过 Celery 异步执行，避免阻塞 API

5. 用户与项目模块

· 用户注册/登录（JWT 认证）
· 用户可创建"研究项目"，将搜索结果、文献收藏归档到项目下
· 项目内支持批量总结和聚合问答

关键工作流程

流程一：文献搜索

```
用户输入自然语言查询
    → LLM 查询改写（生成 2-3 个变体）
    → 每个变体分别进行向量检索
    → 结果合并去重
    → 元数据过滤（PostgreSQL）
    → Cross-Encoder 重排序
    → 返回结果列表
    → 缓存查询结果（Redis，TTL 10min）
```

流程二：文献入库

```
外部数据源 API 调用
    → 清洗元数据
    → PostgreSQL 写入/更新
    → 生成 embedding
    → 向量数据库写入
    → 如有 PDF 全文 → 下载解析 → 分块 → 向量化 → 写入向量库
```

流程三：RAG 问答

```
用户提问
    → 判断问题范围（单篇 or 项目集合）
    → 向量检索相关片段（Top-K = 8~12）
    → 拼接 Prompt 模板（含片段引用标记）
    → LLM 生成回答
    → 缓存问答对（Redis）
    → 返回回答（含引用文献列表）
```

流程四：批量总结

```
用户发起批量总结请求
    → API 立即返回 task_id
    → Celery 异步任务：逐篇提取要点 → 聚合生成综述
    → LLM 生成对比性总结
    → 结果写入 PostgreSQL + Redis 缓存
    → 用户轮询或 WebSocket 推送完成通知
```

数据库 Schema 概要

PostgreSQL 表

```sql
-- 文献表
papers (
    id UUID PRIMARY KEY,
    title TEXT NOT NULL,
    authors JSONB,
    abstract TEXT,
    doi VARCHAR UNIQUE,
    source VARCHAR,           -- arxiv / semantic_scholar / pubmed
    source_id VARCHAR,        -- 外部平台 ID
    published_date DATE,
    pdf_url TEXT,
    citation_count INT DEFAULT 0,
    metadata JSONB,           -- 扩展字段
    created_at TIMESTAMP,
    updated_at TIMESTAMP
)

-- 用户表
users (
    id UUID PRIMARY KEY,
    username VARCHAR UNIQUE,
    email VARCHAR UNIQUE,
    password_hash VARCHAR,
    created_at TIMESTAMP
)

-- 研究项目表
projects (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    name VARCHAR,
    description TEXT,
    created_at TIMESTAMP
)

-- 项目-文献关联表
project_papers (
    project_id UUID REFERENCES projects(id),
    paper_id UUID REFERENCES papers(id),
    added_at TIMESTAMP,
    PRIMARY KEY (project_id, paper_id)
)

-- 总结任务表
summary_tasks (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    project_id UUID REFERENCES projects(id),
    paper_ids UUID[],
    status VARCHAR,           -- pending / processing / completed / failed
    result_text TEXT,
    created_at TIMESTAMP,
    completed_at TIMESTAMP
)
```

Redis 数据结构

Key 模式 类型 用途
search:{query_hash} String (JSON) 缓存搜索结果
session:{user_id}:{session_id} List 对话历史（RAG 多轮）
rate_limit:{user_id} String API 限流计数
task_status:{task_id} String Celery 任务状态缓存
paper_summary:{paper_id} String 单篇总结缓存

向量数据库集合

Collection 名称 维度 用途
paper_abstracts 1024 文献标题+摘要向量
paper_chunks 1024 全文分块向量（用于 RAG）

API 接口概要

```
POST   /api/auth/register          用户注册
POST   /api/auth/login             用户登录

GET    /api/search                 语义搜索文献
POST   /api/search/rewrite         查询改写（调试用）

POST   /api/papers/import          手动导入文献（从外部源）
GET    /api/papers/{id}            获取文献详情
GET    /api/papers/{id}/summary    获取单篇总结

POST   /api/projects               创建研究项目
GET    /api/projects               获取用户项目列表
POST   /api/projects/{id}/papers   添加文献到项目
POST   /api/projects/{id}/summary  批量总结项目文献

POST   /api/qa                     单篇/项目 RAG 问答
GET    /api/tasks/{task_id}        查询异步任务状态
WS     /ws/tasks/{task_id}         WebSocket 任务完成推送
```

非功能性需求

维度 要求
性能 搜索接口 P95 延迟 < 2s（含缓存命中）；未命中 < 5s
并发 支持 50+ 并发用户同时搜索
可扩展 向量数据库与 LLM 服务均支持水平扩展
容错 外部数据源调用失败时降级返回已有数据
缓存策略 搜索结果 TTL 10min；单篇总结 TTL 24h
限流 每用户 20 req/min（Redis 计数器实现）

项目结构参考

```
litsage/
├── app/
│   ├── main.py                # FastAPI 入口
│   ├── config.py              # 配置管理（Pydantic Settings）
│   ├── api/
│   │   ├── routes/
│   │   │   ├── auth.py
│   │   │   ├── search.py
│   │   │   ├── papers.py
│   │   │   ├── projects.py
│   │   │   ├── qa.py
│   │   │   └── tasks.py
│   │   └── dependencies.py    # 依赖注入
│   ├── core/
│   │   ├── security.py        # JWT
│   │   ├── redis_client.py
│   │   └── celery_app.py
│   ├── models/
│   │   ├── db.py              # SQLAlchemy Base
│   │   └── schemas.py         # Pydantic 模型
│   ├── services/
│   │   ├── search_service.py
│   │   ├── rag_service.py
│   │   ├── summary_service.py
│   │   ├── embedding_service.py
│   │   ├── vector_store.py
│   │   └── paper_importer.py
│   ├── llm/
│   │   ├── llm_client.py      # LLM 调用封装
│   │   ├── prompts.py         # Prompt 模板管理
│   │   └── reranker.py        # 重排序模型
│   └── tasks/
│       ├── celery_tasks.py    # 异步任务定义
│       └── workers.py
├── migrations/                 # Alembic 数据库迁移
├── tests/
├── docker-compose.yml          # PostgreSQL + Redis + Milvus
├── .env.example
└── requirements.txt
```


