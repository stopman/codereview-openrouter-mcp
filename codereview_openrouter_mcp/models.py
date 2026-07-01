from copy import deepcopy

MODELS: dict[str, str] = {
    "gemini": "google/gemini-3.5-flash",
    "openai": "openai/gpt-5.3-codex",
    "claude": "anthropic/claude-opus-4.8",
    "grok": "x-ai/grok-4.3",
}

DEFAULT_MODEL = "gemini"

# Models to use when model="all" for parallel multi-model review. Each fills a
# distinct persona slot (see PERSONA_MAP): Gemini=architect, GPT-5.3=detail,
# Opus=simplicity, Grok=pragmatist. All four are US-hosted and ZDR-routable on
# OpenRouter, which is required because the client sends provider.zdr=true by
# default (see client._privacy_provider) — a model with no ZDR endpoint
# hard-fails routing. The prior non-US members (DeepSeek, Kimi, GLM) and the
# Fusion meta-router were removed entirely.
# Caveat: Opus 4.8 is the priciest and slowest member, so in the min_results=3
# latency race it is the most likely straggler to be cancelled; it earns its
# place on the quality of the reviews it does land. Grok 4.3 is cheap and fast,
# which keeps the race fair.
ALL_REVIEW_MODELS = ["gemini", "openai", "claude", "grok"]

# Display names for multi-model output headers
MODEL_DISPLAY_NAMES: dict[str, str] = {
    "gemini": "Gemini 3.5 Flash",
    "openai": "GPT-5.3 Codex",
    "claude": "Claude Opus 4.8",
    "grok": "Grok 4.3",
}

# Per-model always-on request body additions. Currently none — kept as an
# extension point so a model can pin provider/plugin preferences if needed.
MODEL_EXTRA_BODY: dict[str, dict] = {}

# Per-model reasoning configuration for maximum effort via OpenRouter.
REASONING_CONFIG: dict[str, dict] = {
    "gemini": {"reasoning": {"effort": "high"}},
    "openai": {"reasoning": {"effort": "xhigh"}},
    "claude": {"reasoning": {"effort": "xhigh"}, "verbosity": "max"},
    "grok": {"reasoning": {"effort": "high"}},
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


def get_model_extra_body(name: str) -> dict:
    return deepcopy(MODEL_EXTRA_BODY.get(name, {}))
