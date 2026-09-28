"""Application constants and enums."""

from enum import StrEnum


class AuditStatus(StrEnum):
    """Lifecycle status for website audits."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    AWAITING_REVIEW = "awaiting_review"
    INVALID_SITE = "invalid_site"


class AuditRunStatus(StrEnum):
    """Status for background audit runs."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class EmailStatus(StrEnum):
    """Status for generated outreach emails."""

    DRAFT = "draft"
    APPROVED = "approved"


class AgentName(StrEnum):
    """LangGraph agent node identifiers."""

    CRAWLER = "crawler"
    BUSINESS_ANALYSIS = "business_analysis"
    PAIN_POINTS = "pain_points"
    IMPACT_SCORING = "impact_scoring"
    RECOMMENDATIONS = "recommendations"
    EMAIL_WRITER = "email_writer"
    HUMAN_REVIEW = "human_review"


class AgentExecutionStatus(StrEnum):
    """Status for individual agent executions."""

    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"


class QueueJobStatus(StrEnum):
    """Status for bulk audit queue jobs."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"


class QueueBatchStatus(StrEnum):
    """Status for bulk audit queue batches."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class QdrantCollection(StrEnum):
    """Qdrant collection names."""

    WEBSITE_CONTENT = "website_content"
    AUDIT_HISTORY = "audit_history"


# Retry and timeout defaults
OLLAMA_MAX_RETRIES = 3
OLLAMA_RETRY_MIN_WAIT_SECONDS = 1
OLLAMA_RETRY_MAX_WAIT_SECONDS = 10

DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 50
