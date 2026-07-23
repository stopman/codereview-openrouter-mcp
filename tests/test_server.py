import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from planreview_openrouter_mcp.prompts import (
    PLAN_REVIEW_SYSTEM_PROMPT,
    format_plan_review_request,
)


@pytest.fixture
def mock_ctx():
    """A mock MCP Context with async report_progress."""
    ctx = MagicMock()
    ctx.report_progress = AsyncMock()
    return ctx


# --- Plan review prompt tests ---


def test_plan_review_prompt_covers_all_dimensions():
    """Plan review prompt must mention all 5 review dimensions."""
    assert "First-Principles" in PLAN_REVIEW_SYSTEM_PROMPT
    assert "KISS" in PLAN_REVIEW_SYSTEM_PROMPT
    assert "Security" in PLAN_REVIEW_SYSTEM_PROMPT
    assert "Edge Cases" in PLAN_REVIEW_SYSTEM_PROMPT
    assert "Architecture" in PLAN_REVIEW_SYSTEM_PROMPT


def test_format_plan_review_request_basic():
    result = format_plan_review_request("Add a caching layer in front of the DB")
    assert "Add a caching layer" in result
    assert "Plan to review" in result


def test_format_plan_review_request_with_context():
    result = format_plan_review_request(
        "Migrate auth to JWT",
        codebase_context="class AuthMiddleware:\n    ...",
    )
    assert "Migrate auth to JWT" in result
    assert "AuthMiddleware" in result
    assert "Codebase context" in result


def test_format_plan_review_request_no_context():
    result = format_plan_review_request("Simple plan")
    assert "Codebase context" not in result


# --- review_plan secret redaction tests ---


@pytest.mark.asyncio
async def test_review_plan_redacts_secrets_in_plan(mock_ctx):
    """review_plan must call redact_secrets on the plan text."""
    from planreview_openrouter_mcp.server import review_plan

    fake_aws_key = "AKIAIOSFODNN7EXAMPLE"
    plan_with_secret = f"Use this key: {fake_aws_key}"

    with (
        patch("planreview_openrouter_mcp.server.redact_secrets") as mock_redact,
        patch("planreview_openrouter_mcp.server.get_review", new_callable=AsyncMock, return_value="LGTM"),
    ):
        mock_redact.return_value = ("Use this key: ***", [{"type": "AWS Access Key", "line_number": 1}])
        result = await review_plan(plan=plan_with_secret, model="sol", ctx=mock_ctx)

    # redact_secrets must have been called with the plan text
    mock_redact.assert_called()
    call_args = [call.args[0] for call in mock_redact.call_args_list]
    assert any(fake_aws_key in arg for arg in call_args), "redact_secrets was not called with the plan text"
    assert "LGTM" in result


@pytest.mark.asyncio
async def test_review_plan_redacts_secrets_in_codebase_context(mock_ctx):
    """review_plan must call redact_secrets on codebase_context too."""
    from planreview_openrouter_mcp.server import review_plan

    fake_github_token = "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    context_with_secret = f'TOKEN = "{fake_github_token}"'

    with (
        patch("planreview_openrouter_mcp.server.redact_secrets") as mock_redact,
        patch("planreview_openrouter_mcp.server.get_review", new_callable=AsyncMock, return_value="LGTM"),
    ):
        # First call for plan (clean), second for codebase_context (has secret)
        mock_redact.side_effect = [
            ("clean plan", []),
            ("***", [{"type": "GitHub Token", "line_number": 1}]),
        ]
        await review_plan(plan="clean plan", codebase_context=context_with_secret, model="sol", ctx=mock_ctx)

    assert mock_redact.call_count == 2, "redact_secrets should be called for both plan and codebase_context"


@pytest.mark.asyncio
async def test_review_plan_secret_never_reaches_llm(mock_ctx):
    """Integration-style: verify a fake AWS key in the plan never appears in the prompt sent to get_review."""
    from planreview_openrouter_mcp.server import review_plan

    fake_aws_key = "AKIAIOSFODNN7EXAMPLE"
    plan_with_secret = f"Deploy with key {fake_aws_key} to prod"

    with patch("planreview_openrouter_mcp.server.get_review", new_callable=AsyncMock, return_value="LGTM") as mock_get_review:
        await review_plan(plan=plan_with_secret, model="sol", ctx=mock_ctx)

    # Check that the prompt sent to the LLM does NOT contain the raw key
    prompt_sent = mock_get_review.call_args[0][0]  # first positional arg
    assert fake_aws_key not in prompt_sent, f"Secret leaked to LLM prompt: {prompt_sent[:200]}"


