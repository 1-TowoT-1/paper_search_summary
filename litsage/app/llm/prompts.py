QUERY_REWRITE_PROMPT = """Rewrite the user literature query into 2-3 complementary retrieval queries.
Keep domain terms precise and avoid inventing constraints.

Query: {query}
"""

PAPER_SUMMARY_PROMPT = """Summarize the paper using Markdown with these sections:
- Research background
- Method
- Innovation
- Limitations

Paper:
{paper_text}
"""

RAG_ANSWER_PROMPT = """Answer the question using only the cited literature snippets.
If the snippets are insufficient, say what is missing.
Return concise Chinese unless the user asks otherwise.

Question:
{question}

Snippets:
{context}
"""

