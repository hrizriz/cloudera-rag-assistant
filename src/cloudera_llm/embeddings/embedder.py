from __future__ import annotations

from functools import lru_cache

from sentence_transformers import SentenceTransformer

from cloudera_llm.config import AppConfig, get_config


class Embedder:
    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or get_config()
        self.model = _load_model(self.config.embedding.model)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(texts, show_progress_bar=len(texts) > 20)
        return vectors.tolist()

    def embed_query(self, text: str) -> list[float]:
        vector = self.model.encode(text)
        return vector.tolist()


@lru_cache
def _load_model(model_name: str) -> SentenceTransformer:
    return SentenceTransformer(model_name)
