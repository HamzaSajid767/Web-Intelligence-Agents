"""Qdrant collection management."""

from app.core.constants import QdrantCollection
from app.core.config import get_settings
from app.vector.qdrant_client import QdrantService


def ensure_all_collections(qdrant: QdrantService, vector_size: int = 768) -> None:
    """Ensure all required Qdrant collections exist."""
    qdrant.ensure_collection(QdrantCollection.WEBSITE_CONTENT.value, vector_size)
    qdrant.ensure_collection(QdrantCollection.AUDIT_HISTORY.value, vector_size)


def get_default_vector_size() -> int:
    """Return default vector dimension (configurable per embedding model)."""
    settings = get_settings()
    # Common sizes; override via env in future
    model_sizes = {
        "nomic-embed-text": 768,
        "mxbai-embed-large": 1024,
    }
    return model_sizes.get(settings.embedding_model, 768)
