"""Shared pytest fixtures and mocks."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.ai.schemas import (
    BusinessProfileOutput,
    ChatbotAssessmentOutput,
    CrawlerAnalysisOutput,
    EmailOutput,
    PainPointOutput,
    PainPointsBundleOutput,
    PainPointsOutput,
    RecommendationOutput,
    RecommendationsOutput,
)
from app.crawler.crawler_service import CrawlerService
from app.crawler.models import CrawlResult, PageData


class MockOllamaClient:
    """Mock Ollama client returning fixture JSON per schema type."""

    model = "mock"

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        format_json: bool = True,
    ) -> tuple[str, dict[str, Any]]:
        return ("{}", {"prompt_tokens": 10, "completion_tokens": 20, "model": "mock"})

    async def generate_json(
        self,
        prompt: str,
        schema: type,
        **kwargs: Any,
    ) -> tuple[Any, dict[str, Any]]:
        token_usage = {"prompt_tokens": 10, "completion_tokens": 20, "model": "mock"}
        if schema is CrawlerAnalysisOutput:
            return (
                CrawlerAnalysisOutput(
                    summary="Test site summary",
                    primary_topics=["services"],
                    content_quality="medium",
                ),
                token_usage,
            )
        if schema is BusinessProfileOutput:
            return (
                BusinessProfileOutput(
                    industry="Technology",
                    services=["Web Development"],
                    target_audience="SMBs",
                    value_proposition="Quality web services",
                    confidence=0.85,
                    evidence_urls=["https://example.com"],
                ),
                token_usage,
            )
        if schema is PainPointsBundleOutput:
            return (
                PainPointsBundleOutput(
                    pain_points=[
                        PainPointOutput(
                            category="seo",
                            severity="high",
                            description="Missing meta descriptions",
                            evidence={"page_url": "https://example.com"},
                        ),
                        PainPointOutput(
                            category="trust",
                            severity="medium",
                            description="No testimonials visible",
                            evidence={"page_url": "https://example.com"},
                        ),
                        PainPointOutput(
                            category="conversion",
                            severity="high",
                            description="Missing chatbot widget",
                            evidence={"page_url": "site-wide"},
                        ),
                    ]
                ),
                token_usage,
            )
        if schema is PainPointsOutput:
            return (
                PainPointsOutput(
                    pain_points=[
                        PainPointOutput(
                            category="seo",
                            severity="high",
                            description="Missing meta descriptions",
                            evidence={"page_url": "https://example.com"},
                        ),
                        PainPointOutput(
                            category="trust",
                            severity="medium",
                            description="No testimonials visible",
                            evidence={"page_url": "https://example.com"},
                        ),
                    ]
                ),
                token_usage,
            )
        if schema is ChatbotAssessmentOutput:
            return (
                ChatbotAssessmentOutput(
                    design_rating="fair",
                    response_readiness="poor",
                    design_notes="Launcher present but not prominent.",
                    response_notes="No proactive greeting detected.",
                    gaps=[],
                ),
                token_usage,
            )
        if schema is RecommendationsOutput:
            return (
                RecommendationsOutput(
                    recommendations=[
                        RecommendationOutput(
                            problem="Missing meta descriptions",
                            fix="Add unique meta descriptions to all pages",
                            expected_benefit="Improved search visibility",
                            priority="high",
                            source_check="missing_meta_description",
                        )
                    ]
                ),
                token_usage,
            )
        if schema is EmailOutput:
            return (
                EmailOutput(
                    subject="Improve your website visibility",
                    body="Hi, we noticed opportunities on your site.",
                ),
                token_usage,
            )
        raise ValueError(f"Unhandled schema: {schema}")


class MockCrawlerService:
    """Mock crawler returning static page data."""

    async def crawl(self, website_url: str) -> CrawlResult:
        return CrawlResult(
            website_url=website_url,
            pages=[
                PageData(
                    url=website_url,
                    title="Test Page",
                    clean_text=(
                        "Welcome to our business website. We provide professional services "
                        "for small and mid-sized companies including consulting, support, "
                        "and digital solutions tailored to growth-focused organizations."
                    ),
                    metadata={"description": "Test description"},
                    headings=[{"level": "h1", "text": "Welcome"}],
                    links=[],
                )
            ],
            total_pages=1,
        )

    def to_state_dict(self, crawl_result: CrawlResult) -> dict[str, Any]:
        return CrawlerService().to_state_dict(crawl_result)


class MockVectorRetriever:
    """No-op vector retriever for tests."""

    async def upsert_page_chunks(self, audit_id: str, page_url: str, clean_text: str) -> int:
        return 0

    async def store_audit_summary(self, audit_id: str, website_url: str, summary: str) -> None:
        return None

    async def search_similar_content(self, query: str, *, limit: int = 5) -> list:
        return []

    async def find_similar_audits(self, summary: str, *, limit: int = 3) -> list:
        return []


@pytest.fixture
def mock_ollama() -> MockOllamaClient:
    """Provide mock Ollama client."""
    return MockOllamaClient()


@pytest.fixture
def mock_crawler() -> MockCrawlerService:
    """Provide mock crawler."""
    return MockCrawlerService()


@pytest.fixture
def mock_vector_retriever() -> MockVectorRetriever:
    """Provide mock vector retriever."""
    return MockVectorRetriever()


@pytest.fixture
def agent_deps(mock_ollama, mock_crawler, mock_vector_retriever):
    """Provide agent dependencies with mocks."""
    from app.agents.deps import AgentDependencies

    return AgentDependencies(
        ollama=mock_ollama,
        crawler=mock_crawler,
        vector_retriever=mock_vector_retriever,
    )


@pytest.fixture
def sample_audit_state() -> dict:
    """Provide initial audit state."""
    return {
        "audit_id": str(uuid4()),
        "website_url": "https://example.com",
        "crawl_data": {},
        "business_profile": {},
        "pain_points": [],
        "seo_analysis": {},
        "chatbot_analysis": {},
        "scores": {},
        "recommendations": [],
        "email_draft": {},
        "agent_logs": [],
        "status": "running",
        "error": None,
        "current_agent": None,
    }


@pytest.fixture
def mock_job_manager():
    """Mock job manager that does not enqueue Celery tasks."""
    manager = MagicMock()
    manager.enqueue_audit.return_value = "mock-task-id"
    return manager
