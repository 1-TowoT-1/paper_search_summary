# LitSage 1.0：科研文献智能检索与项目知识库系统

## 项目概述

项目名称：LitSage

项目定位：面向医学科研人员的文献检索、私有资料管理、项目知识库问答与阶段性总结平台。

核心价值：将公开文献、用户私有资料、研究问答和阶段总结统一沉淀到研究项目中，使科研人员不仅能够“找到文献”，还能够围绕课题持续积累证据、追踪问题并整理研究思路。

当前版本定位：

> LitSage 1.0 是一个具备 Agent 化扩展基础的科研文献知识库与 RAG 分析系统。

系统已经实现文献检索、全文获取、资料解析、向量化、项目管理、知识库问答、阶段总结和 MCP 工具接口。当前尚未实现成熟 Agent 所需的自主任务规划、持久化运行状态、多工具自动编排和自我校验闭环，因此更准确的描述是 Agent-ready，而不是完全自主的科研 Agent。

## 适用场景

- 从 PubMed 检索医学文献，筛选后直接导入个人文献库或研究项目。
- 上传 PDF、Word、Markdown、内部报告和未发表资料，建立私有科研知识库。
- 围绕特定研究项目进行文献问答，并保留回答引用和历史记录。
- 根据用户提出的阶段性问题，总结项目已有证据、研究方法和当前进展。
- 将文献检索、资料入库和知识库问答能力通过 MCP 提供给外部 Agent。

## 技术栈

| 层级 | 技术选型 | 用途说明 | 当前状态 |
| --- | --- | --- | --- |
| 后端框架 | FastAPI | REST API、认证、业务服务入口 | 已实现 |
| 前端界面 | Streamlit | 本地使用、功能测试与项目演示 | 已实现 |
| 数据访问 | SQLAlchemy + Pydantic | ORM、数据校验和接口模型 | 已实现 |
| 数据库迁移 | Alembic | PostgreSQL 表结构版本管理 | 已实现 |
| 关系数据库 | PostgreSQL | 用户、项目、文献、文件、切片、问答和任务 | 已实现 |
| 向量数据库 | Milvus | 摘要和全文切片的向量存储与召回 | 已实现 |
| 缓存与任务基础 | Redis + Celery | 缓存与异步任务架构预留 | 基础接入 |
| 大模型 | OpenAI-compatible / DeepSeek / Ollama | 查询改写、RAG 回答、总结及多模态解析 | 已实现 |
| Embedding | 本地 BGE / Ollama / 兼容接口 | 生成 1024 维摘要和全文向量 | 已实现 |
| 文档解析 | PyMuPDF + python-docx | PDF、DOCX 和 Markdown 文本提取 | 已实现 |
| OCR | Tesseract OCR | 扫描型 PDF 文本识别兜底 | 可配置 |
| 多模态解析 | 独立视觉模型配置 | PDF 页面和复杂版式识别 | 可配置 |
| 工具协议 | MCP Python SDK | 向外部 Agent 暴露系统能力 | 已实现 |
| 外部数据源 | PubMed / PMC、arXiv、Semantic Scholar | 文献检索、元数据和公开全文获取 | 已实现/可扩展 |

## 系统架构

```text
Streamlit 前端            外部 MCP Client
      │                         │
      ├──── REST API ───────────┤ MCP Tools
      │                         │
      ▼                         ▼
                FastAPI / Service Layer
      ┌──────────────┬───────────────┬──────────────┐
      │ 文献检索导入 │ 用户资料解析  │ RAG/阶段总结 │
      └──────┬───────┴───────┬───────┴──────┬───────┘
             │               │              │
       PubMed / PMC      LLM / OCR      Embedding
             │               │              │
             └───────────────┼──────────────┘
                             │
                   PostgreSQL + Milvus
```

PostgreSQL 负责业务事实、权限和可审计文本，Milvus 负责向量召回。两者通过文献 ID 和切片 ID 关联，避免只在向量库中保存不可追踪的内容。

