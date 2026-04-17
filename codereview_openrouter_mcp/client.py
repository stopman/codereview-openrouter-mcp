import asyncio
import random

import openai
from openai import AsyncOpenAI

from codereview_openrouter_mcp.config import settings
from codereview_openrouter_mcp.logging import get_logger

log = get_logger("client")

_client: AsyncOpenAI | None = None

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1.0  # seconds
MAX_BACKOFF_TIME = 10.0  # max total seconds spent in backoff sleeps
REQUEST_TIMEOUT = 60.0  # per-request timeout in seconds
RETRYABLE_STATUS_CODES = {429, 502, 503, 504}


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        log.debug("Initializing OpenRouter client")
        _client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.openrouter_api_key,
            timeout=REQUEST_TIMEOUT,
        )
    return _client


def _is_retryable(error: Exception) -> bool:
    """Check if an error is transient and worth retrying."""
    if isinstance(error, openai.APIStatusError):
        return error.status_code in RETRYABLE_STATUS_CODES
    if isinstance(error, (openai.APIConnectionError, openai.APITimeoutError)):
        return True
    return False


async def get_review(
    content: str,
    system_prompt: str,
    model_id: str,
    extra_body: dict | None = None,
    max_tokens: int | None = None,
) -> str:
    client = _get_client()
    total_wait = 0.0

    for attempt in range(MAX_RETRIES + 1):
        try:
            kwargs: dict = {
                "model": model_id,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content},
                ],
                "temperature": 0.2,
                "extra_headers": {
                    "HTTP-Referer": "https://github.com/codereview-mcp",
                    "X-OpenRouter-Title": "CodeReview MCP",
                },
            }
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens
            if extra_body:
                kwargs["extra_body"] = extra_body
            log.info(
                "OpenRouter request: model=%s, temperature=%.1f, max_tokens=%s, "
                "extra_body=%s, prompt_len=%d, system_prompt_len=%d",
                model_id, kwargs["temperature"], max_tokens,
                extra_body, len(content), len(system_prompt),
            )
            response = await client.chat.completions.create(**kwargs)
            if not response.choices:
                log.warning("OpenRouter returned empty response (no choices)")
                return "Error: OpenRouter returned an empty response (no choices)."
            return response.choices[0].message.content or ""
        except (openai.APIStatusError, openai.APIConnectionError, openai.APITimeoutError) as e:
            if _is_retryable(e) and attempt < MAX_RETRIES:
                wait = min(
                    RETRY_BACKOFF_BASE * (2 ** attempt) * (0.5 + random.random() * 0.5),
                    MAX_BACKOFF_TIME - total_wait,
                )
                if wait > 0:
                    log.warning(
                        "Retryable API error (%s), retrying in %.1fs (attempt %d/%d)",
                        type(e).__name__, wait, attempt + 1, MAX_RETRIES,
                    )
                    await asyncio.sleep(wait)
                    total_wait += wait
                    continue
            status = getattr(e, "status_code", None)
            log.error("OpenRouter API error (%s, status=%s): %s", type(e).__name__, status, e)
            if status:
                return f"Error: OpenRouter API request failed (status {status}). Please try again."
            return "Error: OpenRouter API request failed. Please try again."
        except openai.APIError as e:
            log.error("OpenRouter API error: %s", e)
            return "Error: OpenRouter API request failed. Please try again."
        except Exception as e:
            log.error("Unexpected OpenRouter failure: %s", e)
            return "Error: Unexpected failure calling OpenRouter."

    return "Error: OpenRouter API request failed after retries. Please try again."
