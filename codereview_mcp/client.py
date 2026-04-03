import openai
from openai import AsyncOpenAI

from codereview_mcp.config import settings

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.openrouter_api_key,
        )
    return _client


async def get_review(content: str, system_prompt: str, model_id: str) -> str:
    client = _get_client()
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
    except openai.APIError as e:
        return f"Error: OpenRouter API request failed: {e}"
    except Exception as e:
        return f"Error: Unexpected failure calling OpenRouter: {e}"
    if not response.choices:
        return "Error: OpenRouter returned an empty response (no choices)."
    return response.choices[0].message.content or ""