## 核心功能模块

### 1. 用户与认证模块

- 用户注册、登录和 JWT 身份认证。
- 获取当前用户信息。
- 邮箱验证码发送与邮箱修改。
- 登录密码修改。
- 所有项目、私有资料和问答操作均按用户范围进行约束。

### 2. 数据库文献检索与导入模块

- 支持从外部文献数据源检索候选文献，医学场景默认优先 PubMed。
- 保存标题、作者、摘要、DOI、PMID、PMCID、发表时间、来源和全文地址等元数据。
- 支持“先检索预览、再勾选导入”，避免无关候选文献直接写入数据库。
- 支持中文检索问题通过大模型改写为适合 PubMed 的英文检索词。
- 候选文献可以在导入时直接绑定到已有研究项目。
- DOI 在前端展示为可点击链接，便于用户访问文献原始页面。
- 基于 DOI、外部来源 ID 等标识执行重复检测。
- 已存在文献但缺少全文时，可重新尝试全文解析，而不是简单跳过。

### 3. PubMed / PMC 全文获取模块

PubMed 记录不等于可直接下载的 PDF。系统对医学公开文献采用分层获取策略：

1. 从 PubMed 元数据中识别 PMID、PMCID 和 DOI。
2. 存在 PMCID 时，优先调用 PMC 官方结构化全文接口。
3. 结构化全文不可用时，再解析并下载真实 PDF。
4. 检查响应内容是否确实为 PDF，拒绝把验证码或 JavaScript challenge 页面当成论文。
5. PDF 下载或解析失败时保留有效元数据，并记录失败状态供后续重试。

PMC 官方结构化全文能够减少 URL 跳转、防爬页面和出版商权限限制对入库流程的影响，也是当前 PubMed 全文导入的首选路径。

### 4. 用户自带资料入库模块

- 支持 PDF、DOCX 和 Markdown 文件。
- 支持一次选择并上传多份资料。
- 文件第一版保存在本地目录，并在数据库记录文件信息和 SHA-256。
- 资料可以绑定研究项目，也可以只保存到个人资料库。
- 用户资料和未发表资料默认设置为 `private`。
- 用户可以手动输入 title 和 abstract，覆盖自动识别结果。
- 相同用户重复上传同一文件时返回已有资料，避免重复解析和向量化。
- 没有可用摘要或 Embedding 失败时不完成知识库入库，防止低质量内容进入后续问答。

### 5. 多层文档解析模块

系统根据文献来源和文件质量组合使用以下策略：

1. PMC 官方结构化全文。
2. PDF 原生文本提取。
3. PDF 页面渲染为 PNG 后调用视觉模型。
4. Tesseract OCR 兜底。
5. 用户手动提供标题和摘要。

解析结果会过滤 `[Unsupported Image]`、`[无法识别]` 和模型道歉文本等无效内容，避免错误文本被写入 `paper_chunks` 并污染 RAG 检索。

### 6. 向量化与知识库模块

- 对标题和摘要生成 Embedding，写入 Milvus `paper_abstracts`。
- 对全文进行分块和重叠处理，写入 PostgreSQL `paper_chunks`。
- 对每个有效全文切片生成 Embedding，写入 Milvus `paper_chunks`。
- 默认向量维度为 1024，入库前检查实际输出维度。
- PostgreSQL 保存切片原文、顺序、页码、类型和来源元数据，支持审计及重建向量库。
- Embedding 或向量数据库失败时记录明确错误，不把未完成资料标记为完整入库。

### 7. 研究项目管理模块

- 创建和查看研究项目。
- 创建项目时或创建后批量绑定已有文献。
- 查看项目已经收录的全部文献。
- 单篇或批量解除项目与文献的绑定。
- 从项目移除文献只删除关联关系，不默认删除个人文献库中的原始资料。
- 查看项目历史提问、AI 回答和引用来源。
- 单条或批量删除无意义问答，避免干扰后续项目总结。

