from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from codereview_openrouter_mcp.models import MODELS, resolve_model


def test_resolve_known_models():
    assert resolve_model("gemini") == "google/gemini-3.1-pro-preview"
    assert resolve_model("openai") == "openai/gpt-5.3-codex"
    assert resolve_model("claude") == "anthropic/claude-opus-4.6"


def test_resolve_unknown_model():
    with pytest.raises(ValueError, match="Unknown model"):
        resolve_model("nonexistent")


def test_all_models_have_slash():
    """All OpenRouter model IDs must contain a slash (provider/model)."""
    for name, model_id in MODELS.items():
        assert "/" in model_id, f"Model '{name}' has invalid ID: {model_id}"


# --- Client error sanitization tests ---


@pytest.mark.asyncio
async def test_client_error_does_not_leak_api_details():
    """API errors should return sanitized messages without raw exception details."""
    from codereview_openrouter_mcp.client import get_review

    sensitive_detail = "sk-ant-api03-secret-key-leaked-in-error"
    mock_response = MagicMock()
    mock_response.status_code = 500
    error = openai.APIStatusError(
        message=f"Internal error with key {sensitive_detail}",
        response=mock_response,
        body=None,
    )

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=error)

    with patch("codereview_openrouter_mcp.client._get_client", return_value=mock_client):
        result = await get_review("test content", "system prompt", "google/gemini-3.1-pro-preview")

    assert sensitive_detail not in result, f"Sensitive detail leaked in error: {result}"
    assert "Error" in result


# --- Retry tests ---


def _make_api_status_error(status_code: int, message: str = "error") -> openai.APIStatusError:
    mock_response = MagicMock()
    mock_response.status_code = status_code
    return openai.APIStatusError(message=message, response=mock_response, body=None)


def _make_success_response(content: str = "LGTM") -> MagicMock:
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


@pytest.mark.asyncio
async def test_get_review_retries_on_429():
    """Should retry on 429 and eventually succeed."""
    from codereview_openrouter_mcp.client import get_review

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=[
            _make_api_status_error(429, "rate limited"),
            _make_api_status_error(429, "rate limited"),
            _make_success_response("review result"),
        ]
    )

    with (
        patch("codereview_openrouter_mcp.client._get_client", return_value=mock_client),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await get_review("code", "system", "google/gemini-3.1-pro-preview")

    assert result == "review result"
    assert mock_client.chat.completions.create.call_count == 3


@pytest.mark.asyncio
async def test_get_review_retries_on_502():
    """Should retry on 502 and eventually succeed."""
    from codereview_openrouter_mcp.client import get_review

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=[
            _make_api_status_error(502, "bad gateway"),
            _make_success_response("ok"),
        ]
    )

    with (
        patch("codereview_openrouter_mcp.client._get_client", return_value=mock_client),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await get_review("code", "system", "google/gemini-3.1-pro-preview")

    assert result == "ok"
    assert mock_client.chat.completions.create.call_count == 2


@pytest.mark.asyncio
async def test_get_review_no_retry_on_401():
    """Should NOT retry on 401 (auth error)."""
    from codereview_openrouter_mcp.client import get_review

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=_make_api_status_error(401, "unauthorized")
    )

    with (
        patch("codereview_openrouter_mcp.client._get_client", return_value=mock_client),
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        result = await get_review("code", "system", "google/gemini-3.1-pro-preview")

    assert "Error" in result
    assert mock_client.chat.completions.create.call_count == 1
    mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_get_review_exhausts_retries():
    """Should return error after max retries exhausted."""
    from codereview_openrouter_mcp.client import get_review

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=_make_api_status_error(503, "unavailable")
    )

    with (
        patch("codereview_openrouter_mcp.client._get_client", return_value=mock_client),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await get_review("code", "system", "google/gemini-3.1-pro-preview")

    assert "Error" in result
    # Should have tried 1 initial + 3 retries = 4 calls total
    assert mock_client.chat.completions.create.call_count == 4
