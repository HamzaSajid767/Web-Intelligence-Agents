"""Ollama client unit tests."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.ai.ollama_client import OllamaClient, _is_retriable_http_error
from app.ai.schemas import BusinessProfileOutput
from app.core.config import Settings


@pytest.mark.asyncio
async def test_generate_json_uses_repair_on_invalid_output():
    """generate_json should repair and parse when first response is invalid."""
    client = OllamaClient()

    with patch.object(client, "generate", new_callable=AsyncMock) as mock_generate:
        mock_generate.side_effect = [
            ("not valid json", {"prompt_tokens": 1, "completion_tokens": 1, "model": "mock"}),
            (
                '{"industry": "Tech", "services": ["Consulting"], '
                '"target_audience": "SMBs", "value_proposition": "Better sites"}',
                {"prompt_tokens": 2, "completion_tokens": 2, "model": "mock"},
            ),
        ]

        result, usage = await client.generate_json("test prompt", BusinessProfileOutput)

    assert result.industry == "Tech"
    assert usage["prompt_tokens"] == 1
    assert mock_generate.call_count == 2


def test_404_is_not_retriable() -> None:
    request = httpx.Request("POST", "https://example.com/api/generate")
    response = httpx.Response(404, request=request)
    exc = httpx.HTTPStatusError("404", request=request, response=response)
    assert _is_retriable_http_error(exc) is False


def test_503_is_retriable() -> None:
    request = httpx.Request("POST", "https://example.com/api/generate")
    response = httpx.Response(503, request=request)
    exc = httpx.HTTPStatusError("503", request=request, response=response)
    assert _is_retriable_http_error(exc) is True


@pytest.mark.asyncio
async def test_generate_uses_generate_endpoint():
    settings = Settings.model_construct(
        ollama_local_url="http://localhost:11434",
        ollama_remote_url="http://remote:11434",
        ollama_use_remote=False,
        ollama_model="llama3.2:3b",
        ollama_timeout_seconds=30,
        ollama_num_predict=64,
    )
    # Force base_url via constructing then overriding
    client = OllamaClient(settings=settings)
    client.base_url = "http://ollama.test"
    client.model = "llama3.2:3b"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "response": '{"ok": true}',
        "prompt_eval_count": 3,
        "eval_count": 2,
    }

    mock_http = AsyncMock()
    mock_http.is_closed = False
    mock_http.post = AsyncMock(return_value=mock_response)
    client._client = mock_http
    client._client_loop_id = id(asyncio.get_running_loop())

    content, usage = await client.generate('{"ok":true}', format_json=True, num_predict=32)
    assert content == '{"ok": true}'
    assert usage["completion_tokens"] == 2
    called_url = mock_http.post.await_args.args[0]
    assert called_url.endswith("/api/generate")


def test_shared_client_survives_two_asyncio_run_cycles_with_aclose():
    """Closing the httpx client between asyncio.run cycles avoids Event loop is closed."""
    settings = Settings.model_construct(
        ollama_local_url="http://localhost:11434",
        ollama_remote_url="http://remote:11434",
        ollama_use_remote=False,
        ollama_model="llama3.2:3b",
        ollama_timeout_seconds=30,
        ollama_num_predict=64,
    )
    client = OllamaClient(settings=settings)
    client.base_url = "http://ollama.test"

    async def _one_call() -> str:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "response": '{"ok": true}',
            "prompt_eval_count": 1,
            "eval_count": 1,
        }
        mock_http = AsyncMock()
        mock_http.is_closed = False
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_http.aclose = AsyncMock()
        client._client = mock_http
        client._client_loop_id = id(asyncio.get_running_loop())
        content, _usage = await client.generate('{"ok":true}', format_json=True)
        await client.aclose()
        return content

    first = asyncio.run(_one_call())
    second = asyncio.run(_one_call())
    assert first == '{"ok": true}'
    assert second == '{"ok": true}'