### 8. 知识库问答模块

- 用户从下拉框选择自己的研究项目后直接提问。
- 系统只在该项目有权访问的文献范围内召回相关片段。
- 根据向量召回结果回查 PostgreSQL，补充文献标题、正文、页码和切片 ID。
- 将带来源标记的上下文交给大模型生成可读文本回答。
- 回答包含引用信息，而不是只向用户展示 JSON。
- 项目问答完成后保存问题、回答、引用和总结上下文状态。

### 9. 阶段性总结模块

- 阶段总结位于研究问答模块下，用户需要输入本阶段希望总结的问题。
- 系统结合项目文献、有效历史问答和当前问题生成阶段性总结。
- 大模型判断普通问答是否值得进入总结上下文，并保存判断结果和原因。
- 用户可以人工删除无意义问答，对项目知识轨迹进行二次治理。
- 当前实现面向“围绕课题持续追问并阶段性梳理”，而不是无条件拼接所有历史内容。

### 10. 文献管理模块

- 检索个人文献库。
- 查看文献详情、来源、可见性、解析状态和摘要。
- 将已有文献批量绑定到项目。
- 支持删除个人文献库中的资料。
- 删除时同步处理项目关联、全文切片和向量数据，避免残留孤立记录。

### 11. Streamlit 前端模块

当前前端用于本地测试、面试演示和基础用户操作，包含：

- 注册、登录和账号设置。
- 研究项目管理。
- 在线文献检索、候选筛选和导入。
- 私有资料批量上传。
- 个人文献库查询、项目绑定和删除。
- 项目知识库问答。
- 阶段性总结。
- 项目文献和历史问答管理。

登录成功后不再显示左侧登录表单，减少重复操作。

### 12. MCP 服务模块

项目保留 FastAPI 和 Streamlit，同时将核心服务封装为 MCP Server。当前提供的 MCP 工具包括：

- `list_projects`
- `create_project`
- `list_project_papers`
- `list_project_qas`
- `bind_papers_to_project`
- `remove_project_papers`
- `delete_project_qas`
- `search_literature`
- `import_literature_candidates`
- `search_my_library`
- `ask_project_knowledge_base`
- `summarize_project_stage`
- `create_manual_material`
- `upload_user_material`
- `delete_paper`

需要大模型的 MCP 工具强制要求调用方传入 `llm_config`。文本模型、视觉模型和 API Key 由外部用户提供，避免外部调用消耗服务端默认模型额度。

MCP 默认使用 stdio，仅供本机客户端拉起；也支持 SSE 和 Streamable HTTP。网络模式在加入 token 鉴权、用户身份映射、限流和审计之前，不建议直接暴露到公网。

## 关键工作流程

### 流程一：在线检索与选择性导入

```text
用户输入检索词
    → 可选 LLM 中英文查询改写
    → PubMed 优先检索候选文献
    → 返回候选列表，不写数据库
    → 用户勾选目标文献和目标项目
    → DOI / PMID / 来源 ID 去重
    → 写入 PostgreSQL 元数据
    → 摘要 Embedding 写入 Milvus
    → 可选 PMC 结构化全文或 PDF 全文处理
    → 全文切片写入 PostgreSQL 与 Milvus
    → 绑定到研究项目
```

### 流程二：用户私有资料导入

```text
用户批量选择 PDF / DOCX / Markdown
    → 文件类型、大小和 SHA-256 检查
    → 保存本地文件
    → 原生文本 / 多模态 / OCR 解析
    → 用户 title / abstract 覆盖
    → 内容有效性检查
    → 摘要与全文切片 Embedding
    → 写入 PostgreSQL 与 Milvus
    → 可选绑定项目，否则进入个人资料库
```

### 流程三：项目知识库问答

```text
用户选择项目并提问
    → 校验项目归属和文献范围
    → 问题 Embedding
    → Milvus 召回相关全文片段
    → PostgreSQL 回填正文、标题、页码和权限
    → 过滤无效及越权片段
    → 构建带引用上下文
    → LLM 生成文本回答
    → 保存有效问答和引用记录
```

