# LitSage Streamlit Frontend

当前项目原本只有 FastAPI 后端和 `/docs` 调试界面，没有独立前端页面。

本目录已新增 Streamlit 前端：

```text
frontend/streamlit_app.py
```

## 启动方式

先启动 FastAPI 后端：

```bash
cd D:\AI\codex项目\1.文献搜索总结系统\litsage
uvicorn app.main:app --reload
```

再打开另一个终端启动前端：

```bash
cd D:\AI\codex项目\1.文献搜索总结系统\litsage
streamlit run frontend/streamlit_app.py
```

如果当前环境没有 Streamlit，请先安装依赖：

```bash
pip install -r requirements.txt
```

## 页面能力

- 注册与登录
- 保存 JWT Token 并调用需要认证的接口
- 后端健康检查
- 文献搜索与查询改写
- 文献导入任务创建
- 研究项目创建、列表刷新、批量总结
- RAG 问答
- 文献详情与总结查询
- 异步任务状态查询