# --- Model resolution tests ---


def test_resolve_model_all_known_models():
    """All model names must resolve to valid OpenRouter model IDs."""
    from planreview_openrouter_mcp.models import MODELS, resolve_model

    for name in MODELS:
        model_id = resolve_model(name)
        assert "/" in model_id, f"Model ID for '{name}' should contain a slash: {model_id}"


def test_resolve_model_opus():
    from planreview_openrouter_mcp.models import resolve_model

    assert resolve_model("opus") == "anthropic/claude-opus-4.8"


def test_resolve_model_invalid():
    from planreview_openrouter_mcp.models import resolve_model

    with pytest.raises(ValueError, match="Unknown model"):
        resolve_model("nonexistent")


def test_resolve_model_all_raises():
    """model='all' should not go through resolve_model — it's handled separately."""
    from planreview_openrouter_mcp.models import resolve_model

    with pytest.raises(ValueError, match="resolve_all_models"):
        resolve_model("all")


# --- Panel roster tests ---


def test_all_review_models_is_expected_panel():
    """Lock in the panel composition: five ZDR-routable models, one per persona.

    GPT-5.6 Sol=architect, GPT-5.3=detail, Sonnet 5=simplicity,
    Opus=pragmatist, Grok 4.5=generalist. Strict ZDR: models without a ZDR
    endpoint (Fable 5, GPT-5.5 Pro) cannot sit on the panel. DeepSeek, Kimi,
    and the Fusion meta-router remain excluded. Grok 4.5 took the generalist
    slot from GLM 5.2 on 2026-07-23 (xAI is US-based with dedicated ZDR
    endpoints, verified live); GLM 5.2 is benched but stays selectable
    explicitly. GPT-5.6 Sol replaced GPT-5.5 in the architect slot on
    2026-07-23 (same price, better indices, ZDR-verified); the old "gpt55"
    slot name is retired.
    """
    from planreview_openrouter_mcp.models import ALL_REVIEW_MODELS

    assert ALL_REVIEW_MODELS == ["sol", "openai", "claude", "opus", "grok"]


def test_claude_slot_uses_sonnet_5():
    """The claude slot runs Sonnet 5 — the newest ZDR-routable Claude.

    Fable 5 was removed under the strict-ZDR rule: it has no ZDR endpoint."""
    from planreview_openrouter_mcp.models import MODEL_DISPLAY_NAMES, MODELS

    assert MODELS["claude"] == "anthropic/claude-sonnet-5"
    assert MODEL_DISPLAY_NAMES["claude"] == "Claude Sonnet 5"


def test_no_slot_weakens_privacy_routing():
    """Strict ZDR: no panel slot may pin privacy keys (zdr / data_collection).

    Routing preferences like a provider allowlist are allowed; privacy keys
    are not — the client injects zdr=true and data_collection="deny" on top
    of every request and every panel model must be ZDR-routable outright."""
    from planreview_openrouter_mcp.models import ALL_REVIEW_MODELS, get_model_extra_body

    for name in ALL_REVIEW_MODELS:
        provider = get_model_extra_body(name).get("provider", {})
        assert "zdr" not in provider, f"'{name}' pins zdr"
        assert "data_collection" not in provider, f"'{name}' pins data_collection"


def test_glm_slot_pins_us_provider_allowlist():
    """GLM 5.2 is a Z.ai (non-US) model allowed only with US hosting:
    its slot must carry a non-empty provider.only allowlist of US-based
    hosts, and the allowlist must exclude China-based providers.

    Benched from the panel (Grok 4.5 holds the generalist slot) but still
    selectable explicitly, so the guardrails must stay intact."""
    from planreview_openrouter_mcp.models import (
        MODEL_DISPLAY_NAMES,
        MODELS,
        get_model_extra_body,
    )

    assert MODELS["glm"] == "z-ai/glm-5.2"
    assert MODEL_DISPLAY_NAMES["glm"] == "GLM 5.2"

    provider = get_model_extra_body("glm")["provider"]
    allowlist = provider["only"]
    assert allowlist, "GLM slot must pin a US provider allowlist"
    for banned in ("z-ai", "baidu", "alibaba", "siliconflow", "streamlake"):
        assert banned not in allowlist, f"non-US provider '{banned}' in GLM allowlist"

    # Preference order: try the major US hosts first (verified ZDR-qualified),
    # with the rest of the allowlist as automatic fallback.
    order = provider["order"]
    assert order[0] == "together"
    assert set(order) <= set(allowlist), "order must be a subset of the allowlist"