### 流程四：项目阶段性总结

```text
用户选择项目并输入阶段问题
    → 读取项目文献证据
    → 读取允许进入总结上下文的历史问答
    → 组织项目阶段上下文
    → LLM 生成阶段性总结
    → 返回研究进展、方法、证据和后续思路
```

### 流程五：外部 Agent 调用

```text
外部 MCP Client
    → 连接 stdio / SSE / Streamable HTTP
    → 调用 LitSage MCP 工具
    → 传入用户 ID、业务参数和调用方 llm_config
    → 复用现有 Service、PostgreSQL 与 Milvus
    → 返回结构化工具结果
```

## 数据库 Schema 概要

### PostgreSQL 核心表

```sql
papers (
    id UUID PRIMARY KEY,
    title TEXT NOT NULL,
    authors JSONB,
    abstract TEXT,
    doi VARCHAR UNIQUE,
    source VARCHAR,
    source_id VARCHAR,
    published_date DATE,
    pdf_url TEXT,
    metadata JSONB,
    source_type VARCHAR,
    publication_status VARCHAR,
    visibility VARCHAR,
    owner_user_id UUID,
    original_filename TEXT,
    file_path TEXT,
    file_sha256 VARCHAR,
    ingestion_status VARCHAR,
    analysis_status VARCHAR,
    text_extraction_method VARCHAR
)

users (
    id UUID PRIMARY KEY,
    username VARCHAR UNIQUE,
    email VARCHAR UNIQUE,
    password_hash VARCHAR,
    created_at TIMESTAMP
)

projects (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    name VARCHAR,
    description TEXT,
    created_at TIMESTAMP
)

project_papers (
    project_id UUID REFERENCES projects(id),
    paper_id UUID REFERENCES papers(id),
    added_at TIMESTAMP,
    PRIMARY KEY (project_id, paper_id)
)

project_qas (
    id UUID PRIMARY KEY,
    project_id UUID REFERENCES projects(id),
    user_id UUID REFERENCES users(id),
    question TEXT,
    answer TEXT,
    citations JSONB,
    include_in_summary_context BOOLEAN,
    summary_context_reason TEXT,
    created_at TIMESTAMP
)

paper_files (
    id UUID PRIMARY KEY,
    paper_id UUID REFERENCES papers(id),
    user_id UUID REFERENCES users(id),
    original_filename TEXT,
    stored_path TEXT,
    mime_type VARCHAR,
    file_size_bytes BIGINT,
    sha256 VARCHAR,
    upload_status VARCHAR
)

paper_chunks (
    id UUID PRIMARY KEY,
    paper_id UUID REFERENCES papers(id),
    chunk_index INTEGER,
    text TEXT,
    page_start INTEGER,
    page_end INTEGER,
    chunk_type VARCHAR,
    metadata JSONB
)

summary_tasks (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    project_id UUID,
    paper_ids UUID[],
    status VARCHAR,
    result_text TEXT,
    created_at TIMESTAMP,
    completed_at TIMESTAMP
)
```

### Milvus Collections

| Collection | 默认维度 | 用途 |
| --- | ---: | --- |
| `paper_abstracts` | 1024 | 标题与摘要语义检索 |
| `paper_chunks` | 1024 | 全文切片检索与项目 RAG |

## API 接口概要

### 用户认证

```text
POST   /api/auth/register                  注册用户
POST   /api/auth/login                     用户登录
GET    /api/auth/me                        获取当前用户
POST   /api/auth/email/verification-code   发送邮箱验证码
PATCH  /api/auth/me/email                  修改邮箱
PATCH  /api/auth/me/password               修改密码
```

### 文献检索与管理

