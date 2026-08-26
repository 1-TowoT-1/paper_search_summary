from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"


class LLMClientError(RuntimeError):
    pass


class LLMClient:
    def __init__(self) -> None:
        self.provider = settings.llm_provider.lower().strip()
        self.openai_base_url = self._resolve_openai_base_url()
        self.ollama_base_url = settings.local_ollama_base_url.rstrip("/")

    async def rewrite_query(self, query: str) -> list[str]:
        system_prompt = (
            "你是科研文献检索专家。请把用户查询改写成 2-3 个互补的检索查询，"
            "用于提高语义检索召回率。保留关键术语，不要添加用户没有表达的硬性限制。"
        )
        user_prompt = (
            "请只返回 JSON，格式为：\n"
            '{"queries": ["查询1", "查询2", "查询3"]}\n\n'
            f"用户查询：{query}"
        )

        try:
            text = await self._generate(system_prompt=system_prompt, user_prompt=user_prompt, max_output_tokens=500)
            parsed = self._parse_json_object(text)
            variants = parsed.get("queries", []) if isinstance(parsed, dict) else []
            if not isinstance(variants, list):
                variants = []
            return self._unique_queries([query, *[str(item).strip() for item in variants]])
        except Exception as exc:
            logger.warning("LLM query rewrite failed, using fallback: %s", exc)
            return self._fallback_rewrite(query)

    async def summarize(self, paper_text: str) -> str:
        system_prompt = (
            "你是严谨的科研论文阅读助手。请基于输入内容生成中文 Markdown 结构化总结。"
            "如果原文信息不足，请明确写出不足，不要编造论文细节。"
        )
        user_prompt = (
            "请按以下小节总结论文：\n"
            "## 研究背景\n"
            "## 核心方法\n"
            "## 主要创新\n"
            "## 实验与结论\n"
            "## 局限与后续方向\n\n"
            f"论文内容：\n{self._clip(paper_text, 18000)}"
        )
        try:
            return await self._generate(system_prompt=system_prompt, user_prompt=user_prompt)
        except Exception as exc:
            logger.exception("LLM paper summary failed")
            return f"LLM 调用失败，暂时无法生成总结。\n\n错误信息：{exc}"

    async def answer(self, question: str, context: str) -> str:
        if not context.strip():
            return "当前检索上下文不足，无法给出可靠回答。请先导入相关文献或缩小问题范围。"
        system_prompt = (
            "你是文献问答助手。只能依据用户提供的文献片段回答。"
            "如果片段不足以回答，请说明缺少哪些信息。回答要简洁、可追溯，并保留片段中的引用标记。"
        )
        user_prompt = (
            f"问题：\n{question}\n\n"
            f"文献片段：\n{self._clip(context, 18000)}"
        )
        try:
            return await self._generate(system_prompt=system_prompt, user_prompt=user_prompt)
        except Exception as exc:
            logger.exception("LLM RAG answer failed")
            return f"LLM 调用失败，暂时无法生成回答。\n\n错误信息：{exc}"

    async def _generate(self, system_prompt: str, user_prompt: str, max_output_tokens: int | None = None) -> str:
        if self.provider == "ollama":
            return await self._generate_ollama(system_prompt, user_prompt, max_output_tokens)

        if self.provider in {"openai", "openai_compatible", "compatible", "deepseek"}:
            mode = settings.openai_api_mode.lower().strip()
            if self.provider != "openai" and mode == "responses":
                mode = "chat_completions"
            if mode in {"chat", "chat_completions", "chat-completions"}:
                return await self._generate_openai_chat(system_prompt, user_prompt, max_output_tokens)
            return await self._generate_openai_responses(system_prompt, user_prompt, max_output_tokens)

        logger.warning("Unknown LLM_PROVIDER=%s, trying OpenAI-compatible chat completions", settings.llm_provider)
        return await self._generate_openai_chat(system_prompt, user_prompt, max_output_tokens)

    def _resolve_openai_base_url(self) -> str:
        base_url = settings.openai_base_url.rstrip("/")
        if self.provider == "deepseek" and base_url == DEFAULT_OPENAI_BASE_URL:
            return DEFAULT_DEEPSEEK_BASE_URL
        return base_url

    async def _generate_openai_responses(
        self,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int | None,
    ) -> str:
        if not settings.openai_api_key:
            raise LLMClientError("OPENAI_API_KEY is not configured")

        payload: dict[str, Any] = {
            "model": settings.openai_model,
            "instructions": system_prompt,
            "input": user_prompt,
            "temperature": settings.llm_temperature,
            "max_output_tokens": max_output_tokens or settings.llm_max_output_tokens,
        }
        data = await self._post_json(
            url=f"{self.openai_base_url}/responses",
            payload=payload,
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        )
        return self._extract_responses_text(data)

    async def _generate_openai_chat(
        self,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int | None,
    ) -> str:
        if not settings.openai_api_key:
            raise LLMClientError("OPENAI_API_KEY is not configured")

        payload: dict[str, Any] = {
            "model": settings.openai_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": settings.llm_temperature,
            "max_tokens": max_output_tokens or settings.llm_max_output_tokens,
        }
        data = await self._post_json(
            url=f"{self.openai_base_url}/chat/completions",
            payload=payload,
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        )
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMClientError(f"Unexpected chat completions response: {data}") from exc

    async def _generate_ollama(
        self,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int | None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": settings.local_ollama_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {
                "temperature": settings.llm_temperature,
                "num_predict": max_output_tokens or settings.llm_max_output_tokens,
            },
        }
        data = await self._post_json(url=f"{self.ollama_base_url}/api/chat", payload=payload, headers={})
        content = data.get("message", {}).get("content") or data.get("response")
        if not content:
            raise LLMClientError(f"Unexpected Ollama response: {data}")
        return str(content).strip()

    async def _post_json(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        request_headers = {"Content-Type": "application/json", **headers}
        try:
            async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
                response = await client.post(url, json=payload, headers=request_headers)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:1000]
            raise LLMClientError(f"LLM API HTTP {exc.response.status_code}: {detail}") from exc
        except httpx.RequestError as exc:
            raise LLMClientError(f"LLM API request failed: {exc}") from exc
        except ValueError as exc:
            raise LLMClientError("LLM API returned non-JSON response") from exc

    def _extract_responses_text(self, data: dict[str, Any]) -> str:
        output_text = data.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        parts: list[str] = []
        for item in data.get("output", []) or []:
            for content in item.get("content", []) or []:
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())

        if parts:
            return "\n".join(parts).strip()
        raise LLMClientError(f"Unexpected responses API response: {data}")

    def _parse_json_object(self, text: str) -> dict[str, Any]:
        cleaned = text.strip()
        fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, flags=re.DOTALL | re.IGNORECASE)
        if fenced:
            cleaned = fenced.group(1).strip()

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
            if not match:
                raise
            parsed = json.loads(match.group(0))

        if not isinstance(parsed, dict):
            raise LLMClientError("Expected JSON object from LLM")
        return parsed

    def _unique_queries(self, queries: list[str]) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for query in queries:
            normalized = " ".join(query.split())
            key = normalized.lower()
            if normalized and key not in seen:
                seen.add(key)
                unique.append(normalized)
            if len(unique) >= 3:
                break
        return unique or self._fallback_rewrite("")

    def _fallback_rewrite(self, query: str) -> list[str]:
        query = query.strip()
        if not query:
            return []
        if len(query.split()) <= 2:
            return [query, f"{query} survey", f"{query} recent advances"]
        return [query, f"{query} applications", f"{query} methods comparison"]

    def _clip(self, text: str, max_chars: int) -> str:
        text = text.strip()
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n\n[内容过长，已截断]"
