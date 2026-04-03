import pytest

from codereview_mcp.models import MODELS, resolve_model


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