```text
GET    /api/search                         检索个人库及外部文献
POST   /api/search/rewrite                 查询改写
POST   /api/papers/import                  直接导入外部文献
POST   /api/papers/import/preview          获取候选文献
POST   /api/papers/import/selected         导入选中的候选文献
POST   /api/papers/upload                  上传单份用户资料
POST   /api/papers/upload/batch            批量上传用户资料
POST   /api/papers/manual                  手动创建资料
GET    /api/papers                         查询个人文献库
GET    /api/papers/{paper_id}              查看文献详情
GET    /api/papers/{paper_id}/summary      获取文献总结
DELETE /api/papers/{paper_id}              删除文献
```

### 研究项目

```text
POST   /api/projects                                   创建项目
GET    /api/projects                                   查看项目列表
GET    /api/projects/{project_id}/papers               查看项目文献
POST   /api/projects/{project_id}/papers               绑定单篇文献
POST   /api/projects/{project_id}/papers/batch         批量绑定文献
DELETE /api/projects/{project_id}/papers/{paper_id}    移除单篇文献
POST   /api/projects/{project_id}/papers/delete        批量移除文献
GET    /api/projects/{project_id}/qas                  查看历史问答
DELETE /api/projects/{project_id}/qas/{qa_id}          删除单条问答
POST   /api/projects/{project_id}/qas/delete           批量删除问答
POST   /api/projects/{project_id}/summary              生成阶段性总结
```

### 问答与任务

```text
POST   /api/qa                             项目知识库问答
GET    /api/tasks/{task_id}                查询任务状态
GET    /health                             后端健康检查
```

## 项目结构

```text
文献搜索总结系统/
├── Readme.md                         # 项目设计模板
└── litsage/
    ├── app/
    │   ├── main.py                   # FastAPI 入口
    │   ├── config.py                 # Pydantic Settings 配置
    │   ├── api/
    │   │   ├── dependencies.py       # 数据库和认证依赖
    │   │   └── routes/
    │   │       ├── auth.py           # 注册、登录与账号设置
    │   │       ├── search.py         # 文献搜索与查询改写
    │   │       ├── papers.py         # 导入、上传、查询与删除
    │   │       ├── projects.py       # 项目、绑定、问答与总结
    │   │       ├── qa.py             # RAG 问答入口
    │   │       └── tasks.py          # 任务状态
    │   ├── core/
    │   │   ├── security.py           # JWT 与密码安全
    │   │   ├── redis_client.py       # Redis 客户端
    │   │   └── celery_app.py         # Celery 基础配置
    │   ├── llm/
    │   │   ├── llm_client.py         # 文本与视觉模型统一客户端
    │   │   ├── prompts.py            # Prompt 模板
    │   │   └── reranker.py           # 重排序接口
    │   ├── mcp/
    │   │   ├── runtime.py            # 调用方 LLM 运行时配置
    │   │   └── server.py             # MCP Server 与工具
    │   ├── models/
    │   │   ├── db.py                 # SQLAlchemy 数据模型
    │   │   └── schemas.py            # Pydantic 请求响应模型
    │   ├── services/
    │   │   ├── paper_importer.py     # 外部文献检索与导入
    │   │   ├── pdf_resolver.py       # 全文发现、下载与 PMC 解析
    │   │   ├── user_material_importer.py # 私有资料解析与入库
    │   │   ├── embedding_service.py  # Embedding 客户端
    │   │   ├── vector_store.py       # Milvus 操作
    │   │   ├── rag_service.py        # 项目知识库问答
    │   │   ├── summary_service.py    # 文献与项目总结
    │   │   ├── paper_catalog_service.py # 个人文献库查询
    │   │   └── paper_cleanup_service.py # 文献清理
    │   └── tasks/
    │       └── celery_tasks.py       # 异步任务定义
    ├── frontend/
    │   └── streamlit_app.py          # Streamlit 前端
    ├── migrations/                   # Alembic 迁移
    ├── scripts/                      # 初始化、诊断和 MCP 脚本
    ├── tests/                        # 自动化测试
    ├── docs/                         # 设计文档与开发日志
    ├── docker-compose.yml            # PostgreSQL、Redis、Milvus
    ├── alembic.ini
    └── requirements.txt
```

