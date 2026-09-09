# 面试演示内网穿透记录

记录日期：2026-09-08

## 当前演示方式

本次使用 Cloudflare Tunnel 将本机 Streamlit 前端临时暴露给外部访问。

只转发前端端口：

```text
http://127.0.0.1:8501
```

后端 FastAPI 仍保持本机访问：

```text
http://127.0.0.1:8000
```

Streamlit 前端在服务端本机调用 FastAPI，因此外部用户只需要访问前端公网链接，不需要直接访问后端 `/docs` 或 MCP SSE 地址。

## 本次已安装工具

通过 winget 安装：

```bash
winget install --id Cloudflare.cloudflared -e --accept-package-agreements --accept-source-agreements
```

安装路径：

```text
C:\Program Files (x86)\cloudflared\cloudflared.exe
```

如果当前终端找不到 `cloudflared` 命令，可以直接使用完整路径启动。

## 启动顺序

先启动 FastAPI 后端：

```bash
uvicorn app.main:app --reload
```

再启动 Streamlit 前端：

```bash
streamlit run frontend/streamlit_app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true
```

最后启动 Cloudflare Tunnel：

```powershell
& 'C:\Program Files (x86)\cloudflared\cloudflared.exe' tunnel --url http://127.0.0.1:8501
```

控制台会输出一个临时公网地址，例如：

```text
https://xxxx.trycloudflare.com
```

这个地址就是面试时可以给外部访问的前端链接。

## 验证方式

本机验证前端：

```bash
curl --noproxy "*" -I http://127.0.0.1:8501
```

验证公网链接：

```bash
curl --noproxy "*" -I https://xxxx.trycloudflare.com
```

如果返回 `200 OK`，说明外部链接已经打通。

## 注意事项

- 面试演示结束后关闭 Cloudflare Tunnel 终端，公网链接会失效。
- 不要把 FastAPI `/docs` 和 MCP SSE 服务一起暴露出去。
- 不要上传真实敏感资料。
- 建议提前准备测试账号和测试项目。
- 演示期间避免让外部用户随意批量上传大文件。
- 如果接口访问异常，先确认后端 `http://127.0.0.1:8000/health` 是否正常。

## 本次问题记录

第一次直接运行 `cloudflared` 提示命令不存在，原因是安装后当前终端 PATH 未刷新。

解决方案：

使用完整安装路径启动：

```powershell
& 'C:\Program Files (x86)\cloudflared\cloudflared.exe' tunnel --url http://127.0.0.1:8501
```

第一次在普通沙箱权限中启动公网连接失败，原因是外部 443 连接被限制。

解决方案：

使用非沙箱权限运行 tunnel 命令。
