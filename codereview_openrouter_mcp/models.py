from copy import deepcopy

MODELS: dict[str, str] = {
    "gemini": "google/gemini-3.5-flash",
    "openai": "openai/gpt-5.3-codex",
    "claude": "anthropic/claude-opus-4.8",
    "deepseek": "deepseek/deepseek-v4-pro",
    "qwen": "qwen/qwen3.7-max",
    "kimi": "moonshotai/kimi-k2.6",
    "glm": "z-ai/glm-5.2",
    "fusion": "openrouter/fusion",
}

DEFAULT_MODEL = "gemini"

# Models to use when model="all" for parallel multi-model review.
# All four are fast single models so the latency race is fair (the slowest
# straggler is dropped by min_results). GLM-5.2 fills the pragmatist persona
# slot (see PERSONA_MAP). Fusion is intentionally excluded from the panel:
# it is itself a multi-model deliberation, so it is structurally the slowest
# member and would almost always be the one cancelled — wasting a composite
# call while rarely contributing a review. It remains available via
# model="fusion".
ALL_REVIEW_MODELS = ["gemini", "openai", "qwen", "glm"]

# Display names for multi-model output headers
MODEL_DISPLAY_NAMES: dict[str, str] = {
    "gemini": "Gemini 3.5 Flash",
    "openai": "GPT-5.3 Codex",
    "claude": "Claude Opus 4.8",
    "deepseek": "DeepSeek V4 Pro",
    "qwen": "Qwen3.7 Max",
    "kimi": "Kimi K2.6",
    "glm": "GLM-5.2",
    "fusion": "Fusion (Budget)",
}

# Per-model always-on request body additions.
# `fusion` is configured to use the curated budget panel via preset slug.
MODEL_EXTRA_BODY: dict[str, dict] = {
    "fusion": {
        "plugins": [
            {
                "id": "fusion",
                "preset": "general-budget",
            },
        ],
    },
}

# Per-model reasoning configuration for maximum effort via OpenRouter.
REASONING_CONFIG: dict[str, dict] = {
    "gemini": {"reasoning": {"effort": "high"}},
    "openai": {"reasoning": {"effort": "xhigh"}},
    "claude": {"reasoning": {"effort": "xhigh"}, "verbosity": "max"},
    "deepseek": {"reasoning": {"enabled": True}},
    "qwen": {"reasoning": {"enabled": True}},
    "kimi": {"reasoning": {"enabled": True}},
    "glm": {"reasoning": {"enabled": True}},
    "fusion": {"reasoning": {"enabled": True}},
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
