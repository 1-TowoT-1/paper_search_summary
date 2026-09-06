from __future__ import annotations

import base64
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
            "You are an expert academic literature search assistant. Rewrite the user query into "
            "2-3 complementary English literature retrieval queries. If the user query is Chinese, "
            "translate the intent into precise English academic terms first. Preserve key domain "
            "concepts and do not add hard constraints that the user did not express."
        )
        user_prompt = (
            "Return JSON only, with this schema:\n"
            '{"queries": ["english query 1", "english query 2", "english query 3"]}\n\n'
            f"User query: {query}"
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

    async def generate_ingestion_abstract(self, text: str) -> str:
        system_prompt = (
            "你是科研资料入库助手。请为用户上传的资料生成一个客观、准确、适合语义检索的中文摘要。"
            "只能依据输入文本，不要编造作者、结果或结论。"
        )
        user_prompt = (
            "请生成 200-300 字中文摘要，覆盖研究主题、方法、内容范围和主要信息。"
            "如果资料不是论文，也按科研资料进行概括。\n\n"
            f"资料内容：\n{self._clip(text, 12000)}"
        )
        try:
            return await self._generate(system_prompt=system_prompt, user_prompt=user_prompt, max_output_tokens=700)
        except Exception as exc:
            logger.exception("LLM ingestion abstract failed")
            raise LLMClientError(f"Failed to generate ingestion abstract: {exc}") from exc

    async def extract_text_from_images(self, images: list[bytes], filename: str = "document.pdf") -> str:
        if not images:
            return ""
        self._validate_vision_model()
        logger.info(
            "multimodal extraction request filename=%s images=%s image_bytes=%s",
            filename,
            len(images),
            [len(image) for image in images],
        )
        if self.provider == "ollama":
            raise LLMClientError("Ollama multimodal extraction is not implemented")

        if self.provider not in {"openai", "openai_compatible", "compatible", "deepseek"}:
            raise LLMClientError(f"Multimodal extraction is not supported for provider: {self.provider}")

        mode = self._api_mode()
        if mode in {"chat", "chat_completions", "chat-completions"}:
            text = await self._extract_text_from_images_chat(images=images, filename=filename)
        else:
            text = await self._extract_text_from_images_responses(images=images, filename=filename)
        return self._validate_multimodal_text(text)

    async def extract_text_from_image_urls(self, image_urls: list[str], filename: str = "document.pdf") -> str:
        image_urls = [url.strip() for url in image_urls if url and url.strip()]
        if not image_urls:
            return ""
        self._validate_vision_model()
        logger.info(
            "multimodal extraction request filename=%s image_urls=%s",
            filename,
            len(image_urls),
        )
        if self.provider == "ollama":
            raise LLMClientError("Ollama multimodal extraction is not implemented")

        if self.provider not in {"openai", "openai_compatible", "compatible", "deepseek"}:
            raise LLMClientError(f"Multimodal extraction is not supported for provider: {self.provider}")

        mode = self._api_mode()
        if mode in {"chat", "chat_completions", "chat-completions"}:
            text = await self._extract_text_from_image_urls_chat(image_urls=image_urls, filename=filename)
        else:
            text = await self._extract_text_from_image_urls_responses(image_urls=image_urls, filename=filename)
        return self._validate_multimodal_text(text)

    async def extract_metadata_from_images(self, images: list[bytes], filename: str = "document.pdf") -> dict[str, Any]:
        if not images:
            return {}
        prompt = (
            f"请从用户上传资料 {filename} 的页面图片中识别文献元数据。"
            "只基于图片中可见内容，不要编造。"
            "返回 JSON，字段为："
            '{"title": "标题或空字符串", "abstract": "摘要原文或中文概括", '
            '"authors": [{"name": "作者名"}], "keywords": ["关键词"], '
            '"language": "语言", "confidence": "high|medium|low"}。'
            "如果图片中有 Abstract、摘要、Rezumat 等摘要段落，优先提取该段落；"
            "如果没有明确摘要，但能看懂首页主要内容，可以生成客观中文摘要。"
        )
        text = await self._generate_from_images(
            images=images,
            filename=filename,
            system_prompt="你是严谨的科研 PDF 首页元数据识别助手，只返回 JSON。",
            user_prompt=prompt,
            max_output_tokens=1000,
        )
        text = self._validate_multimodal_text(text)
        try:
            parsed = self._parse_json_object(text)
        except Exception as exc:
            raise LLMClientError(f"Failed to parse multimodal metadata JSON: {text[:500]}") from exc
        return parsed

    async def extract_metadata_from_image_urls(self, image_urls: list[str], filename: str = "document.pdf") -> dict[str, Any]:
        if not image_urls:
            return {}
        prompt = (
            f"请从用户上传资料 {filename} 的页面图片中识别文献元数据。"
            "只基于图片中可见内容，不要编造。"
            "返回 JSON，字段为："
            '{"title": "标题或空字符串", "abstract": "摘要原文或中文概括", '
            '"authors": [{"name": "作者名"}], "keywords": ["关键词"], '
            '"language": "语言", "confidence": "high|medium|low"}。'
            "如果图片中有 Abstract、摘要、Rezumat 等摘要段落，优先提取该段落；"
            "如果没有明确摘要，但能看懂首页主要内容，可以生成客观中文摘要。"
        )
        text = await self._generate_from_image_urls(
            image_urls=image_urls,
            filename=filename,
            system_prompt="你是严谨的科研 PDF 首页元数据识别助手，只返回 JSON。",
            user_prompt=prompt,
            max_output_tokens=1000,
        )
        text = self._validate_multimodal_text(text)
        try:
            parsed = self._parse_json_object(text)
        except Exception as exc:
            raise LLMClientError(f"Failed to parse multimodal metadata JSON: {text[:500]}") from exc
        return parsed

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

    async def assess_project_qa_summary_context(self, question: str, answer: str) -> dict[str, Any]:
        system_prompt = (
            "你是科研项目管理助手。请判断一条项目问答是否适合进入阶段性总结上下文。"
            "适合进入上下文的问答应当包含研究目标、研究方法、证据、结论、风险、实验设计、项目推进建议或重要待办。"
            "闲聊、测试、重复确认、无实际研究信息的问题不应进入总结上下文。只返回 JSON。"
        )
        user_prompt = (
            "请返回 JSON：\n"
            '{"include": true, "reason": "简短原因"}\n\n'
            f"问题：\n{question}\n\n"
            f"回答：\n{self._clip(answer, 3000)}"
        )
        try:
            text = await self._generate(system_prompt=system_prompt, user_prompt=user_prompt, max_output_tokens=300)
            parsed = self._parse_json_object(text)
            include = bool(parsed.get("include"))
            reason = str(parsed.get("reason") or "").strip()
            return {"include": include, "reason": reason or ("适合进入阶段总结" if include else "不适合进入阶段总结")}
        except Exception as exc:
            logger.warning("LLM QA summary-context assessment failed, using heuristic: %s", exc)
            return self._fallback_project_qa_summary_assessment(question=question, answer=answer)

    async def _generate(self, system_prompt: str, user_prompt: str, max_output_tokens: int | None = None) -> str:
        if self.provider == "ollama":
            return await self._generate_ollama(system_prompt, user_prompt, max_output_tokens)

        if self.provider in {"openai", "openai_compatible", "compatible", "deepseek"}:
            mode = self._api_mode()
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

    def _api_mode(self) -> str:
        mode = settings.openai_api_mode.lower().strip()
        if self.provider not in {"openai", "deepseek"} and mode == "responses":
            return "chat_completions"
        return mode

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

    async def _extract_text_from_images_responses(self, images: list[bytes], filename: str) -> str:
        return await self._generate_from_images_responses(
            images=images,
            system_prompt="你是严谨的科研 PDF 图像转文本助手，只输出从页面中识别到的文本。",
            user_prompt=(
                f"请从用户上传资料 {filename} 的页面图片中提取可用于科研入库的正文文本。"
                "保留标题、摘要、关键词、章节标题、图表题注和重要段落。"
                "不要解释任务，不要输出思考过程，不要编造图片中不存在的内容；看不清的位置写“局部文字不可读”。"
            ),
            max_output_tokens=settings.llm_max_output_tokens,
        )

    async def _extract_text_from_image_urls_responses(self, image_urls: list[str], filename: str) -> str:
        return await self._generate_from_image_urls_responses(
            image_urls=image_urls,
            system_prompt="你是严谨的科研 PDF 图像转文本助手，只输出从页面中识别到的文本。",
            user_prompt=(
                f"请从用户上传资料 {filename} 的页面图片中提取可用于科研入库的正文文本。"
                "保留标题、摘要、关键词、章节标题、图表题注和重要段落。"
                "不要解释任务，不要输出思考过程，不要编造图片中不存在的内容；看不清的位置写“局部文字不可读”。"
            ),
            max_output_tokens=settings.llm_max_output_tokens,
        )

    async def _extract_text_from_images_chat(self, images: list[bytes], filename: str) -> str:
        return await self._generate_from_images_chat(
            images=images,
            system_prompt="你是严谨的科研 PDF 图像转文本助手，只输出从页面中识别到的文本。",
            user_prompt=(
                f"请从用户上传资料 {filename} 的页面图片中提取可用于科研入库的正文文本。"
                "保留标题、摘要、关键词、章节标题、图表题注和重要段落。"
                "不要解释任务，不要输出思考过程，不要编造图片中不存在的内容；看不清的位置写“局部文字不可读”。"
            ),
            max_output_tokens=settings.llm_max_output_tokens,
        )

    async def _extract_text_from_image_urls_chat(self, image_urls: list[str], filename: str) -> str:
        return await self._generate_from_image_urls_chat(
            image_urls=image_urls,
            system_prompt="你是严谨的科研 PDF 图像转文本助手，只输出从页面中识别到的文本。",
            user_prompt=(
                f"请从用户上传资料 {filename} 的页面图片中提取可用于科研入库的正文文本。"
                "保留标题、摘要、关键词、章节标题、图表题注和重要段落。"
                "不要解释任务，不要输出思考过程，不要编造图片中不存在的内容；看不清的位置写“局部文字不可读”。"
            ),
            max_output_tokens=settings.llm_max_output_tokens,
        )

    async def _generate_from_images(
        self,
        images: list[bytes],
        filename: str,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> str:
        _ = filename
        if self.provider == "ollama":
            raise LLMClientError("Ollama multimodal extraction is not implemented")
        mode = self._api_mode()
        if mode in {"chat", "chat_completions", "chat-completions"}:
            return await self._generate_from_images_chat(images, system_prompt, user_prompt, max_output_tokens)
        return await self._generate_from_images_responses(images, system_prompt, user_prompt, max_output_tokens)

    async def _generate_from_image_urls(
        self,
        image_urls: list[str],
        filename: str,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> str:
        _ = filename
        if self.provider == "ollama":
            raise LLMClientError("Ollama multimodal extraction is not implemented")
        mode = self._api_mode()
        if mode in {"chat", "chat_completions", "chat-completions"}:
            return await self._generate_from_image_urls_chat(image_urls, system_prompt, user_prompt, max_output_tokens)
        return await self._generate_from_image_urls_responses(image_urls, system_prompt, user_prompt, max_output_tokens)

    async def _generate_from_images_responses(
        self,
        images: list[bytes],
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> str:
        if not settings.openai_api_key:
            raise LLMClientError("OPENAI_API_KEY is not configured")

        content: list[dict[str, Any]] = [{"type": "input_text", "text": user_prompt}]
        for image in images:
            content.append({"type": "input_image", "image_url": self._image_data_url(image)})

        payload: dict[str, Any] = {
            "model": self._vision_model(),
            "instructions": system_prompt,
            "input": [{"role": "user", "content": content}],
            "temperature": 0,
            "max_output_tokens": max_output_tokens,
        }
        data = await self._post_json(
            url=f"{self.openai_base_url}/responses",
            payload=payload,
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        )
        return self._extract_responses_text(data)

    async def _generate_from_image_urls_responses(
        self,
        image_urls: list[str],
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> str:
        if not settings.openai_api_key:
            raise LLMClientError("OPENAI_API_KEY is not configured")

        content: list[dict[str, Any]] = [{"type": "input_text", "text": user_prompt}]
        for image_url in image_urls:
            content.append({"type": "input_image", "image_url": image_url})

        payload: dict[str, Any] = {
            "model": self._vision_model(),
            "instructions": system_prompt,
            "input": [{"role": "user", "content": content}],
            "temperature": 0,
            "max_output_tokens": max_output_tokens,
        }
        data = await self._post_json(
            url=f"{self.openai_base_url}/responses",
            payload=payload,
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        )
        return self._extract_responses_text(data)

    async def _generate_from_images_chat(
        self,
        images: list[bytes],
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> str:
        if not settings.openai_api_key:
            raise LLMClientError("OPENAI_API_KEY is not configured")

        content: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]
        for image in images:
            content.append({"type": "image_url", "image_url": {"url": self._image_data_url(image)}})

        payload: dict[str, Any] = {
            "model": self._vision_model(),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            "temperature": 0,
            "max_tokens": max_output_tokens,
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

    async def _generate_from_image_urls_chat(
        self,
        image_urls: list[str],
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> str:
        if not settings.openai_api_key:
            raise LLMClientError("OPENAI_API_KEY is not configured")

        content: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]
        for image_url in image_urls:
            content.append({"type": "image_url", "image_url": {"url": image_url}})

        payload: dict[str, Any] = {
            "model": self._vision_model(),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            "temperature": 0,
            "max_tokens": max_output_tokens,
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
            item_type = str(item.get("type") or "").lower()
            if item_type and item_type != "message":
                continue
            for content in item.get("content", []) or []:
                content_type = str(content.get("type") or "").lower()
                if content_type and content_type not in {"output_text", "text"}:
                    continue
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
        if self._contains_cjk(query):
            return [query]
        if len(query.split()) <= 2:
            return [query, f"{query} survey", f"{query} recent advances"]
        return [query, f"{query} applications", f"{query} methods comparison"]

    def _fallback_project_qa_summary_assessment(self, question: str, answer: str) -> dict[str, Any]:
        text = f"{question}\n{answer}".strip()
        lowered = text.lower()
        trivial_markers = ("test", "hello", "hi", "ping", "随便", "测试", "你好", "在吗", "谢谢")
        research_markers = (
            "研究",
            "方法",
            "实验",
            "结论",
            "证据",
            "机制",
            "进展",
            "风险",
            "方案",
            "数据",
            "模型",
            "analysis",
            "method",
            "evidence",
            "result",
            "study",
        )
        if len(text) < 20 or any(marker in lowered for marker in trivial_markers):
            return {"include": False, "reason": "问题或回答缺少有效研究信息"}
        if any(marker in lowered for marker in research_markers):
            return {"include": True, "reason": "包含研究相关信息，可用于阶段总结"}
        return {"include": False, "reason": "未识别到明确研究推进价值"}

    def _contains_cjk(self, text: str) -> bool:
        return bool(re.search(r"[\u4e00-\u9fff]", text))

    def _validate_vision_model(self) -> None:
        model = self._vision_model()
        base_url = self.openai_base_url.lower()
        if self.provider == "deepseek" or "api.deepseek.com" in base_url:
            if model != "deepseek-v4-flash-vision-exp":
                raise LLMClientError(
                    "DeepSeek image input requires model `deepseek-v4-flash-vision-exp`. "
                    f"Current model is `{model}`."
                )

    def _vision_model(self) -> str:
        if settings.pdf_multimodal_model:
            return settings.pdf_multimodal_model
        base_url = self.openai_base_url.lower()
        if self.provider == "deepseek" or "api.deepseek.com" in base_url:
            return settings.deepseek_vision_model
        return settings.openai_model

    def _validate_multimodal_text(self, text: str) -> str:
        cleaned = text.strip()
        if not cleaned:
            raise LLMClientError("Multimodal extraction returned empty text")

        unsupported_markers = (
            "[unsupported image]",
            "unsupported image",
            "无法看到上传的图片内容",
            "图片显示为",
            "无法读取图片内容",
            "无法识别图片内容",
            "不能读取图片",
            "不支持图片",
            "图片格式不被支持",
            "未能成功上传",
            "重新上传",
            "直接上传可读取的 pdf",
            "收到可用的图片后",
        )
        lowered = cleaned.lower()
        if any(marker in lowered for marker in unsupported_markers):
            raise LLMClientError(f"Multimodal extraction did not process images: {cleaned[:300]}")
        return cleaned

    def _image_data_url(self, image: bytes) -> str:
        return "data:image/png;base64," + base64.b64encode(image).decode("ascii")

    def _clip(self, text: str, max_chars: int) -> str:
        text = text.strip()
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n\n[内容过长，已截断]"
