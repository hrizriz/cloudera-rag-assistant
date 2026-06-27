from __future__ import annotations

import argparse
import sys

from cloudera_llm.llm.client import LLMClient
from cloudera_llm.rag.pipeline import RAGPipeline
from cloudera_llm.vectorstore.store import VectorStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat with the Cloudera RAG assistant")
    parser.add_argument("question", nargs="?", help="Question to ask")
    parser.add_argument("--top-k", type=int, default=None, help="Number of chunks to retrieve")
    args = parser.parse_args()

    if not args.question:
        parser.print_help()
        sys.exit(1)

    store = VectorStore()
    if store.count() == 0:
        print("Vector store is empty. Run: cloudera-ingest")
        sys.exit(1)

    llm = LLMClient()
    if not llm.health_check():
        print(
            "Cannot reach gemini-web2api. Start it first:\n"
            "  python gemini_web2api.py\n"
            "Expected base URL from config.yaml / .env"
        )
        sys.exit(1)

    pipeline = RAGPipeline(store=store, llm=llm)
    result = pipeline.ask(args.question, top_k=args.top_k)

    print("\n=== Answer ===\n")
    print(result.answer)
    print("\n=== Sources ===")
    for index, source in enumerate(result.sources, start=1):
        print(f"[{index}] {source.title} ({source.score:.2f})")
        print(f"    {source.source_url}")


if __name__ == "__main__":
    main()
