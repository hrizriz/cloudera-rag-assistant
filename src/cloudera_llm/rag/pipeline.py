from __future__ import annotations

from dataclasses import dataclass

from cloudera_llm.config import AppConfig, get_config
from cloudera_llm.ingestion.chunker import chunk_text
from cloudera_llm.ingestion.local_files import load_local_documents, save_local_documents
from cloudera_llm.ingestion.scraper import ClouderaDocScraper, ScrapedPage
from cloudera_llm.llm.client import LLMClient, LLMResponse
from cloudera_llm.vectorstore.store import RetrievedChunk, VectorStore


@dataclass
class RAGAnswer:
    answer: str
    sources: list[RetrievedChunk]
    model: str


class RAGPipeline:
    def __init__(
        self,
        config: AppConfig | None = None,
        store: VectorStore | None = None,
        llm: LLMClient | None = None,
    ) -> None:
        self.config = config or get_config()
        self.store = store or VectorStore(self.config)
        self.llm = llm or LLMClient(self.config)

    def ingest_from_web(self, *, reset: bool = False) -> dict[str, int]:
        scraper = ClouderaDocScraper(self.config)
        try:
            pages = scraper.crawl()
        finally:
            scraper.close()

        return self.ingest_pages(pages, reset=reset)

    def ingest_from_local(self, *, reset: bool = False, persist_raw: bool = True) -> dict[str, int]:
        pages = load_local_documents()
        if persist_raw:
            save_local_documents(pages)
        return self.ingest_pages(pages, reset=reset)

    def ingest_all(self, *, reset: bool = False) -> dict[str, int]:
        local_stats = self.ingest_from_local(reset=reset, persist_raw=True)
        web_stats = self.ingest_from_web(reset=False)
        return {
            "pages": local_stats["pages"] + web_stats["pages"],
            "chunks": local_stats["chunks"] + web_stats["chunks"],
            "total_vectors": self.store.count(),
            "local_pages": local_stats["pages"],
            "web_pages": web_stats["pages"],
        }

    def ingest_pages(self, pages: list[ScrapedPage], *, reset: bool = False) -> dict[str, int]:
        if reset:
            self.store.reset()

        all_chunks = []
        for page in pages:
            header = _metadata_header(page)
            all_chunks.extend(
                chunk_text(
                    page.text,
                    source_url=page.url,
                    title=page.title,
                    chunk_size=self.config.rag.chunk_size,
                    chunk_overlap=self.config.rag.chunk_overlap,
                    product=page.product,
                    version=page.version,
                    service=page.service,
                    doc_type=page.doc_type,
                    metadata_header=header,
                )
            )

        added = self.store.add_chunks(all_chunks)
        return {
            "pages": len(pages),
            "chunks": added,
            "total_vectors": self.store.count(),
        }

    def ask(self, question: str, *, top_k: int | None = None) -> RAGAnswer:
        chunks = self.store.query(question, top_k=top_k)
        context = _format_context(chunks, max_chars=self.config.rag.max_context_chars)
        response: LLMResponse = self.llm.chat(question, context)
        return RAGAnswer(answer=response.content, sources=chunks, model=response.model)


def _format_context(chunks: list[RetrievedChunk], *, max_chars: int) -> str:
    if not chunks:
        return "No relevant documentation found in the local knowledge base."

    parts: list[str] = []
    total = 0
    for index, chunk in enumerate(chunks, start=1):
        block = (
            f"[Source {index}] {chunk.title}\n"
            f"URL: {chunk.source_url}\n"
            f"Product: {chunk.product or 'n/a'} | Version: {chunk.version or 'n/a'} | "
            f"Service: {chunk.service or 'n/a'} | Type: {chunk.doc_type or 'n/a'}\n"
            f"Relevance: {chunk.score:.2f}\n"
            f"{chunk.text}\n"
        )
        if total + len(block) > max_chars:
            break
        parts.append(block)
        total += len(block)

    return "\n---\n".join(parts)


def _metadata_header(page: ScrapedPage) -> str:
    parts = [
        f"Product: {page.product_name or page.product or 'unknown'}",
        f"Version: {page.version or 'unknown'}",
    ]
    if page.service:
        parts.append(f"Service: {page.service}")
    if page.doc_type:
        parts.append(f"DocType: {page.doc_type}")
    if page.is_support_matrix:
        parts.append("SupportMatrix: yes")
    return " | ".join(parts)
