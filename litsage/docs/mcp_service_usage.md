# LitSage MCP 服务使用说明

记录日期：2026-09-06

## 目标

本次封装保留原 FastAPI 后端和 Streamlit 前端，同时新增 MCP Server。外部 Agent 可以通过 MCP 调用 LitSage 的文献检索、文献入库、项目管理、知识库问答、阶段性总结、资料上传和删除能力。

需要调用大模型的 MCP 工具会强制传入 `llm_config`，因此模型 API Key、文本模型、视觉模型都由外部调用方提供，避免消耗服务端 `.env` 中配置的 token。

## 启动方式

先安装依赖：

```bash
pip install -r requirements.txt
```

如果本地已经装过 `mcp 2.x`，需要降级到 v1，因为当前 MCP Server 使用的是 v1 的 `FastMCP` API：

```bash
pip install --upgrade --force-reinstall "mcp[cli]>=1.27,<2"
```

如果数据库迁移还没执行，先运行：

```bash
alembic upgrade head
```

启动 MCP Server：

```bash
python -m app.mcp.server
```

也可以使用脚本：

```bash
python scripts/run_mcp_server.py
```

FastAPI 和 Streamlit 前端不受 MCP 影响，仍然可以按原方式启动调试。

## 外部 IP 调用测试

默认启动方式是 `stdio`，适合被本机 MCP 客户端拉起。如果要让其他机器通过 IP 访问，需要使用 SSE 网络传输。

在服务端机器执行：

```powershell
$env:MCP_TRANSPORT="sse"
$env:MCP_HOST="0.0.0.0"
$env:MCP_PORT="9000"
python -m app.mcp.server
```

也可以直接运行：

```bash
python scripts/run_mcp_sse_server.py --host 0.0.0.0 --port 9010
```

外部机器访问的地址是：

```text
http://服务端IP:9010/sse
```

如果 Windows 防火墙拦截了端口，需要放行对应端口，例如 `9010`。生产环境不建议直接裸露内网服务，应该放到反向代理和鉴权之后。

外部机器可以用测试脚本列出工具：

```bash
python scripts/test_mcp_remote_client.py --url http://服务端IP:9010/sse
```

调用不需要大模型的工具，例如查看项目：

```bash
python scripts/test_mcp_remote_client.py --url http://服务端IP:9010/sse --tool list_projects --arguments-json "{\"user_id\":\"你的用户UUID\"}"
```

调用需要大模型的工具时，必须传调用方自己的 `llm_config`：

```bash
python scripts/test_mcp_remote_client.py --url http://服务端IP:9010/sse --tool ask_project_knowledge_base --arguments-json "{\"user_id\":\"你的用户UUID\",\"project_id\":\"项目UUID\",\"question\":\"这个项目有哪些研究方法？\",\"llm_config\":{\"provider\":\"deepseek\",\"api_key\":\"调用方自己的key\",\"base_url\":\"https://api.deepseek.com\",\"api_mode\":\"responses\",\"model\":\"deepseek-v4-flash\",\"vision_model\":\"deepseek-v4-flash-vision-exp\"}}"
```

## MCP 客户端配置示例

```json
{
  "mcpServers": {
    "litsage": {
      "command": "python",
      "args": ["-m", "app.mcp.server"],
      "cwd": "D:/AI/codex项目/1.文献搜索总结系统/litsage"
    }
  }
}
```

## llm_config 示例

OpenAI 兼容模型：

```json
{
  "provider": "openai_compatible",
  "api_key": "调用方自己的 API Key",
  "base_url": "https://api.openai.com/v1",
  "api_mode": "responses",
  "model": "gpt-4.1-mini",
  "vision_model": "gpt-4.1-mini",
  "temperature": 0.2,
  "timeout_seconds": 60,
  "max_output_tokens": 10000
}
```

DeepSeek 文本模型加视觉模型：

```json
{
  "provider": "deepseek",
  "api_key": "调用方自己的 DeepSeek API Key",
  "base_url": "https://api.deepseek.com",
  "api_mode": "responses",
  "model": "deepseek-v4-flash",
  "vision_model": "deepseek-v4-flash-vision-exp",
  "temperature": 0.2,
  "timeout_seconds": 60,
  "max_output_tokens": 10000
}
```

本地 Ollama：

```json
{
  "provider": "ollama",
  "model": "local-model-name",
  "ollama_base_url": "http://localhost:11434",
  "ollama_model": "local-model-name"
}
```

## 已封装工具

- `list_projects`：查看用户项目。
- `create_project`：创建研究项目。
- `list_project_papers`：查看项目已收录文献。
- `list_project_qas`：查看项目历史问答。
- `bind_papers_to_project`：把已有文献绑定到项目。
- `remove_project_papers`：从项目移除文献绑定，不删除文献库原文献。
- `delete_project_qas`：删除项目问答记录。
- `search_literature`：检索外部数据库文献，默认优先 PubMed。
- `import_literature_candidates`：导入候选文献，可选获取全文并绑定项目。
- `search_my_library`：检索用户已有文献库。
- `ask_project_knowledge_base`：基于项目知识库问答。
- `summarize_project_stage`：根据用户阶段性问题生成项目总结。
- `create_manual_material`：创建手动资料记录。
- `upload_user_material`：上传 PDF、DOCX、Markdown 资料，PDF 多模态解析使用调用方视觉模型。
- `delete_paper`：删除文献，需要 `confirm=true`。

## 当前边界

第一版 MCP 仍复用当前服务端数据库、Milvus 和 embedding 配置。外部调用方负责提供 LLM 配置；服务端负责保存文献、切片、向量和项目问答历史。

删除类工具已经加入显式确认参数，但 MCP 侧还没有更复杂的租户级 token 鉴权。对外部署前建议再增加 MCP 客户端身份映射、访问令牌和审计日志。

