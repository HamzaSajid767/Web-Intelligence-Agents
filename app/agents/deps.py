"""Agent node dependencies container."""

from dataclasses import dataclass
from typing import Any

from app.ai.ollama_client import OllamaClient
from app.crawler.crawler_service import CrawlerService


@dataclass
class AgentDependencies:
    """Injected dependencies for agent nodes."""

    ollama: OllamaClient
    crawler: CrawlerService
    vector_retriever: Any = None