def test_grok_slot_config():
    """Grok 4.5 holds the generalist panel slot (replaced GLM 5.2, 2026-07-23).

    xAI is US-based and serves dedicated ZDR endpoints, so no provider pins
    are needed — the client's injected zdr=true routes correctly on its own.
    Grok 4.5 supports at most effort=high (no xhigh)."""
    from planreview_openrouter_mcp.models import (
        MODEL_DISPLAY_NAMES,
        MODELS,
        get_model_extra_body,
        get_reasoning_config,
    )
    from planreview_openrouter_mcp.prompts import (
        PERSONA_GENERALIST,
        PERSONA_MAP,
        get_plan_review_system_prompt,
    )

    assert MODELS["grok"] == "x-ai/grok-4.5"
    assert MODEL_DISPLAY_NAMES["grok"] == "Grok 4.5"
    assert get_model_extra_body("grok") == {}
    assert get_reasoning_config("grok") == {"reasoning": {"effort": "high"}}
    assert PERSONA_MAP["grok"] == PERSONA_GENERALIST
    assert get_plan_review_system_prompt("grok") == PLAN_REVIEW_SYSTEM_PROMPT


def test_glm_mapped_to_generalist_persona():
    """GLM 5.2 keeps the generalist prompt for explicit single-model runs,
    even while benched from the panel."""
    from planreview_openrouter_mcp.prompts import (
        PERSONA_GENERALIST,
        PERSONA_MAP,
        get_plan_review_system_prompt,
    )

    assert PERSONA_MAP["glm"] == PERSONA_GENERALIST
    assert get_plan_review_system_prompt("glm") == PLAN_REVIEW_SYSTEM_PROMPT


def test_glm_benched_from_panel_but_not_deleted():
    """GLM 5.2 must stay out of the panel roster while remaining fully
    configured as an explicit single-model option."""
    from planreview_openrouter_mcp.models import ALL_REVIEW_MODELS, MODELS, resolve_model

    assert "glm" not in ALL_REVIEW_MODELS
    assert MODELS["glm"] == "z-ai/glm-5.2"
    assert resolve_model("glm") == "z-ai/glm-5.2"


def test_removed_models_absent_from_registry():
    """Retired models must not linger anywhere in the registry as dead options."""
    from planreview_openrouter_mcp.models import (
        MODEL_DISPLAY_NAMES,
        MODELS,
        REASONING_CONFIG,
    )
    from planreview_openrouter_mcp.prompts import PERSONA_MAP

    for name in ("qwen", "deepseek", "kimi", "fusion", "gemini", "gptpro", "gpt55"):
        assert name not in MODELS, f"'{name}' still in MODELS"
        assert name not in MODEL_DISPLAY_NAMES, f"'{name}' still in MODEL_DISPLAY_NAMES"
        assert name not in REASONING_CONFIG, f"'{name}' still in REASONING_CONFIG"
        assert name not in PERSONA_MAP, f"'{name}' still in PERSONA_MAP"


def test_all_review_models_are_valid():
    """Every model in ALL_REVIEW_MODELS must exist in MODELS."""
    from planreview_openrouter_mcp.models import ALL_REVIEW_MODELS, MODELS

    for name in ALL_REVIEW_MODELS:
        assert name in MODELS, f"ALL_REVIEW_MODELS contains unknown model '{name}'"


def test_all_review_models_have_display_names():
    """Every model in ALL_REVIEW_MODELS must have a display name."""
    from planreview_openrouter_mcp.models import ALL_REVIEW_MODELS, MODEL_DISPLAY_NAMES

    for name in ALL_REVIEW_MODELS:
        assert name in MODEL_DISPLAY_NAMES, f"Missing display name for '{name}'"


# --- Reasoning config tests ---


def test_reasoning_config_exists_for_all_models():
    """Every model should have a reasoning config entry."""
    from planreview_openrouter_mcp.models import MODELS, REASONING_CONFIG

    for name in MODELS:
        assert name in REASONING_CONFIG, f"Missing REASONING_CONFIG for '{name}'"


