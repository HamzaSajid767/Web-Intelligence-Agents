"""Replaceable embedding provider interface."""

from typing import Protocol

from app.core.config import Settings, get_settings


class EmbeddingProvider(Protocol):
    """Protocol for text embedding providers."""

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts."""
        ...

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query text."""
        ...


class OllamaEmbeddingProvider:
    """Ollama-based embedding provider."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.base_url = self.settings.ollama_base_url.rstrip("/")
        self.model = self.settings.embedding_model
        self.timeout = self.settings.ollama_timeout_seconds

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts via Ollama."""
        import httpx

        embeddings: list[list[float]] = []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for text in texts:
                response = await client.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": self.model, "prompt": text},
                )
                response.raise_for_status()
                data = response.json()
                embeddings.append(data.get("embedding", []))
        return embeddings

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query."""
        results = await self.embed_texts([text])
        return results[0] if results else []


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    """Factory for embedding provider based on configuration."""
    settings = settings or get_settings()
    provider = settings.embedding_provider.lower()

    if provider == "ollama":
        return OllamaEmbeddingProvider(settings)

    raise ValueError(f"Unsupported embedding provider: {provider}")
