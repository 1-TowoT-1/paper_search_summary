from app.config import settings


class LLMClient:
    async def rewrite_query(self, query: str) -> list[str]:
        if len(query.split()) <= 2:
            return [query, f"{query} survey", f"{query} recent advances"]
        return [query, f"{query} applications", f"{query} methods comparison"]

    async def summarize(self, paper_text: str) -> str:
        preview = paper_text.strip().replace("\n", " ")[:800] or "No abstract/full text available."
        return (
            "## Research background\n"
            f"{preview}\n\n"
            "## Method\n"
            "待接入 LLM 后基于全文自动提取。\n\n"
            "## Innovation\n"
            "待接入 LLM 后生成结构化创新点。\n\n"
            "## Limitations\n"
            "待接入 LLM 后结合论文内容归纳局限。"
        )

    async def answer(self, question: str, context: str) -> str:
        if not context.strip():
            return "当前检索上下文不足，无法给出可靠回答。请先导入相关文献或缩小问题范围。"
        return f"基于已检索片段，可以围绕“{question}”进行回答。生产环境中这里会调用 {settings.llm_provider} 模型并附带引用。"

