"""Pydantic schemas for agent LLM outputs."""

from typing import Literal

from pydantic import BaseModel, Field


class CrawlerAnalysisOutput(BaseModel):
    """Output schema for crawler analysis."""

    summary: str
    primary_topics: list[str] = Field(default_factory=list)
    content_quality: str = "medium"
    notable_elements: list[str] = Field(default_factory=list)


class BusinessProfileOutput(BaseModel):
    """Structured business profile from website crawl."""

    industry: str = ""
    services: list[str] = Field(default_factory=list)
    target_audience: str = ""
    value_proposition: str = ""
    confidence: float = 0.5
    evidence_urls: list[str] = Field(default_factory=list)


# Backward-compatible alias
BusinessAnalysisOutput = BusinessProfileOutput


class PainPointOutput(BaseModel):
    """Single website pain point with evidence."""

    category: Literal["seo", "trust", "conversion", "content"]
    severity: Literal["low", "medium", "high", "critical"]
    description: str
    evidence: dict = Field(default_factory=dict)


class PainPointsOutput(BaseModel):
    """Output schema for pain points."""

    pain_points: list[PainPointOutput] = Field(default_factory=list)


class ChatbotGapOutput(BaseModel):
    """Single chatbot-related gap from LLM assessment."""

    check: str
    severity: Literal["low", "medium", "high", "critical"]
    description: str
    page_url: str = "site-wide"


class ChatbotAssessmentOutput(BaseModel):
    """LLM assessment of chatbot design and response readiness."""

    design_rating: Literal["good", "fair", "poor"]
    response_readiness: Literal["good", "fair", "poor"]
    design_notes: str
    response_notes: str
    gaps: list[ChatbotGapOutput] = Field(default_factory=list)


class PainPointsBundleOutput(BaseModel):
    """Pain points plus optional chatbot assessment in one LLM call."""

    pain_points: list[PainPointOutput] = Field(default_factory=list)
    design_rating: Literal["good", "fair", "poor"] | None = None
    response_readiness: Literal["good", "fair", "poor"] | None = None
    design_notes: str = ""
    response_notes: str = ""
    chatbot_gaps: list[ChatbotGapOutput] = Field(default_factory=list)


# Backward-compatible alias
PainPointItem = PainPointOutput


class RecommendationOutput(BaseModel):
    """Single actionable recommendation."""

    problem: str
    fix: str
    expected_benefit: str
    priority: Literal["low", "medium", "high"] = "medium"
    source_check: str = ""


class RecommendationsOutput(BaseModel):
    """Output schema for recommendations."""

    recommendations: list[RecommendationOutput] = Field(default_factory=list)


# Backward-compatible alias
RecommendationItem = RecommendationOutput


class EmailOutput(BaseModel):
    """Generated outreach email draft."""

    subject: str
    body: str


# Backward-compatible alias
EmailDraftOutput = EmailOutput
