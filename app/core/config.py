"""Application configuration via environment variables."""

from functools import lru_cache
from urllib.parse import quote, urlparse, urlunparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _truthy_env(value: str | bool | None) -> bool:
    """Return True for common truthy env representations."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def rewrite_mongodb_uri_for_docker(uri: str, *, in_docker: bool) -> str:
    """Rewrite localhost/127.0.0.1 to host.docker.internal when running in Docker.

    Containers cannot reach the host mongod via localhost; host.docker.internal
    points at the same host DB defined in .env (port and database name unchanged).
    """
    if not in_docker:
        return uri
    parsed = urlparse(uri)
    hostname = (parsed.hostname or "").lower()
    if hostname not in {"localhost", "127.0.0.1"}:
        return uri
    # Preserve credentials and path; only swap the host for Docker Desktop.
    port = f":{parsed.port}" if parsed.port else ""
    userinfo = ""
    if parsed.username is not None:
        userinfo = parsed.username
        if parsed.password is not None:
            userinfo += f":{parsed.password}"
        userinfo += "@"
    netloc = f"{userinfo}host.docker.internal{port}"
    return urlunparse(parsed._replace(netloc=netloc))


class Settings(BaseSettings):
    """Central application settings loaded from environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: str = Field(default="development", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    in_docker: bool = Field(default=False, alias="IN_DOCKER")

    mongodb_uri: str = Field(
        default="mongodb://localhost:27017/web_intelligence",
        alias="MONGODB_URI",
    )
    mongodb_db_name: str = Field(
        default="web_intelligence",
        alias="MONGODB_DB_NAME",
    )

    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    celery_broker_url: str = Field(
        default="redis://localhost:6379/0",
        alias="CELERY_BROKER_URL",
    )
    celery_result_backend: str = Field(
        default="redis://localhost:6379/1",
        alias="CELERY_RESULT_BACKEND",
    )

    ollama_use_remote: bool = Field(default=False, alias="OLLAMA_USE_REMOTE")
    ollama_local_url: str = Field(
        default="http://localhost:11434",
        alias="OLLAMA_LOCAL_URL",
    )
    ollama_remote_url: str = Field(
        default="https://providing-race-reenact.ngrok-free.dev",
        alias="OLLAMA_REMOTE_URL",
    )
    ollama_model: str = Field(default="llama3.2:3b", alias="OLLAMA_MODEL")
    ollama_timeout_seconds: int = Field(default=600, alias="OLLAMA_TIMEOUT_SECONDS")
    ollama_num_predict: int = Field(default=2048, alias="OLLAMA_NUM_PREDICT")

    agent_context_max_pages: int = Field(default=3, alias="AGENT_CONTEXT_MAX_PAGES")
    agent_context_max_chars_per_page: int = Field(
        default=1200,
        alias="AGENT_CONTEXT_MAX_CHARS_PER_PAGE",
    )

    qdrant_url: str = Field(default="http://localhost:6333", alias="QDRANT_URL")
    qdrant_api_key: str | None = Field(default=None, alias="QDRANT_API_KEY")

    embedding_provider: str = Field(default="ollama", alias="EMBEDDING_PROVIDER")
    embedding_model: str = Field(default="nomic-embed-text", alias="EMBEDDING_MODEL")

    crawler_max_pages: int = Field(default=5, alias="CRAWLER_MAX_PAGES")
    crawler_timeout_seconds: int = Field(default=30, alias="CRAWLER_TIMEOUT_SECONDS")
    crawler_concurrency: int = Field(default=3, alias="CRAWLER_CONCURRENCY")
    use_webclaw_fallback: bool = Field(default=True, alias="USE_WEBCLAW_FALLBACK")
    colly_url: str = Field(default="http://localhost:8081", alias="COLLY_URL")
    colly_timeout_seconds: int = Field(default=20, alias="COLLY_TIMEOUT_SECONDS")
    webclaw_base_url: str = Field(default="http://localhost:3010", alias="WEBCLAW_BASE_URL")
    crawler_max_retries: int = Field(default=3, alias="CRAWLER_MAX_RETRIES")
    crawler_retry_backoff_seconds: float = Field(default=2.0, alias="CRAWLER_RETRY_BACKOFF_SECONDS")
    crawler_respect_robots_txt: bool = Field(default=True, alias="CRAWLER_RESPECT_ROBOTS_TXT")
    crawler_min_html_length: int = Field(default=500, alias="CRAWLER_MIN_HTML_LENGTH")

    proxy_enabled: bool = Field(default=False, alias="PROXY_ENABLED")
    proxy_host: str = Field(default="p.webshare.io", alias="PROXY_HOST")
    proxy_port: int = Field(default=80, alias="PROXY_PORT")
    proxy_username: str | None = Field(default=None, alias="PROXY_USERNAME")
    proxy_password: str | None = Field(default=None, alias="PROXY_PASSWORD")

    default_user_email: str = Field(
        default="admin@example.com",
        alias="DEFAULT_USER_EMAIL",
    )
    default_user_name: str = Field(default="Default Admin", alias="DEFAULT_USER_NAME")

    queue_workers: int = Field(default=5, alias="QUEUE_WORKERS")
    max_retries: int = Field(default=3, alias="MAX_RETRIES")
    queue_batch_size: int = Field(default=100, alias="QUEUE_BATCH_SIZE")
    queue_poll_interval_seconds: float = Field(default=2.0, alias="QUEUE_POLL_INTERVAL_SECONDS")
    queue_stale_job_seconds: int = Field(default=3600, alias="QUEUE_STALE_JOB_SECONDS")
    queue_shutdown_timeout_seconds: int = Field(
        default=300,
        alias="QUEUE_SHUTDOWN_TIMEOUT_SECONDS",
    )

    @field_validator("in_docker", "proxy_enabled", mode="before")
    @classmethod
    def _parse_truthy_bool(cls, value: object) -> bool:
        return _truthy_env(value if isinstance(value, (str, bool)) or value is None else str(value))

    @model_validator(mode="after")
    def _rewrite_mongodb_uri_in_docker(self) -> "Settings":
        self.mongodb_uri = rewrite_mongodb_uri_for_docker(
            self.mongodb_uri,
            in_docker=self.in_docker,
        )
        return self

    @property
    def is_development(self) -> bool:
        """Return True when running in development mode."""
        return self.environment.lower() in {"development", "dev", "local"}

    @property
    def ollama_base_url(self) -> str:
        """Active Ollama API base URL (local or remote, from OLLAMA_USE_REMOTE)."""
        url = self.ollama_remote_url if self.ollama_use_remote else self.ollama_local_url
        return url.rstrip("/")

    @property
    def proxy_url(self) -> str | None:
        """HTTP proxy URL for outbound crawl fetches, or None when disabled."""
        if not self.proxy_enabled:
            return None
        host = (self.proxy_host or "").strip()
        if not host:
            return None
        port = self.proxy_port or 80
        user = (self.proxy_username or "").strip()
        password = self.proxy_password or ""
        if user:
            auth = f"{quote(user, safe='')}:{quote(password, safe='')}@"
        else:
            auth = ""
        return f"http://{auth}{host}:{port}"


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
