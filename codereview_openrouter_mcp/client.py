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
RETRY_BUDGET = 10.0  # max total seconds spent retrying
RETRYABLE_STATUS_CODES = {429, 502, 503, 504}


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        log.debug("Initializing OpenRouter client")
        _client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.openrouter_api_key,
        )
    return _client


async def get_review(content: str, system_prompt: str, model_id: str) -> str:
    client = _get_client()
    log.debug("Calling OpenRouter API: model=%s, content_len=%d", model_id, len(content))

    total_wait = 0.0

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = await client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content},
                ],
                temperature=0.2,
                extra_headers={
                    "HTTP-Referer": "https://github.com/codereview-mcp",
                    "X-OpenRouter-Title": "CodeReview MCP",
                },
            )
            if not response.choices:
                log.warning("OpenRouter returned empty response (no choices)")
                return "Error: OpenRouter returned an empty response (no choices)."
            return response.choices[0].message.content or ""
        except openai.APIStatusError as e:
            if e.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES:
                wait = min(
                    RETRY_BACKOFF_BASE * (2 ** attempt) * (0.5 + random.random() * 0.5),
                    RETRY_BUDGET - total_wait,
                )
                if wait > 0:
                    log.warning(
                        "Retryable API error (status=%d), retrying in %.1fs (attempt %d/%d)",
                        e.status_code, wait, attempt + 1, MAX_RETRIES,
                    )
                    await asyncio.sleep(wait)
                    total_wait += wait
                    continue
            log.error("OpenRouter API error (status=%d): %s", e.status_code, e)
            return f"Error: OpenRouter API request failed (status {e.status_code}). Please try again."
        except openai.APIError as e:
            log.error("OpenRouter API error: %s", e)
            return "Error: OpenRouter API request failed. Please try again."
        except Exception as e:
            log.error("Unexpected OpenRouter failure: %s", e)
            return "Error: Unexpected failure calling OpenRouter."

    return "Error: OpenRouter API request failed after retries. Please try again."
