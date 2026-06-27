from __future__ import annotations

import hashlib
from dataclasses import dataclass

import chromadb

from cloudera_llm.config import AppConfig, chroma_path, get_config
from cloudera_llm.embeddings.embedder import Embedder
from cloudera_llm.ingestion.chunker import DocumentChunk


@dataclass
class RetrievedChunk:
    text: str
    source_url: str
    title: str
    score: float
    product: str = ""
    version: str = ""
    service: str = ""
    doc_type: str = ""


class VectorStore:
    def __init__(self, config: AppConfig | None = None, embedder: Embedder | None = None) -> None:
        self.config = config or get_config()
        self.embedder = embedder or Embedder(self.config)
        self.client = chromadb.PersistentClient(path=str(chroma_path(self.config)))
        self.collection = self.client.get_or_create_collection(
            name=self.config.vectorstore.collection,
            metadata={"hnsw:space": "cosine"},
        )

    def reset(self) -> None:
        name = self.config.vectorstore.collection
        try:
            self.client.delete_collection(name)
        except ValueError:
            pass
        self.collection = self.client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )

    def add_chunks(self, chunks: list[DocumentChunk]) -> int:
        if not chunks:
            return 0

        texts = [chunk.text for chunk in chunks]
        embeddings = self.embedder.embed_documents(texts)
        ids = [_chunk_id(chunk.source_url, chunk.chunk_index) for chunk in chunks]
        metadatas = [
            {
                "source_url": chunk.source_url,
                "title": chunk.title,
                "chunk_index": chunk.chunk_index,
                "product": chunk.product,
                "version": chunk.version,
                "service": chunk.service,
                "doc_type": chunk.doc_type,
            }
            for chunk in chunks
        ]

        batch_size = 64
        for start in range(0, len(chunks), batch_size):
            end = start + batch_size
            self.collection.add(
                ids=ids[start:end],
                documents=texts[start:end],
                embeddings=embeddings[start:end],
                metadatas=metadatas[start:end],
            )

        return len(chunks)

    def query(self, question: str, top_k: int | None = None) -> list[RetrievedChunk]:
        k = top_k or self.config.vectorstore.top_k
        query_embedding = self.embedder.embed_query(question)
        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=k,
            include=["documents", "metadatas", "distances"],
        )

        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        retrieved: list[RetrievedChunk] = []
        for doc, meta, distance in zip(documents, metadatas, distances, strict=False):
            if not doc or not meta:
                continue
            score = 1.0 - float(distance)
            retrieved.append(
                RetrievedChunk(
                    text=doc,
                    source_url=str(meta.get("source_url", "")),
                    title=str(meta.get("title", "Untitled")),
                    score=score,
                    product=str(meta.get("product", "")),
                    version=str(meta.get("version", "")),
                    service=str(meta.get("service", "")),
                    doc_type=str(meta.get("doc_type", "")),
                )
            )
        return retrieved

    def count(self) -> int:
        return self.collection.count()


def _chunk_id(source_url: str, chunk_index: int) -> str:
    digest = hashlib.sha1(f"{source_url}:{chunk_index}".encode("utf-8")).hexdigest()
    return f"chunk_{digest}"
