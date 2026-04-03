from openai import AsyncOpenAI

from codereview_mcp.config import settings

_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=settings.openrouter_api_key,
)


async def get_review(content: str, system_prompt: str, model_id: str) -> str:
    response = await _client.chat.completions.create(
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
    return response.choices[0].message.content or ""
