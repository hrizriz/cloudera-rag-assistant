from __future__ import annotations

from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from cloudera_llm.llm.client import LLMClient
from cloudera_llm.rag.pipeline import RAGPipeline
from cloudera_llm.vectorstore.store import VectorStore

app = FastAPI(title="Cloudera LLM", version="0.1.0")

_pipeline: RAGPipeline | None = None
_store: VectorStore | None = None
_llm: LLMClient | None = None


class ChatRequest(BaseModel):
    question: str = Field(min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=20)


class SourceItem(BaseModel):
    title: str
    url: str
    score: float
    excerpt: str


class ChatResponse(BaseModel):
    answer: str
    model: str
    sources: list[SourceItem]


def _get_pipeline() -> RAGPipeline:
    global _pipeline, _store, _llm
    if _pipeline is None:
        _store = VectorStore()
        _llm = LLMClient()
        _pipeline = RAGPipeline(store=_store, llm=_llm)
    return _pipeline


@app.get("/health")
def health() -> dict[str, Any]:
    store = VectorStore()
    llm = LLMClient()
    return {
        "status": "ok",
        "vectors": store.count(),
        "llm_reachable": llm.health_check(),
    }


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    pipeline = _get_pipeline()
    if pipeline.store.count() == 0:
        raise HTTPException(
            status_code=503,
            detail="Vector store is empty. Run `cloudera-ingest` first.",
        )

    if not pipeline.llm.health_check():
        raise HTTPException(
            status_code=503,
            detail="gemini-web2api is not reachable. Start it on localhost:8081.",
        )

    result = pipeline.ask(request.question, top_k=request.top_k)
    sources = [
        SourceItem(
            title=source.title,
            url=source.source_url,
            score=source.score,
            excerpt=source.text[:240],
        )
        for source in result.sources
    ]
    return ChatResponse(answer=result.answer, model=result.model, sources=sources)


def serve() -> None:
    uvicorn.run("cloudera_llm.api.main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    serve()