## 安装与启动

以下命令均在 `litsage` 目录下执行。

### 1. 创建环境并安装依赖

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. 启动基础服务

```powershell
docker compose up -d
```

该命令启动 PostgreSQL、Redis、etcd、MinIO 和 Milvus。大模型及本地 Embedding 服务需要根据实际配置单独启动或接入。

### 3. 配置环境变量

在 `litsage/.env` 中配置运行参数。

```dotenv
APP_NAME=LitSage
ENVIRONMENT=dev
AUTO_CREATE_TABLES=true

DATABASE_URL=postgresql+psycopg://litsage:your_password@localhost:5432/litsage
REDIS_URL=redis://localhost:6379/0
MILVUS_URI=http://localhost:19530

EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=your_embedding_model
EMBEDDING_DIM=1024
LOCAL_OLLAMA_BASE_URL=http://localhost:11434

LLM_PROVIDER=openai
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=https://your-provider.example/v1
OPENAI_API_MODE=responses
OPENAI_MODEL=your_text_model
DEEPSEEK_VISION_MODEL=your_vision_model

PDF_MULTIMODAL_ENABLED=true
PDF_OCR_ENABLED=false
PDF_OCR_LANGUAGES=eng+chi_sim

PUBMED_EMAIL=your_email@example.com
PUBMED_API_KEY=
SEMANTIC_SCHOLAR_API_KEY=
```


### 4. 执行数据库迁移

推荐使用 Alembic，而不是长期依赖自动建表：

```powershell
alembic upgrade head
```

开发环境也可以临时使用：

```dotenv
ENVIRONMENT=dev
AUTO_CREATE_TABLES=true
```

自动建表只能创建缺失表，不能可靠替代已有表的字段迁移。

### 5. 启动 FastAPI 后端

```powershell
uvicorn app.main:app --reload
```

访问地址：

```text
API 文档：http://127.0.0.1:8000/docs
健康检查：http://127.0.0.1:8000/health
```

### 6. 启动 Streamlit 前端

打开另一个终端，在 `litsage` 目录执行：

```powershell
streamlit run frontend/streamlit_app.py
```

默认访问地址：

```text
http://127.0.0.1:8501
```

### 7. 启动 MCP Server

本机 stdio 模式：

```powershell
python -m app.mcp.server
```

SSE 测试模式：

```powershell
python scripts/run_mcp_sse_server.py --host 127.0.0.1 --port 9010
```

测试 MCP 连接：

```powershell
python scripts/test_mcp_remote_client.py --url http://127.0.0.1:9010/sse
```

## 调试与测试

### 自动化测试

```powershell
pytest
```

### 数据库结构检查

```powershell
python scripts/check_db_schema.py
```

### 文献导入依赖检查

```powershell
python scripts/check_importer_stack.py
```

### PDF 全链路诊断

```powershell
python scripts/debug_pdf_ingestion_pipeline.py --pdf-url "PDF_URL"
```

也可以按文献 ID、本地文件或 PMCID 调试：

```powershell
python scripts/debug_pdf_ingestion_pipeline.py --paper-id "PAPER_UUID"
python scripts/debug_pdf_ingestion_pipeline.py --file "D:\papers\sample.pdf"
python scripts/debug_pdf_ingestion_pipeline.py --pmc-id "PMC1234567"
```

该脚本用于分别检查全文发现、下载响应、PDF 真实性、原生文本、页面渲染、多模态解析、切片和 Embedding，不写入 PostgreSQL 或 Milvus。

## 非功能性设计

