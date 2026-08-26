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
LLM_MAX_OUTPUT_TOKENS=1600
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
OPENAI_API_MODE=chat_completions
OPENAI_MODEL=deepseek-chat
```

如果 `LLM_PROVIDER=deepseek` 且没有配置 `OPENAI_BASE_URL`，程序会默认使用 `https://api.deepseek.com`。

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
