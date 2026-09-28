"""Application settings tests."""

from app.core.config import Settings, rewrite_mongodb_uri_for_docker


def test_ollama_base_url_uses_local_by_default() -> None:
    settings = Settings(
        OLLAMA_USE_REMOTE=False,
        OLLAMA_LOCAL_URL="http://localhost:11434",
        OLLAMA_REMOTE_URL="https://providing-race-reenact.ngrok-free.dev",
    )
    assert settings.ollama_base_url == "http://localhost:11434"


def test_ollama_base_url_uses_remote_when_enabled() -> None:
    settings = Settings(
        OLLAMA_USE_REMOTE=True,
        OLLAMA_LOCAL_URL="http://localhost:11434",
        OLLAMA_REMOTE_URL="https://providing-race-reenact.ngrok-free.dev",
    )
    assert settings.ollama_base_url == "https://providing-race-reenact.ngrok-free.dev"


def test_rewrite_mongodb_uri_leaves_localhost_on_host() -> None:
    uri = "mongodb://localhost:27017/web_intelligence"
    assert rewrite_mongodb_uri_for_docker(uri, in_docker=False) == uri


def test_rewrite_mongodb_uri_swaps_localhost_in_docker() -> None:
    uri = "mongodb://localhost:27017/web_intelligence"
    assert (
        rewrite_mongodb_uri_for_docker(uri, in_docker=True)
        == "mongodb://host.docker.internal:27017/web_intelligence"
    )


def test_rewrite_mongodb_uri_swaps_loopback_in_docker() -> None:
    uri = "mongodb://127.0.0.1:27017/web_intelligence"
    assert (
        rewrite_mongodb_uri_for_docker(uri, in_docker=True)
        == "mongodb://host.docker.internal:27017/web_intelligence"
    )


def test_rewrite_mongodb_uri_preserves_non_local_hosts() -> None:
    uri = "mongodb://mongo.example.com:27017/web_intelligence"
    assert rewrite_mongodb_uri_for_docker(uri, in_docker=True) == uri


def test_settings_keeps_localhost_mongodb_without_in_docker() -> None:
    settings = Settings(
        MONGODB_URI="mongodb://localhost:27017/web_intelligence",
        IN_DOCKER=False,
    )
    assert settings.mongodb_uri == "mongodb://localhost:27017/web_intelligence"


def test_settings_rewrites_mongodb_when_in_docker() -> None:
    settings = Settings(
        MONGODB_URI="mongodb://localhost:27017/web_intelligence",
        IN_DOCKER="1",
    )
    assert settings.in_docker is True
    assert settings.mongodb_uri == "mongodb://host.docker.internal:27017/web_intelligence"


def test_proxy_url_none_when_disabled() -> None:
    settings = Settings(
        PROXY_ENABLED=False,
        PROXY_HOST="p.webshare.io",
        PROXY_PORT=80,
        PROXY_USERNAME="user",
        PROXY_PASSWORD="pass",
    )
    assert settings.proxy_url is None


def test_proxy_url_built_when_enabled() -> None:
    settings = Settings(
        PROXY_ENABLED="true",
        PROXY_HOST="p.webshare.io",
        PROXY_PORT=80,
        PROXY_USERNAME="qeptcpar-rotate",
        PROXY_PASSWORD="btwwtm8mb2b6",
    )
    assert settings.proxy_enabled is True
    assert settings.proxy_url == "http://qeptcpar-rotate:btwwtm8mb2b6@p.webshare.io:80"
