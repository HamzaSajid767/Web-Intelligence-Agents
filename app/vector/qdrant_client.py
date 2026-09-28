"""Qdrant vector database client wrapper."""

from typing import Any
from uuid import UUID

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class QdrantService:
    """Async-compatible wrapper around Qdrant client."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: QdrantClient | None = None

    @property
    def client(self) -> QdrantClient:
        """Lazy-init Qdrant client."""
        if self._client is None:
            kwargs: dict[str, Any] = {"url": self.settings.qdrant_url}
            if self.settings.qdrant_api_key:
                kwargs["api_key"] = self.settings.qdrant_api_key
            self._client = QdrantClient(**kwargs)
        return self._client

    def ensure_collection(self, name: str, vector_size: int) -> None:
        """Create collection if it does not exist."""
        collections = {c.name for c in self.client.get_collections().collections}
        if name not in collections:
            self.client.create_collection(
                collection_name=name,
                vectors_config=qmodels.VectorParams(size=vector_size, distance=qmodels.Distance.COSINE),
            )
            logger.info("Created Qdrant collection", extra={"collection": name})

    def upsert_vectors(
        self,
        collection: str,
        *,
        ids: list[str | UUID],
        vectors: list[list[float]],
        payloads: list[dict[str, Any]],
    ) -> None:
        """Upsert vectors with payloads."""
        points = [
            qmodels.PointStruct(id=str(point_id), vector=vector, payload=payload)
            for point_id, vector, payload in zip(ids, vectors, payloads, strict=True)
        ]
        self.client.upsert(collection_name=collection, points=points)

    def search(
        self,
        collection: str,
        query_vector: list[float],
        *,
        limit: int = 5,
        score_threshold: float | None = None,
    ) -> list[qmodels.ScoredPoint]:
        """Similarity search in a collection."""
        return self.client.search(
            collection_name=collection,
            query_vector=query_vector,
            limit=limit,
            score_threshold=score_threshold,
        )
