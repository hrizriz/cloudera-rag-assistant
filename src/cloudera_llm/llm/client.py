from __future__ import annotations

from dataclasses import dataclass

from openai import OpenAI

from cloudera_llm.config import AppConfig, get_config


SYSTEM_PROMPT = """You are a Cloudera expert assistant.

Rules:
- Answer using ONLY the provided Cloudera documentation context.
- Always mention product, version, and service when available in the context.
- For compatibility or version questions, prioritize support-matrix and release-notes sources.
- If the context is insufficient, say you do not have enough information and suggest what to check in Cloudera docs.
- Be practical: include steps, commands, or configuration hints when relevant.
- Cite sources using [Source N] markers from the context.
- Match the user's language (Indonesian or English).
"""


@dataclass
class LLMResponse:
    content: str
    model: str


class LLMClient:
    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or get_config()
        self.client = OpenAI(
            base_url=self.config.llm.base_url,
            api_key=self.config.llm.api_key,
            timeout=self.config.llm.timeout_sec,
        )

    def chat(self, question: str, context: str, *, system_prompt: str = SYSTEM_PROMPT) -> LLMResponse:
        user_message = (
            "Use the following Cloudera documentation excerpts to answer the question.\n\n"
            f"Context:\n{context}\n\n"
            f"Question: {question}"
        )

        response = self.client.chat.completions.create(
            model=self.config.llm.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )

        choice = response.choices[0].message
        content = choice.content or ""
        model = response.model or self.config.llm.model
        return LLMResponse(content=content, model=model)

    def health_check(self) -> bool:
        try:
            self.client.models.list()
            return True
        except Exception:
            return False