def test_reasoning_config_openai_uses_xhigh():
    from planreview_openrouter_mcp.models import get_reasoning_config

    config = get_reasoning_config("openai")
    assert config["reasoning"]["effort"] == "xhigh"


def test_reasoning_config_claude_uses_verbosity_max():
    from planreview_openrouter_mcp.models import get_reasoning_config

    config = get_reasoning_config("claude")
    assert config["verbosity"] == "max"
    assert config["reasoning"]["effort"] == "xhigh"


def test_reasoning_config_sol_uses_max():
    """GPT-5.6 Sol supports a "max" reasoning tier above xhigh — use it."""
    from planreview_openrouter_mcp.models import get_reasoning_config

    config = get_reasoning_config("sol")
    assert config["reasoning"]["effort"] == "max"


def test_reasoning_config_opus_uses_xhigh_verbosity_max():
    from planreview_openrouter_mcp.models import get_reasoning_config

    config = get_reasoning_config("opus")
    assert config["reasoning"]["effort"] == "xhigh"
    assert config["verbosity"] == "max"


# --- Multi-model review tests ---


def _fixed_prompt_fn(prompt: str):
    """Helper: build a system_prompt_fn that returns the same prompt for every model."""
    return lambda _model_name: prompt


@pytest.mark.asyncio
async def test_multi_model_review_all_succeed():
    """model='all' waits for the whole panel: one section per panel member."""
    from planreview_openrouter_mcp.models import ALL_REVIEW_MODELS
    from planreview_openrouter_mcp.server import _do_multi_model_review

    async def fake_review(content, system_prompt, model_id, extra_body=None, max_tokens=None):
        return f"Review from {model_id}"

    with patch("planreview_openrouter_mcp.server.get_review", side_effect=fake_review):
        result = await _do_multi_model_review("test prompt", _fixed_prompt_fn("system prompt"))

    assert result.count("# Review by") == len(ALL_REVIEW_MODELS)
    assert "failed" not in result.lower()
    assert "fallback" not in result.lower()


@pytest.mark.asyncio
async def test_multi_model_review_partial_failure_uses_fallback():
    """A failed panel member's persona is covered by its fallback model.

    Opus fails, so its pragmatist slot must be re-run on the fallback
    (Gemini 3.5 Flash), the section header must disclose the substitution,
    and the warning block must record the primary failure.
    """
    from planreview_openrouter_mcp.models import ALL_REVIEW_MODELS
    from planreview_openrouter_mcp.server import _do_multi_model_review

    async def fake_review(content, system_prompt, model_id, extra_body=None, max_tokens=None):
        if "opus" in model_id:
            raise Exception("Opus is down")
        await asyncio.sleep(0.01)
        return f"Review from {model_id}"

    with patch("planreview_openrouter_mcp.server.get_review", side_effect=fake_review):
        result = await _do_multi_model_review("test prompt", _fixed_prompt_fn("system prompt"))

    # The other members still report normally
    assert "GPT-5.6 Sol" in result
    assert "GPT-5.3 Codex" in result
    assert "Claude Sonnet 5" in result
    # The pragmatist slot is covered by the fallback, disclosed in the header
    assert result.count("# Review by") == len(ALL_REVIEW_MODELS)
    assert "fallback for Claude Opus 4.8" in result
    # And the primary failure is still surfaced
    assert "failed" in result.lower() or "error" in result.lower()


@pytest.mark.asyncio
async def test_multi_model_review_all_fail():
    """If all primaries AND all fallbacks fail, return a clear error."""
    from planreview_openrouter_mcp.server import _do_multi_model_review

    async def fake_review(content, system_prompt, model_id, extra_body=None, max_tokens=None):
        raise Exception(f"{model_id} is down")

    with patch("planreview_openrouter_mcp.server.get_review", side_effect=fake_review):
        result = await _do_multi_model_review("test prompt", _fixed_prompt_fn("system prompt"))

    assert "Error: All models failed" in result


