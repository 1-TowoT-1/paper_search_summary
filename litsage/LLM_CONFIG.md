# LLM 配置说明

`app/llm/llm_client.py` 支持三种常见接入方式：

## OpenAI Responses API

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=你的_api_key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_MODE=responses
OPENAI_MODEL=gpt-4.1-mini
LLM_TEMPERATURE=0.2
LLM_TIMEOUT_SECONDS=60
LLM_MAX_OUTPUT_TOKENS=10000
```

## OpenAI-compatible Chat Completions

如果你接入的是兼容 OpenAI `/chat/completions` 的第三方大模型网关：

```env
LLM_PROVIDER=openai_compatible
OPENAI_API_KEY=你的_api_key
OPENAI_BASE_URL=https://你的网关地址/v1
OPENAI_API_MODE=chat_completions
OPENAI_MODEL=你的模型名
```

## DeepSeek

```env
LLM_PROVIDER=deepseek
OPENAI_API_KEY=你的_deepseek_api_key
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_API_MODE=responses
OPENAI_MODEL=deepseek-v4-flash
DEEPSEEK_VISION_MODEL=deepseek-v4-flash-vision-exp
```

如果 `LLM_PROVIDER=deepseek` 且没有配置 `OPENAI_BASE_URL`，程序会默认使用 `https://api.deepseek.com`。

## PDF OCR 与多模态兜底配置

当 PyMuPDF 原生解析出的 PDF 文本太短时，用户资料入库会按顺序尝试：

```text
1. Tesseract OCR
2. 多模态大模型图片识别
```

同时，如果开启 `PDF_MULTIMODAL_ENABLED=true`，系统会把 PDF 前几页渲染为图片交给当前多模态模型识别文献元数据：

```text
title
abstract
authors
keywords
language
confidence
```

摘要入库优先级：

```text
1. 用户手动填写 abstract
2. 原生文本中识别到的 Abstract / 摘要 / Rezumat
3. 多模态模型从 PDF 页面图片中识别或概括的 abstract
4. 文本 LLM 基于解析正文生成 ingestion_abstract
5. 正文开头摘录兜底
```

`.env` 示例：

```env
PDF_MIN_NATIVE_TEXT_CHARS=800

PDF_OCR_ENABLED=true
PDF_OCR_PROVIDER=tesseract
PDF_OCR_LANGUAGES=eng+chi_sim
PDF_OCR_MAX_PAGES=8
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe

PDF_MULTIMODAL_ENABLED=true
PDF_MULTIMODAL_MODEL=你的视觉模型名
PDF_MULTIMODAL_MAX_PAGES=3
PDF_RENDER_ZOOM=2.0
PDF_MULTIMODAL_IMAGE_TRANSPORT=base64
GENERATED_IMAGE_DIR=generated_images
GENERATED_IMAGE_BASE_URL=http://127.0.0.1:8000/generated_images
```

说明：

```text
1. Tesseract 需要额外安装系统程序和语言包，不只是 Python 依赖
2. 中文 OCR 需要 chi_sim 语言包
3. 多模态模型必须支持图片输入
4. 默认会把 PDF 页面渲染为 PNG，并以 base64 data URL 传给模型 API
5. 如果模型 API 只支持图片 URL，可以设置 `PDF_MULTIMODAL_IMAGE_TRANSPORT=url`
6. 使用 URL 模式时，`GENERATED_IMAGE_BASE_URL` 必须是模型服务可以访问到的地址；`127.0.0.1` 只适合模型服务和后端在同一台机器或同一网络环境时测试
7. URL 模式调用失败时，程序会自动回退到 base64 data URL 再尝试一次
8. 如果使用 OpenAI-compatible 网关，OPENAI_API_MODE 建议使用 chat_completions
9. 多模态兜底默认只识别前几页，避免成本和耗时过高
```

## DeepSeek 视觉模型说明

```env
OPENAI_MODEL=deepseek-v4-flash
DEEPSEEK_VISION_MODEL=deepseek-v4-flash-vision-exp
PDF_MULTIMODAL_MODEL=
PDF_MULTIMODAL_ENABLED=true
PDF_MULTIMODAL_IMAGE_TRANSPORT=base64
```

`OPENAI_MODEL` 用于普通文本问答、总结、查询改写。PDF 页面渲染为 PNG 后，会优先使用 `PDF_MULTIMODAL_MODEL`；如果该值为空，并且当前接入的是 DeepSeek，则自动使用 `DEEPSEEK_VISION_MODEL`。

建议默认保持 `PDF_MULTIMODAL_MODEL` 为空，只配置 `DEEPSEEK_VISION_MODEL=deepseek-v4-flash-vision-exp`。这样普通文本模型不会收到图片输入，也能避免图片解析时返回 `[Unsupported Image]` 或 `[无法识别]`。

## Ollama

```env
LLM_PROVIDER=ollama
LOCAL_OLLAMA_BASE_URL=http://localhost:11434
LOCAL_OLLAMA_MODEL=qwen2.5:7b
```

## 使用位置

- 查询改写：`LLMClient.rewrite_query`
- 单篇总结：`LLMClient.summarize`
- RAG 回答：`LLMClient.answer`

查询改写会要求模型返回 JSON，并做宽松解析；如果模型调用失败，会自动退回到本地规则改写，避免搜索接口整体不可用。
