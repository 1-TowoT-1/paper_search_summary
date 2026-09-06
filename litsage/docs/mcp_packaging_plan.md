# LitSage MCP 封装方案记录

记录日期：2026-09-04

## 1. 是否适合封装成 MCP

适合。

LitSage 当前已经具备比较清晰的服务边界：文献检索、候选文献导入、用户资料上传、项目管理、知识库问答、阶段总结、文献删除等能力本质上都是“外部智能体可以调用的工具”。这些能力如果封装成 MCP Server，其他大模型客户端或 Agent 平台就可以把 LitSage 当作一个科研文献知识库工具来调用。

更适合 MCP 的原因包括：

1. 能力是工具型的，而不是单纯页面型的。
2. 输入输出可以结构化表达，例如 query、project_id、paper_id、files、limit。
3. 项目有自己的数据库、向量库和权限体系，MCP 可以作为统一访问层。
4. RAG 问答和项目总结适合被其他 Agent 编排调用。
5. 用户上传的私有资料、未发表资料、项目问答历史可以成为差异化能力。

## 2. 改动量评估

如果第一版 MCP 只封装现有后端能力，改动不算大，属于中等偏小。

原因是当前 FastAPI 后端已经提供了多数接口，MCP Server 可以作为一个新的适配层调用这些已有 service 或 HTTP API，不需要推翻现有架构。

预计改动范围：

1. 新增一个 MCP Server 入口模块。
2. 将现有核心服务包装成 MCP tools。
3. 增加 MCP 使用的认证方式。
4. 对部分返回结果做文本化和结构化整理。
5. 增加 MCP 专用配置和启动脚本。

不需要大改的部分：

1. PostgreSQL 表结构。
2. Milvus 向量库结构。
3. 已有 FastAPI 路由。
4. 文献导入、解析、问答、总结等核心 service。

后续如果希望 MCP 支持“直接上传文件给工具”，改动会更大一些，因为要处理 MCP 客户端文件传输、临时文件保存、权限校验和异步任务状态。

## 3. 推荐 MCP 工具设计

第一版建议不要一次封装所有功能，而是优先封装最能体现价值的工具。

### 3.1 文献检索工具

工具名建议：

`search_literature`

用途：

根据关键词检索 PubMed 优先的外部文献和本地文献库。

输入：

- `query`
- `source`
- `year_from`
- `year_to`
- `limit`

输出：

- 文献标题
- 作者
- 摘要
- DOI
- 来源
- 是否已在库中
- 候选导入标识

### 3.2 候选文献导入工具

工具名建议：

`import_literature_candidates`

用途：

把检索到的候选文献导入 LitSage 文献库，可选择是否尝试 PDF 全文解析。

输入：

- `papers`
- `include_pdf`
- `project_id`

输出：

- 导入状态
- 新增数量
- 重复数量
- PDF 解析数量
- 失败原因

### 3.3 项目文献问答工具

工具名建议：

`ask_project_knowledge_base`

用途：

基于某个研究项目中的文献和资料回答问题。

输入：

- `project_id`
- `question`

输出：

- 中文回答
- 引用来源
- 命中的文献片段
- 是否使用摘要兜底

### 3.4 项目阶段总结工具

工具名建议：

`summarize_research_project`

用途：

根据项目文献和历史问答生成阶段性总结。

输入：

- `project_id`

输出：

- 阶段总结 Markdown
- 文献数量
- 问答记录数量
- 主要研究方向
- 后续研究建议

### 3.5 我的文献库检索工具

工具名建议：

`search_my_library`

用途：

在用户已有文献库里检索文献，支持中文关键词自动扩展英文。

输入：

- `query`
- `title`
- `doi`
- `author`
- `source`
- `year_from`
- `year_to`
- `limit`

输出：

- 文献列表
- 文献 ID
- DOI 链接
- 摘要
- 来源

### 3.6 文献删除工具

工具名建议：

`delete_paper`

用途：

删除指定文献，并清理项目关联和向量库数据。

输入：

- `paper_id`

输出：

- 删除结果
- 项目关联清理数量
- 向量清理状态

删除类工具需要更严格的确认机制，不建议让自动 Agent 无确认调用。