@pytest.mark.asyncio
async def test_multi_model_review_with_reasoning():
    """Reasoning config should be passed when use_reasoning=True."""
    from planreview_openrouter_mcp.models import ALL_REVIEW_MODELS
    from planreview_openrouter_mcp.server import _do_multi_model_review

    calls = []

    async def fake_review(content, system_prompt, model_id, extra_body=None, max_tokens=None):
        calls.append({"model_id": model_id, "extra_body": extra_body, "max_tokens": max_tokens})
        return f"Review from {model_id}"

    with patch("planreview_openrouter_mcp.server.get_review", side_effect=fake_review):
        await _do_multi_model_review(
            "test prompt", _fixed_prompt_fn("system prompt"),
            use_reasoning=True, max_tokens=16384,
        )

    assert len(calls) == len(ALL_REVIEW_MODELS)
    for call in calls:
        assert call["extra_body"] is not None, f"Reasoning config missing for {call['model_id']}"
        assert call["max_tokens"] == 16384


@pytest.mark.asyncio
async def test_multi_model_review_dispatches_per_model_persona():
    """When fanning out, each model should receive its own persona's system prompt."""
    from planreview_openrouter_mcp.models import ALL_REVIEW_MODELS, resolve_model
    from planreview_openrouter_mcp.prompts import get_plan_review_system_prompt
    from planreview_openrouter_mcp.server import _do_multi_model_review

    captured: dict[str, str] = {}

    async def fake_review(content, system_prompt, model_id, extra_body=None, max_tokens=None):
        captured[model_id] = system_prompt
        return f"Review from {model_id}"

    with patch("planreview_openrouter_mcp.server.get_review", side_effect=fake_review):
        await _do_multi_model_review("test prompt", get_plan_review_system_prompt)

    # Every panel member runs (no quorum cancellation) with its persona prompt.
    for name in ALL_REVIEW_MODELS:
        model_id = resolve_model(name)
        assert model_id in captured, f"Model {name} never ran"
        assert captured[model_id] == get_plan_review_system_prompt(name), (
            f"Model {name} did not receive its persona prompt"
        )


@pytest.mark.asyncio
async def test_multi_model_review_section_header_includes_persona():
    """The aggregated multi-model output should label each section with its persona."""
    from planreview_openrouter_mcp.prompts import get_plan_review_system_prompt
    from planreview_openrouter_mcp.server import _do_multi_model_review

    async def fake_review(content, system_prompt, model_id, extra_body=None, max_tokens=None):
        return f"Review from {model_id}"

    with patch("planreview_openrouter_mcp.server.get_review", side_effect=fake_review):
        result = await _do_multi_model_review("test prompt", get_plan_review_system_prompt)

    assert "persona" in result.lower()


# --- review_oracle alias tests ---


@pytest.mark.asyncio
async def test_review_oracle_works_like_review_plan(mock_ctx):
    """review_oracle should produce the same result as review_plan."""
    from planreview_openrouter_mcp.server import review_oracle, review_plan

    with patch("planreview_openrouter_mcp.server.get_review", new_callable=AsyncMock, return_value="LGTM"):
        plan_result = await review_plan(plan="Add caching layer", model="sol", ctx=mock_ctx)
        oracle_result = await review_oracle(plan="Add caching layer", model="sol", ctx=mock_ctx)

    assert plan_result == oracle_result


@pytest.mark.asyncio
async def test_review_oracle_passes_reasoning_config(mock_ctx):
    """review_oracle should pass reasoning config to get_review."""
    from planreview_openrouter_mcp.server import review_oracle

    with patch("planreview_openrouter_mcp.server.get_review", new_callable=AsyncMock, return_value="LGTM") as mock:
        await review_oracle(plan="Design a new auth system", model="openai", ctx=mock_ctx)

    _, kwargs = mock.call_args
    assert kwargs.get("extra_body") is not None
    assert kwargs["extra_body"]["reasoning"]["effort"] == "xhigh"
    assert kwargs["max_tokens"] == 16384


# --- Plan review reasoning params integration tests ---


@pytest.mark.asyncio
async def test_review_plan_passes_reasoning_and_max_tokens(mock_ctx):
    """review_plan should pass reasoning config and max_tokens to get_review."""
    from planreview_openrouter_mcp.server import review_plan

    with patch("planreview_openrouter_mcp.server.get_review", new_callable=AsyncMock, return_value="LGTM") as mock:
        await review_plan(plan="Implement caching", model="claude", ctx=mock_ctx)

    _, kwargs = mock.call_args
    assert kwargs["extra_body"]["verbosity"] == "max"
    assert kwargs["extra_body"]["reasoning"]["effort"] == "xhigh"
    assert kwargs["max_tokens"] == 16384


