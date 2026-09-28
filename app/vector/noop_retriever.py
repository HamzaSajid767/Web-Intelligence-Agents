"""No-op vector retriever for Phase 2 (RAG disabled)."""

from typing import Any


class NoOpVectorRetriever:
    """Placeholder retriever when vector/RAG features are disabled."""

    async def upsert_page_chunks(self, audit_id: str, page_url: str, clean_text: str) -> int:
        return 0

    async def store_audit_summary(self, audit_id: str, website_url: str, summary: str) -> None:
        return None

    async def search_similar_content(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        return []

    async def find_similar_audits(self, summary: str, *, limit: int = 3) -> list[dict[str, Any]]:
        return []