## 4. MCP 架构建议

推荐采用“旁路适配层”方案。

也就是保留当前 FastAPI 项目不动，在项目中新增一个 MCP Server：

```text
litsage
  + app
    + api
    + services
    + models
  + mcp_server
    + server.py
    + tools.py
    + auth.py
    + schemas.py
```

MCP 工具调用时直接复用 `app/services` 中的服务，而不是绕一圈调用 FastAPI HTTP 接口。

优点：

1. 复用现有业务逻辑。
2. 避免重复维护两套核心代码。
3. MCP 与 FastAPI 可以独立启动。
4. 后续也可以把 MCP Server 单独部署。

## 5. 认证与权限设计

MCP 版本必须考虑权限问题，尤其是用户上传的 private 文献和未发表资料。

第一版建议：

1. MCP Server 启动时配置固定用户身份。
2. 每个 MCP 客户端绑定一个 LitSage user_id 或 token。
3. 工具内部仍然走现有用户权限过滤。
4. 删除、批量导入、项目绑定等写操作需要显式确认。

不建议第一版直接开放无认证 MCP，否则私有资料风险很高。

## 6. 文件上传能力设计

第一版 MCP 可以暂时不做文件上传，只封装文本型工具。

原因：

1. 不同 MCP 客户端对文件传输支持不完全一致。
2. PDF 上传涉及本地临时文件、大小限制、清理策略和任务状态。
3. 多模态解析耗时较长，更适合后续接入异步任务。

第二版再增加：

`upload_user_material`

支持 PDF、DOCX、Markdown 文件入库。

## 7. 阶段路线

### 第一阶段：只读 MCP

目标：

让其他 Agent 可以搜索文献库、查看项目、对项目提问、生成项目总结。

工具：

- `search_my_library`
- `search_literature`
- `ask_project_knowledge_base`
- `summarize_research_project`
- `list_projects`

特点：

风险低，适合先跑通。

### 第二阶段：可写 MCP

目标：

允许外部 Agent 导入文献、绑定项目、删除文献。

工具：

- `import_literature_candidates`
- `bind_papers_to_project`
- `delete_paper`

特点：

需要确认机制和更严格权限控制。

### 第三阶段：文件型 MCP

目标：

允许外部 Agent 上传 PDF、DOCX、Markdown，并触发多模态解析。

工具：

- `upload_user_material`
- `check_ingestion_status`
- `retry_paper_parsing`

特点：

需要异步任务、文件生命周期管理和更强错误恢复。

## 8. 对原项目需要改动的模块

建议新增：

- `mcp_server/server.py`
- `mcp_server/tools.py`
- `mcp_server/auth.py`
- `mcp_server/schemas.py`
- `scripts/run_mcp_server.py`

建议调整：

- `app/services/rag_service.py`：增加更适合 MCP 返回的结构化引用。
- `app/services/paper_catalog_service.py`：增强检索结果摘要格式。
- `app/services/paper_importer.py`：为 MCP 暴露更清晰的导入状态。
- `app/services/user_material_importer.py`：后续支持文件型 MCP 时调整。
- `app/config.py`：新增 MCP 启动和认证配置。

## 9. 风险与注意事项

1. 私有文献权限必须严格控制。
2. 删除类工具必须有确认机制。
3. 多模态 PDF 解析耗时较长，不适合阻塞式工具长期等待。
4. 外部文献检索依赖 PubMed、DOI 页面、出版商页面，失败率不可完全避免。
5. MCP 返回结果要面向 Agent 使用，既要结构化，也要保留可读文本。
6. 不建议把 Streamlit 前端逻辑封装成 MCP，应封装后端 service 能力。

## 10. 结论

LitSage 适合封装成 MCP。

第一版改动不大，可以通过新增 MCP 适配层复用现有 FastAPI 后端服务。最推荐先做“只读 MCP”，让其他 Agent 调用项目问答、文献库检索和项目总结；等稳定后再开放导入、删除、上传等写操作。

长期看，MCP 会让 LitSage 从一个单独的文献系统，变成可被其他科研 Agent 调用的“文献知识库能力底座”。这会增强项目价值，尤其适合客户已有内部资料、未发表文献和项目沉淀问答的场景。