@pytest.mark.asyncio
async def test_review_plan_all_uses_multi_model(mock_ctx):
    """review_plan with model='all' should fan out to the panel models."""
    from planreview_openrouter_mcp.models import ALL_REVIEW_MODELS
    from planreview_openrouter_mcp.server import review_plan

    call_models = []

    async def fake_review(content, system_prompt, model_id, extra_body=None, max_tokens=None):
        call_models.append(model_id)
        return f"Review from {model_id}"

    with patch("planreview_openrouter_mcp.server.get_review", side_effect=fake_review):
        result = await review_plan(plan="Add auth", model="all", ctx=mock_ctx)

    assert len(call_models) == len(ALL_REVIEW_MODELS)
    assert "GPT-5.6 Sol" in result
    assert "GPT-5.3 Codex" in result


@pytest.mark.asyncio
async def test_review_plan_single_model_uses_persona_prompt(mock_ctx):
    """Single-model review_plan should send the per-model plan-review persona prompt."""
    from planreview_openrouter_mcp.prompts import get_plan_review_system_prompt
    from planreview_openrouter_mcp.server import review_plan

    captured = {}

    async def fake_review(content, system_prompt, model_id, extra_body=None, max_tokens=None):
        captured["system_prompt"] = system_prompt
        captured["extra_body"] = extra_body
        return "LGTM"

    with patch("planreview_openrouter_mcp.server.get_review", side_effect=fake_review):
        await review_plan(plan="Add caching layer", model="opus", ctx=mock_ctx)

    assert captured["system_prompt"] == get_plan_review_system_prompt("opus")
    # Plan reviews run with reasoning enabled — opus is configured for xhigh effort.
    assert captured["extra_body"]["reasoning"]["effort"] == "xhigh"
    assert "Pragmatist" in captured["system_prompt"] or "Production" in captured["system_prompt"]


# --- Fallback model tests ---


def test_fallback_models_cover_panel():
    """Every panel slot needs a fallback that is a different, valid model."""
    from planreview_openrouter_mcp.models import (
        ALL_REVIEW_MODELS,
        FALLBACK_MODELS,
        resolve_model,
    )

    for name in ALL_REVIEW_MODELS:
        fallback_id = FALLBACK_MODELS.get(name)
        assert fallback_id, f"No fallback configured for panel slot '{name}'"
        assert "/" in fallback_id, f"Fallback for '{name}' is not a model id: {fallback_id}"
        assert fallback_id != resolve_model(name), (
            f"Fallback for '{name}' must differ from its primary"
        )


def test_fallbacks_are_cross_vendor():
    """A slot's fallback must come from a different vendor than its primary,
    so a vendor outage can't take out both. In particular, Anthropic-backed
    slots must fall back to Gemini."""
    from planreview_openrouter_mcp.models import (
        ALL_REVIEW_MODELS,
        FALLBACK_MODELS,
        resolve_model,
    )

    for name in ALL_REVIEW_MODELS:
        primary_vendor = resolve_model(name).split("/")[0]
        fallback_vendor = FALLBACK_MODELS[name].split("/")[0]
        assert fallback_vendor != primary_vendor, (
            f"Slot '{name}' falls back within its own vendor '{primary_vendor}'"
        )
        if primary_vendor == "anthropic":
            assert fallback_vendor == "google", (
                f"Anthropic slot '{name}' must fall back to Gemini, got {FALLBACK_MODELS[name]}"
            )


@pytest.mark.asyncio
async def test_fallback_review_uses_clean_extra_body():
    """Fallback runs must not inherit the primary slot's extra_body.

    The primary's reasoning/verbosity tuning must never ride along to the
    fallback model, which runs with the full default privacy routing and
    stock parameters.
    """
    from planreview_openrouter_mcp.prompts import get_plan_review_system_prompt
    from planreview_openrouter_mcp.server import _do_multi_model_review

    calls = []

    async def fake_review(content, system_prompt, model_id, extra_body=None, max_tokens=None):
        calls.append({"model_id": model_id, "system_prompt": system_prompt, "extra_body": extra_body})
        if "sonnet-5" in model_id:
            raise Exception("Sonnet is down")
        return f"Review from {model_id}"

    with patch("planreview_openrouter_mcp.server.get_review", side_effect=fake_review):
        result = await _do_multi_model_review("test prompt", get_plan_review_system_prompt)

    assert "fallback for Claude Sonnet 5" in result
    simplicity_prompt = get_plan_review_system_prompt("claude")
    fallback_calls = [
        c for c in calls
        if c["system_prompt"] == simplicity_prompt and "sonnet-5" not in c["model_id"]
    ]
    assert len(fallback_calls) == 1, "Expected exactly one fallback run for the claude slot"
    assert fallback_calls[0]["extra_body"] is None, (
        "Fallback must run with default privacy routing, not the primary's extra_body"
    )


