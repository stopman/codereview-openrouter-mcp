MODELS: dict[str, str] = {
    "gemini": "google/gemini-3.1-pro-preview",
    "openai": "openai/gpt-5.3-codex",
    "claude": "anthropic/claude-opus-4.7",
    "deepseek": "deepseek/deepseek-v3.2-speciale",
    "kimi": "moonshotai/kimi-k2-thinking",
}

DEFAULT_MODEL = "gemini"

# Models to use when model="all" for parallel multi-model review
ALL_REVIEW_MODELS = ["gemini", "openai", "deepseek", "kimi"]

# Display names for multi-model output headers
MODEL_DISPLAY_NAMES: dict[str, str] = {
    "gemini": "Gemini 3.1 Pro",
    "openai": "GPT-5.3 Codex",
    "claude": "Claude Opus 4.7",
    "deepseek": "DeepSeek V3.2 Speciale",
    "kimi": "Kimi K2 Thinking",
}

# Per-model reasoning configuration for maximum effort via OpenRouter.
# OpenRouter normalizes the `reasoning` param across providers, but each
# provider has different capabilities:
#   - OpenAI/Codex: supports effort levels (xhigh/high/medium/low)
#   - Anthropic/Claude 4.6: uses verbosity="max" + reasoning.effort="xhigh"
#   - Gemini 3: xhigh maps down to "high" (Google's max thinkingLevel)
#   - DeepSeek: reasoning.enabled boolean toggle
#   - Kimi K2 Thinking: native reasoning model, enabled by default
REASONING_CONFIG: dict[str, dict] = {
    "gemini": {"reasoning": {"effort": "high"}},
    "openai": {"reasoning": {"effort": "xhigh"}},
    "claude": {"reasoning": {"effort": "xhigh"}, "verbosity": "max"},
    "deepseek": {"reasoning": {"enabled": True}},
    "kimi": {"reasoning": {"enabled": True}},
}


def resolve_model(name: str) -> str:
    if name == "all":
        raise ValueError("Use resolve_all_models() for model='all'")
    model_id = MODELS.get(name)
    if not model_id:
        available = ", ".join(sorted(MODELS.keys()))
        raise ValueError(f"Unknown model '{name}'. Available: {available}, all")
    return model_id


def get_reasoning_config(name: str) -> dict:
    return REASONING_CONFIG.get(name, {})
