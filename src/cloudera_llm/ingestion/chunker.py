from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class DocumentChunk:
    text: str
    source_url: str
    title: str
    chunk_index: int
    product: str = ""
    version: str = ""
    service: str = ""
    doc_type: str = ""


def chunk_text(
    text: str,
    *,
    source_url: str,
    title: str,
    chunk_size: int = 800,
    chunk_overlap: int = 150,
    product: str = "",
    version: str = "",
    service: str = "",
    doc_type: str = "",
    metadata_header: str = "",
) -> list[DocumentChunk]:
    cleaned = _normalize_whitespace(text)
    if not cleaned:
        return []

    prefix = metadata_header.strip()
    if prefix:
        cleaned = f"{prefix}\n\n{cleaned}"

    if len(cleaned) <= chunk_size:
        return [
            DocumentChunk(
                cleaned,
                source_url,
                title,
                0,
                product=product,
                version=version,
                service=service,
                doc_type=doc_type,
            )
        ]

    chunks: list[DocumentChunk] = []
    start = 0
    index = 0
    while start < len(cleaned):
        end = min(start + chunk_size, len(cleaned))
        if end < len(cleaned):
            split_at = _find_split_point(cleaned, start, end)
            if split_at > start:
                end = split_at

        piece = cleaned[start:end].strip()
        if piece:
            chunks.append(
                DocumentChunk(
                    piece,
                    source_url,
                    title,
                    index,
                    product=product,
                    version=version,
                    service=service,
                    doc_type=doc_type,
                )
            )
            index += 1

        if end >= len(cleaned):
            break
        start = max(end - chunk_overlap, start + 1)

    return chunks


def _normalize_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _find_split_point(text: str, start: int, end: int) -> int:
    window = text[start:end]
    for marker in ("\n\n", ". ", ".\n", "\n"):
        pos = window.rfind(marker)
        if pos > len(window) * 0.4:
            return start + pos + len(marker)
    return end