# --- Persona dispatch tests ---


def test_persona_map_covers_all_review_models():
    """Every model in ALL_REVIEW_MODELS must have a persona assigned."""
    from planreview_openrouter_mcp.models import ALL_REVIEW_MODELS
    from planreview_openrouter_mcp.prompts import PERSONA_MAP

    for name in ALL_REVIEW_MODELS:
        assert name in PERSONA_MAP, f"Model '{name}' has no persona assigned in PERSONA_MAP"


def test_personas_unique_across_all_review_models():
    """Each model in the multi-model panel must have a distinct persona —
    otherwise the panel returns duplicate perspectives."""
    from planreview_openrouter_mcp.models import ALL_REVIEW_MODELS
    from planreview_openrouter_mcp.prompts import PERSONA_MAP

    personas = [PERSONA_MAP[name] for name in ALL_REVIEW_MODELS]
    assert len(personas) == len(set(personas)), (
        f"Duplicate personas in ALL_REVIEW_MODELS: {personas}"
    )


def test_persona_map_assigns_expected_personas():
    """Lock in the per-model persona mapping the user requested."""
    from planreview_openrouter_mcp.prompts import (
        PERSONA_ARCHITECT,
        PERSONA_DETAIL,
        PERSONA_MAP,
        PERSONA_PRAGMATIST,
        PERSONA_SIMPLICITY,
    )

    assert PERSONA_MAP["sol"] == PERSONA_ARCHITECT
    assert PERSONA_MAP["openai"] == PERSONA_DETAIL
    assert PERSONA_MAP["claude"] == PERSONA_SIMPLICITY
    assert PERSONA_MAP["opus"] == PERSONA_PRAGMATIST


def test_claude_mapped_to_simplicity_persona():
    """Claude fills the first-principles / simplicity slot in the panel."""
    from planreview_openrouter_mcp.prompts import PERSONA_MAP, PERSONA_SIMPLICITY

    assert PERSONA_MAP["claude"] == PERSONA_SIMPLICITY


def test_get_plan_review_system_prompt_returns_persona_specific():
    """Plan-review prompts must be persona-specific."""
    from planreview_openrouter_mcp.prompts import get_plan_review_system_prompt

    architect = get_plan_review_system_prompt("sol")
    detail = get_plan_review_system_prompt("openai")
    simplicity = get_plan_review_system_prompt("claude")
    pragmatist = get_plan_review_system_prompt("opus")

    assert len({architect, detail, simplicity, pragmatist}) == 4
    assert "Architect" in architect
    assert "Detail-Oriented" in detail


def test_get_plan_review_system_prompt_unmapped_falls_back():
    from planreview_openrouter_mcp.prompts import get_plan_review_system_prompt

    assert get_plan_review_system_prompt("nonexistent_model") == PLAN_REVIEW_SYSTEM_PROMPT


def test_pragmatist_persona_covers_security():
    """Opus owns security-adjacent review: the pragmatist prompt it runs
    must explicitly cover security exposure."""
    from planreview_openrouter_mcp.prompts import PRAGMATIST_PLAN_REVIEW_SYSTEM_PROMPT

    assert "Security" in PRAGMATIST_PLAN_REVIEW_SYSTEM_PROMPT


# --- Server instructions tests ---


def test_server_has_instructions_set():
    """FastMCP server must publish instructions so MCP clients (Claude Code
    etc.) see proactive guidance on when/how to use this server."""
    from planreview_openrouter_mcp.server import mcp

    instructions = mcp.instructions
    assert instructions, "Server must publish instructions"
    assert len(instructions) > 200, "Instructions should be substantive"


def test_server_instructions_advertise_context_files():
    """Instructions must tell callers to scan for project docs and attach
    them via context_files — otherwise the feature is invisible."""
    from planreview_openrouter_mcp.server import mcp

    text = mcp.instructions.lower()
    assert "context_files" in text
    # Mentions concrete doc locations the AI should look for
    assert "architecture.md" in text or "architecture" in text
    assert "claude.md" in text or "agents.md" in text


