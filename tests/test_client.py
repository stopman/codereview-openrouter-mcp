from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from planreview_openrouter_mcp.models import MODELS, resolve_model


def test_resolve_known_models():
    assert resolve_model("sol") == "openai/gpt-5.6-sol"
    assert resolve_model("openai") == "openai/gpt-5.3-codex"
    assert resolve_model("claude") == "anthropic/claude-sonnet-5"
    assert resolve_model("opus") == "anthropic/claude-opus-4.8"


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
    from planreview_openrouter_mcp.client import get_review

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

    with patch("planreview_openrouter_mcp.client._get_client", return_value=mock_client):
        result = await get_review("test content", "system prompt", "google/gemini-3.1-pro-preview")

    assert sensitive_detail not in result, f"Sensitive detail leaked in error: {result}"
    assert "Error" in result


# --- Data-privacy provider routing tests ---


async def _capture_create_kwargs(extra_body=None):
    """Run get_review against a mock and return the kwargs sent to OpenRouter."""
    from planreview_openrouter_mcp.client import get_review

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=_make_success_response())
    with patch("planreview_openrouter_mcp.client._get_client", return_value=mock_client):
        await get_review("code", "system", "google/gemini-3.5-flash", extra_body=extra_body)
    return mock_client.chat.completions.create.call_args.kwargs


@pytest.mark.asyncio
async def test_privacy_provider_always_injected():
    """Every request must deny data collection (no provider training on our data)."""
    kwargs = await _capture_create_kwargs(extra_body=None)
    provider = kwargs["extra_body"]["provider"]
    assert provider["data_collection"] == "deny"
    assert provider["zdr"] is True  # default OPENROUTER_ZDR=true


@pytest.mark.asyncio
async def test_privacy_provider_does_not_clobber_reasoning():
    """Merging the provider block must preserve caller reasoning/verbosity config."""
    extra = {"reasoning": {"effort": "xhigh"}, "verbosity": "max"}
    kwargs = await _capture_create_kwargs(extra_body=extra)
    body = kwargs["extra_body"]
    assert body["reasoning"]["effort"] == "xhigh"
    assert body["verbosity"] == "max"
    assert body["provider"]["data_collection"] == "deny"


@pytest.mark.asyncio
async def test_privacy_provider_merges_existing_provider_subkeys():
    """An existing provider sub-dict must be merged, not overwritten (CRITICAL)."""
    extra = {"provider": {"order": ["anthropic"]}}
    kwargs = await _capture_create_kwargs(extra_body=extra)
    provider = kwargs["extra_body"]["provider"]
    assert provider["order"] == ["anthropic"]  # caller key preserved
    assert provider["data_collection"] == "deny"  # privacy key still applied


@pytest.mark.asyncio
async def test_zdr_can_be_disabled_via_settings():
    """OPENROUTER_ZDR=false drops zdr but keeps data_collection=deny."""
    from planreview_openrouter_mcp import client as client_mod

    with patch.object(client_mod.settings, "require_zdr", False):
        kwargs = await _capture_create_kwargs(extra_body=None)
    provider = kwargs["extra_body"]["provider"]
    assert "zdr" not in provider
    assert provider["data_collection"] == "deny"


@pytest.mark.asyncio
async def test_caller_cannot_weaken_zdr():
    """Strict ZDR: an explicit caller provider.zdr=False must be overridden.

    There are no per-model ZDR exemptions — every panel model must be
    ZDR-routable, and the privacy block always wins the merge.
    """
    extra = {"provider": {"zdr": False}}
    kwargs = await _capture_create_kwargs(extra_body=extra)
    provider = kwargs["extra_body"]["provider"]
    assert provider["zdr"] is True  # privacy block wins; no exemptions
    assert provider["data_collection"] == "deny"


@pytest.mark.asyncio
async def test_data_collection_cannot_be_overridden():
    """data_collection='deny' is the immutable privacy floor — no caller may relax it."""
    extra = {"provider": {"data_collection": "allow"}}
    kwargs = await _capture_create_kwargs(extra_body=extra)
    assert kwargs["extra_body"]["provider"]["data_collection"] == "deny"


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
    from planreview_openrouter_mcp.client import get_review

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=[
            _make_api_status_error(429, "rate limited"),
            _make_api_status_error(429, "rate limited"),
            _make_success_response("review result"),
        ]
    )

    with (
        patch("planreview_openrouter_mcp.client._get_client", return_value=mock_client),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await get_review("code", "system", "google/gemini-3.1-pro-preview")

    assert result == "review result"
    assert mock_client.chat.completions.create.call_count == 3


@pytest.mark.asyncio
async def test_get_review_retries_on_502():
    """Should retry on 502 and eventually succeed."""
    from planreview_openrouter_mcp.client import get_review

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=[
            _make_api_status_error(502, "bad gateway"),
            _make_success_response("ok"),
        ]
    )

    with (
        patch("planreview_openrouter_mcp.client._get_client", return_value=mock_client),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await get_review("code", "system", "google/gemini-3.1-pro-preview")

    assert result == "ok"
    assert mock_client.chat.completions.create.call_count == 2


@pytest.mark.asyncio
async def test_get_review_no_retry_on_401():
    """Should NOT retry on 401 (auth error)."""
    from planreview_openrouter_mcp.client import get_review

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=_make_api_status_error(401, "unauthorized")
    )

    with (
        patch("planreview_openrouter_mcp.client._get_client", return_value=mock_client),
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        result = await get_review("code", "system", "google/gemini-3.1-pro-preview")

    assert "Error" in result
    assert mock_client.chat.completions.create.call_count == 1
    mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_get_review_retries_on_connection_error():
    """Should retry on APIConnectionError (network failure)."""
    from planreview_openrouter_mcp.client import get_review

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=[
            openai.APIConnectionError(request=MagicMock()),
            _make_success_response("recovered"),
        ]
    )

    with (
        patch("planreview_openrouter_mcp.client._get_client", return_value=mock_client),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await get_review("code", "system", "google/gemini-3.1-pro-preview")

    assert result == "recovered"
    assert mock_client.chat.completions.create.call_count == 2


@pytest.mark.asyncio
async def test_get_review_retries_on_timeout_error():
    """Should retry on APITimeoutError."""
    from planreview_openrouter_mcp.client import get_review

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=[
            openai.APITimeoutError(request=MagicMock()),
            _make_success_response("recovered"),
        ]
    )

    with (
        patch("planreview_openrouter_mcp.client._get_client", return_value=mock_client),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await get_review("code", "system", "google/gemini-3.1-pro-preview")

    assert result == "recovered"
    assert mock_client.chat.completions.create.call_count == 2


@pytest.mark.asyncio
async def test_get_review_exhausts_retries():
    """Should return error after max retries exhausted."""
    from planreview_openrouter_mcp.client import get_review

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=_make_api_status_error(503, "unavailable")
    )

    with (
        patch("planreview_openrouter_mcp.client._get_client", return_value=mock_client),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await get_review("code", "system", "google/gemini-3.1-pro-preview")

    assert "Error" in result
    # Should have tried 1 initial + 3 retries = 4 calls total
    assert mock_client.chat.completions.create.call_count == 4
