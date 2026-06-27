from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = ROOT_DIR / "config.yaml"


class LLMConfig(BaseModel):
    base_url: str = "http://127.0.0.1:8081/v1"
    api_key: str = "sk-anything"
    model: str = "gemini-3.5-flash"
    timeout_sec: int = 180


class EmbeddingConfig(BaseModel):
    model: str = "sentence-transformers/all-MiniLM-L6-v2"


class VectorStoreConfig(BaseModel):
    path: str = "./data/chroma"
    collection: str = "cloudera_docs"
    top_k: int = 5


class RAGConfig(BaseModel):
    chunk_size: int = 800
    chunk_overlap: int = 150
    max_context_chars: int = 12000


class IngestionConfig(BaseModel):
    mode: str = "sitemap"
    sitemap_index_url: str = "https://docs.cloudera.com/sitemap.xml"
    sitemap_include: list[str] = Field(default_factory=list)
    sitemap_exclude: list[str] = Field(default_factory=list)
    seed_urls: list[str] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=lambda: ["docs.cloudera.com"])
    max_pages: int = 0
    max_crawl_discover: int = 500
    delay_seconds: float = 2.0
    delay_jitter_seconds: float = 1.5
    retry_attempts: int = 5
    retry_backoff_seconds: float = 5.0
    cooldown_on_429_seconds: float = 60.0
    rotate_user_agent: bool = True
    warmup_url: str = "https://docs.cloudera.com/"
    resume: bool = True
    prioritize_support_matrix: bool = True
    proxy: str | None = None
    local_data_dir: str = "./data"
    local_extensions: list[str] = Field(
        default_factory=lambda: [".docx", ".pdf", ".xlsx", ".xlsm", ".zip"]
    )


class AppConfig(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    vectorstore: VectorStoreConfig = Field(default_factory=VectorStoreConfig)
    rag: RAGConfig = Field(default_factory=RAGConfig)
    ingestion: IngestionConfig = Field(default_factory=IngestionConfig)


class TelegramSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str = ""
    telegram_allowed_chat_ids: str = ""

    def allowed_chat_ids(self) -> list[int]:
        if not self.telegram_allowed_chat_ids.strip():
            return []
        ids: list[int] = []
        for raw in self.telegram_allowed_chat_ids.split(","):
            value = raw.strip()
            if value:
                ids.append(int(value))
        return ids


class EnvSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    embedding_model: str | None = None
    chroma_path: str | None = None
    collection_name: str | None = None


def _load_yaml_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _resolve_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path


@lru_cache
def get_config(config_path: str | Path | None = None) -> AppConfig:
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    data = _load_yaml_config(path)
    config = AppConfig.model_validate(data)

    env = EnvSettings()
    if env.llm_base_url:
        config.llm.base_url = env.llm_base_url
    if env.llm_api_key:
        config.llm.api_key = env.llm_api_key
    if env.llm_model:
        config.llm.model = env.llm_model
    if env.embedding_model:
        config.embedding.model = env.embedding_model
    if env.chroma_path:
        config.vectorstore.path = env.chroma_path
    if env.collection_name:
        config.vectorstore.collection = env.collection_name

    return config


@lru_cache
def get_telegram_settings() -> TelegramSettings:
    return TelegramSettings()


def chroma_path(config: AppConfig | None = None) -> Path:
    cfg = config or get_config()
    path = _resolve_path(cfg.vectorstore.path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def raw_data_path() -> Path:
    path = ROOT_DIR / "data" / "raw"
    path.mkdir(parents=True, exist_ok=True)
    return path
