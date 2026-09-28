"""Async Ollama LLM client with retries and structured output."""

from __future__ import annotations

import json
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.ai.output_parser import parse_with_repair
from app.core.config import Settings, get_settings
from app.core.constants import (
    OLLAMA_MAX_RETRIES,
    OLLAMA_RETRY_MAX_WAIT_SECONDS,
    OLLAMA_RETRY_MIN_WAIT_SECONDS,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

DEFAULT_SYSTEM_PROMPT = (
    "You are a precise data extraction assistant. "
    "Return valid JSON only. No markdown. No extra text."
)

# Per-agent decode caps (keep schemas satisfied without 2048→8192 escalation).
NUM_PREDICT_CRAWLER = 512
NUM_PREDICT_BUSINESS = 384
NUM_PREDICT_PAIN_POINTS = 1536
NUM_PREDICT_RECOMMENDATIONS = 1024
NUM_PREDICT_EMAIL = 768
NUM_PREDICT_REPAIR = 768


def _is_retriable_http_error(exc: BaseException) -> bool:
    """Retry timeouts and transient HTTP errors; never retry 404."""
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 404:
            return False
        return status >= 500 or status == 429
    if isinstance(exc, httpx.HTTPError):
        return True
    return False


class OllamaClient:
    """Async client for Ollama generate API (compatible with remote GPU tunnels)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.base_url = self.settings.ollama_base_url.rstrip("/")
        self.model = self.settings.ollama_model
        self.timeout = self.settings.ollama_timeout_seconds
        self._client: httpx.AsyncClient | None = None
        self._client_loop_id: int | None = None
        # Prefer /api/generate for remote tunnels; fall back to /api/chat on 404.
        self._api_mode: str = "generate"

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=30.0,
            read=float(self.timeout),
            write=30.0,
            pool=30.0,
        )

    def _client_headers(self) -> dict[str, str]:
        # Avoid ngrok free-tier browser interstitial on remote tunnels.
        return {"ngrok-skip-browser-warning": "true"}

    async def _get_client(self) -> httpx.AsyncClient:
        """Return an AsyncClient bound to the current event loop."""
        import asyncio

        loop = asyncio.get_running_loop()
        loop_id = id(loop)
        stale = (
            self._client is not None
            and (
                self._client.is_closed
                or getattr(self, "_client_loop_id", None) != loop_id
                or loop.is_closed()
            )
        )
        if stale:
            try:
                if self._client is not None and not self._client.is_closed:
                    await self._client.aclose()
            except Exception:
                pass
            self._client = None
            self._client_loop_id = None
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self._timeout(),
                headers=self._client_headers(),
            )
            self._client_loop_id = loop_id
        return self._client

    async def aclose(self) -> None:
        """Close the shared HTTP client (must be called before asyncio.run ends)."""
        if self._client is not None:
            try:
                if not self._client.is_closed:
                    await self._client.aclose()
            except Exception:
                pass
        self._client = None
        self._client_loop_id = None

    def _generate_url(self) -> str:
        return f"{self.base_url}/api/generate"

    def _chat_url(self) -> str:
        return f"{self.base_url}/api/chat"

    def _build_prompt(self, prompt: str, system: str | None) -> str:
        system_text = (system or DEFAULT_SYSTEM_PROMPT).strip()
        return f"{system_text}\n\n{prompt}".strip()

    @retry(
        retry=retry_if_exception(_is_retriable_http_error),
        stop=stop_after_attempt(OLLAMA_MAX_RETRIES),
        wait=wait_exponential(
            multiplier=1,
            min=OLLAMA_RETRY_MIN_WAIT_SECONDS,
            max=OLLAMA_RETRY_MAX_WAIT_SECONDS,
        ),
        reraise=True,
    )
    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        format_json: bool = True,
        num_predict: int | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Generate text via /api/generate or /api/chat (whichever works)."""
        client = await self._get_client()
        options = {
            "num_predict": num_predict or self.settings.ollama_num_predict,
            "temperature": 0.1,
        }

        order = (
            ("generate", "chat")
            if self._api_mode == "generate"
            else ("chat", "generate")
        )
        last_404: httpx.Response | None = None

        for mode in order:
            if mode == "generate":
                payload: dict[str, Any] = {
                    "model": self.model,
                    "prompt": self._build_prompt(prompt, system),
                    "stream": False,
                    "options": options,
                }
                if format_json:
                    payload["format"] = "json"
                response = await client.post(self._generate_url(), json=payload)
                if response.status_code == 404:
                    last_404 = response
                    logger.warning(
                        "Ollama /api/generate returned 404; trying /api/chat",
                        extra={"base_url": self.base_url},
                    )
                    continue
                response.raise_for_status()
                self._api_mode = "generate"
                data = response.json()
                content = data.get("response", "") or ""
                token_usage = {
                    "prompt_tokens": data.get("prompt_eval_count", 0),
                    "completion_tokens": data.get("eval_count", 0),
                    "model": self.model,
                }
                logger.debug("Ollama generation complete", extra={"token_usage": token_usage})
                return content, token_usage

            messages: list[dict[str, str]] = []
            if system:
                messages.append({"role": "system", "content": system})
            else:
                messages.append({"role": "system", "content": DEFAULT_SYSTEM_PROMPT})
            messages.append({"role": "user", "content": prompt})
            chat_payload: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": options,
            }
            if format_json:
                chat_payload["format"] = "json"
            response = await client.post(self._chat_url(), json=chat_payload)
            if response.status_code == 404:
                last_404 = response
                logger.warning(
                    "Ollama /api/chat returned 404; trying /api/generate",
                    extra={"base_url": self.base_url},
                )
                continue
            response.raise_for_status()
            self._api_mode = "chat"
            data = response.json()
            content = data.get("message", {}).get("content", "") or ""
            token_usage = {
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
                "model": self.model,
            }
            logger.debug("Ollama chat complete", extra={"token_usage": token_usage})
            return content, token_usage

        body_preview = ((last_404.text if last_404 else "") or "")[:180].replace("\n", " ")
        hint = ""
        if "<html" in body_preview.lower() or "<!doctype" in body_preview.lower():
            hint = (
                " Remote URL returned an HTML 404 page — the ngrok/Ollama tunnel "
                "is likely offline or OLLAMA_REMOTE_URL is wrong."
            )
        request = last_404.request if last_404 is not None else httpx.Request("POST", self._chat_url())
        response = last_404 or httpx.Response(404, request=request)
        raise httpx.HTTPStatusError(
            f"Ollama API unavailable on {self.base_url} (/api/generate and /api/chat).{hint} "
            f"body={body_preview!r}",
            request=request,
            response=response,
        )

    async def _repair_json(self, invalid_content: str, schema: type[T]) -> str:
        """Ask Ollama to repair invalid JSON output."""
        schema_json = json.dumps(schema.model_json_schema(), indent=2)
        repair_prompt = (
            "The following JSON is invalid or does not match the required schema.\n"
            f"Required schema:\n{schema_json}\n\n"
            f"Invalid output:\n{invalid_content}\n\n"
            "Return corrected JSON only. No markdown. No explanation."
        )
        content, _ = await self.generate(
            repair_prompt,
            system=DEFAULT_SYSTEM_PROMPT,
            format_json=True,
            num_predict=NUM_PREDICT_REPAIR,
        )
        return content

    def _salvage_array_key(self, schema: type[T]) -> str | None:
        """Return the preferred list field to salvage when JSON is truncated."""
        json_schema = schema.model_json_schema()
        properties = json_schema.get("properties") or {}
        # Prefer the primary domain array over secondary ones (e.g. chatbot_gaps).
        for preferred in ("pain_points", "recommendations", "gaps"):
            prop = properties.get(preferred)
            if isinstance(prop, dict) and prop.get("type") == "array":
                return preferred
        for name, prop in properties.items():
            if isinstance(prop, dict) and prop.get("type") == "array":
                return name
        return None

    async def generate_json(
        self,
        prompt: str,
        schema: type[T],
        *,
        system: str | None = None,
        num_predict: int | None = None,
    ) -> tuple[T, dict[str, Any]]:
        """Generate and parse structured JSON output with limited truncation retries."""
        from pydantic import ValidationError

        system_prompt = system or DEFAULT_SYSTEM_PROMPT
        base_predict = num_predict or self.settings.ollama_num_predict
        # Cap escalation: at most 2x base (not 4x → 8192).
        max_predict = min(max(base_predict * 2, base_predict), max(base_predict * 2, 2048))
        current_predict = base_predict
        salvage_key = self._salvage_array_key(schema)
        content = ""
        token_usage: dict[str, Any] = {}

        async def repair_fn(text: str) -> str:
            return await self._repair_json(text, schema)

        while current_predict <= max_predict:
            content, token_usage = await self.generate(
                prompt,
                system=system_prompt,
                format_json=True,
                num_predict=current_predict,
            )
            truncated = token_usage.get("completion_tokens", 0) >= current_predict

            try:
                parsed = await parse_with_repair(
                    content,
                    schema,
                    repair_fn,
                    salvage_array_key=salvage_key,
                )
                if not truncated or current_predict >= max_predict:
                    return parsed, token_usage
            except (json.JSONDecodeError, ValidationError):
                if current_predict >= max_predict:
                    raise

            next_predict = min(current_predict * 2, max_predict)
            if next_predict <= current_predict:
                break
            logger.warning(
                "Ollama output truncated or invalid; retrying with higher token limit",
                extra={
                    "num_predict": current_predict,
                    "completion_tokens": token_usage.get("completion_tokens"),
                },
            )
            current_predict = next_predict

        raise json.JSONDecodeError("Failed to parse Ollama JSON output", content, 0)