def test_server_instructions_explain_model_all():
    """Instructions should describe what model='all' returns and that the
    caller is expected to synthesize."""
    from planreview_openrouter_mcp.server import mcp

    text = mcp.instructions.lower()
    assert 'model="all"' in text or "model='all'" in text
    assert "panel" in text


def test_server_instructions_explain_personas():
    """Instructions should name the per-model personas so the caller knows
    what each model is contributing."""
    from planreview_openrouter_mcp.server import mcp

    text = mcp.instructions.lower()
    for persona in ["architect", "detail", "simplicity", "production"]:
        assert persona in text, f"Persona '{persona}' missing from instructions"


def test_server_instructions_steer_security_to_opus():
    """Callers must be told to send security-sensitive plans to opus, whose
    persona explicitly owns security exposure."""
    from planreview_openrouter_mcp.server import mcp

    text = mcp.instructions.lower()
    assert "security" in text
    assert "opus" in text


def test_server_instructions_are_plan_only():
    """The code-review tools are gone — instructions must not advertise them."""
    from planreview_openrouter_mcp.server import mcp

    text = mcp.instructions
    for retired_tool in ("review_diff", "review_commit", "review_branch", "review_file"):
        assert retired_tool not in text, f"Retired tool '{retired_tool}' still advertised"


# --- context_files / project_docs tests ---


def test_format_plan_review_request_includes_project_docs():
    from planreview_openrouter_mcp.prompts import format_plan_review_request

    docs = '<project_context><file name="ARCH.md">\nService A → B.\n</file></project_context>'
    result = format_plan_review_request("Add caching", project_docs=docs)
    assert docs in result
    assert result.index(docs) < result.index("Add caching")


@pytest.mark.asyncio
async def test_review_plan_injects_context_files_into_prompt(mock_ctx, tmp_path):
    """review_plan must accept context_files when repo_path is supplied."""
    from planreview_openrouter_mcp.server import review_plan

    (tmp_path / "VISION.md").write_text("VISION_MARKER_99: build a cache.")

    captured = {}

    async def fake_review(content, system_prompt, model_id, extra_body=None, max_tokens=None):
        captured["content"] = content
        return "Proceed."

    with patch("planreview_openrouter_mcp.server.get_review", side_effect=fake_review):
        await review_plan(
            plan="Add an LRU cache to the user service",
            model="sol",
            repo_path=str(tmp_path),
            context_files=["VISION.md"],
            ctx=mock_ctx,
        )

    assert "VISION_MARKER_99" in captured["content"]
    assert '<file name="VISION.md">' in captured["content"]


@pytest.mark.asyncio
async def test_review_plan_redacts_secrets_in_context_files(mock_ctx, tmp_path):
    """Secrets in a context file must be redacted before being sent to the LLM."""
    from planreview_openrouter_mcp.server import review_plan

    fake_aws_key = "AKIAIOSFODNN7EXAMPLE"
    (tmp_path / "DEPLOY.md").write_text(f"Deploy with key {fake_aws_key}")

    captured = {}

    async def fake_review(content, system_prompt, model_id, extra_body=None, max_tokens=None):
        captured["content"] = content
        return "LGTM"

    with patch("planreview_openrouter_mcp.server.get_review", side_effect=fake_review):
        await review_plan(
            plan="Ship the deploy pipeline",
            model="sol",
            repo_path=str(tmp_path),
            context_files=["DEPLOY.md"],
            ctx=mock_ctx,
        )

    assert fake_aws_key not in captured["content"], "AWS key leaked from context file to LLM"


@pytest.mark.asyncio
async def test_review_plan_missing_context_file_surfaces_notice(mock_ctx, tmp_path):
    """A requested but missing context file must not silently disappear —
    a notice should reach the LLM so it knows context is incomplete."""
    from planreview_openrouter_mcp.server import review_plan

    captured = {}

    async def fake_review(content, system_prompt, model_id, extra_body=None, max_tokens=None):
        captured["content"] = content
        return "LGTM"

    with patch("planreview_openrouter_mcp.server.get_review", side_effect=fake_review):
        await review_plan(
            plan="Add caching",
            model="sol",
            repo_path=str(tmp_path),
            context_files=["ARCH_THAT_DOESNT_EXIST.md"],
            ctx=mock_ctx,
        )

    assert "<context_notice>" in captured["content"]
    assert "ARCH_THAT_DOESNT_EXIST.md" in captured["content"]
    assert "not found" in captured["content"]
