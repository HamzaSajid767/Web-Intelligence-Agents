"""Vector retrieval and storage operations."""

import hashlib
import uuid
from typing import Any

from app.ai.embeddings import EmbeddingProvider, get_embedding_provider
from app.core.constants import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE, QdrantCollection
from app.core.logging import get_logger
from app.vector.collections import ensure_all_collections, get_default_vector_size
from app.vector.qdrant_client import QdrantService

logger = get_logger(__name__)


def chunk_text(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks."""
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
        if start >= len(text):
            break
    return chunks


class VectorRetriever:
    """High-level vector storage and retrieval."""

    def __init__(
        self,
        qdrant: QdrantService | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.qdrant = qdrant or QdrantService()
        self.embeddings = embedding_provider or get_embedding_provider()
        self.vector_size = get_default_vector_size()
        ensure_all_collections(self.qdrant, self.vector_size)

    async def upsert_page_chunks(
        self,
        audit_id: str,
        page_url: str,
        clean_text: str,
    ) -> int:
        """Chunk page text, embed, and store in website_content collection."""
        chunks = chunk_text(clean_text)
        if not chunks:
            return 0

        vectors = await self.embeddings.embed_texts(chunks)
        ids = [
            str(uuid.uuid5(uuid.NAMESPACE_URL, f"{audit_id}:{page_url}:{i}"))
            for i in range(len(chunks))
        ]
        payloads = [
            {
                "audit_id": audit_id,
                "page_url": page_url,
                "chunk_index": i,
                "text": chunk,
            }
            for i, chunk in enumerate(chunks)
        ]
        self.qdrant.upsert_vectors(
            QdrantCollection.WEBSITE_CONTENT.value,
            ids=ids,
            vectors=vectors,
            payloads=payloads,
        )
        return len(chunks)

    async def search_similar_content(
        self,
        query: str,
        *,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Search website content by semantic similarity."""
        query_vector = await self.embeddings.embed_query(query)
        if not query_vector:
            return []
        results = self.qdrant.search(
            QdrantCollection.WEBSITE_CONTENT.value,
            query_vector,
            limit=limit,
        )
        return [
            {"score": hit.score, "payload": hit.payload}
            for hit in results
        ]

    async def store_audit_summary(
        self,
        audit_id: str,
        website_url: str,
        summary: str,
    ) -> None:
        """Store audit summary in audit_history collection."""
        vector = await self.embeddings.embed_query(summary)
        if not vector:
            return
        point_id = hashlib.sha256(audit_id.encode()).hexdigest()[:32]
        self.qdrant.upsert_vectors(
            QdrantCollection.AUDIT_HISTORY.value,
            ids=[point_id],
            vectors=[vector],
            payloads=[{
                "audit_id": audit_id,
                "website_url": website_url,
                "summary": summary,
            }],
        )

    async def find_similar_audits(
        self,
        summary: str,
        *,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Find similar past audits."""
        query_vector = await self.embeddings.embed_query(summary)
        if not query_vector:
            return []
        results = self.qdrant.search(
            QdrantCollection.AUDIT_HISTORY.value,
            query_vector,
            limit=limit,
        )
        return [
            {"score": hit.score, "payload": hit.payload}
            for hit in results
        ]