| 维度 | 当前策略 |
| --- | --- |
| 数据隔离 | 项目和私有资料按用户 ID 限制访问 |
| 可追溯性 | PostgreSQL 保存正文切片、页码、文献来源和问答引用 |
| 去重 | 外部文献使用 DOI/来源 ID，用户文件使用 SHA-256 |
| 容错 | 全文获取采用结构化全文、原生 PDF、视觉模型、OCR 分层降级 |
| 配置安全 | API Key 使用环境变量；MCP LLM 工具要求调用方提供配置 |
| 可迁移性 | 使用 Alembic 管理数据库结构 |
| 可测试性 | 提供自动化测试及 PDF 入库分阶段诊断脚本 |
| 可扩展性 | API、Service、存储和 MCP 适配层分离 |

当前版本尚未通过正式并发压测，因此不承诺固定的 P95 延迟和并发用户数量。

## 当前限制

- 复杂出版商站点可能存在登录、验证码、JavaScript challenge 或版权限制，系统无法保证自动获得所有论文全文。
- 多模态模型的图片输入格式、模型能力和服务商实现存在差异，解析结果仍需质量检查。
- 当前 RAG 以向量召回为主，尚未形成完整的混合检索、Cross-Encoder 重排序和答案证据自检链路。
- 文献导入和全文向量化仍以同步流程为主，长任务需要继续迁移到 Celery Worker。
- Streamlit 适合开发和演示，尚不是正式生产前端。
- MCP 网络模式尚缺少完整的 token 到用户身份映射、细粒度授权、限流和审计。
- 用户上传文件当前保存在本地，生产环境需要迁移到对象存储并增加病毒扫描和生命周期管理。

## 后续开发计划

### 1. Agent Run 与任务状态

- 新增 `agent_runs`、`agent_steps` 和工具调用日志。
- 将研究目标拆解为检索、筛选、全文获取、分析和总结步骤。
- 支持步骤重试、失败恢复、暂停和继续。

### 2. LLM 调用治理

- 统一 retry、指数退避、超时和 fallback。
- 记录模型、耗时、Token 和费用。
- 建立文本模型与视觉模型路由。
- 增加结构化输出校验和错误分类。

### 3. RAG 质量提升

- 增加关键词与向量混合检索。
- 接入 Reranker。
- 建立检索召回、引用覆盖和事实一致性评测集。
- 增加答案生成后的证据校验。

### 4. 文献结构化理解

- 抽取研究背景、研究设计、样本量、方法、结果、结论和局限。
- 提取图表题注和表格结构。
- 识别疾病、药物、基因、数据集和评价指标。
- 为入库文献生成覆盖率与解析质量评分。

### 5. 工程与安全

- 文献导入迁移到 Celery 异步任务。
- 文件迁移到 MinIO 或其他对象存储。
- 增加 MCP token 鉴权、权限范围、限流和审计日志。
- 正式部署时使用反向代理、HTTPS 和受控 CORS。
- 将 Streamlit 逐步替换为 React、Vue 或 Next.js 正式前端。

## 项目核心优势

1. 以研究项目为中心组织文献、私有资料、问答和阶段总结，而不是一次性调用大模型。
2. 同时支持公开文献和未发表资料，能够覆盖真实科研工作中的内部知识资产。
3. 针对医学场景重点优化 PubMed、PMCID 和 PMC 官方结构化全文链路。
4. 通过 PostgreSQL 与 Milvus 分工保存事实数据和向量数据，使回答证据可追溯。
5. 同时提供 Streamlit、REST API 和 MCP 三种使用方式，可供人工操作或外部 Agent 复用。
6. 具备清晰的 Agent 化升级路径，能够继续扩展任务规划、工具编排和研究过程管理。

## 当前阶段结论

LitSage 1.0 已经完成科研资料从“获取、解析、入库、组织、检索、问答到阶段总结”的基础闭环，并将核心能力封装为可复用的 MCP 工具。

项目的真正价值不只是替用户调用大模型总结论文，而是为科研项目建立长期、私有、可管理并且能够追溯证据的知识底座。下一阶段的重点是补齐 Agent 状态管理、模型调用治理、RAG 质量评测和对外服务安全，使系统从可用的科研知识库逐步演进为能够持续跟进课题的科研 Agent。
