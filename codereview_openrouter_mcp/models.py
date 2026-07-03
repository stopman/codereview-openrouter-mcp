from copy import deepcopy

MODELS: dict[str, str] = {
    "gemini": "google/gemini-3.5-flash",
    "openai": "openai/gpt-5.3-codex",
    "claude": "anthropic/claude-fable-5",
    "opus": "anthropic/claude-opus-4.8",
}

DEFAULT_MODEL = "gemini"

# Models to use when model="all" for parallel multi-model review. Each fills a
# distinct persona slot (see PERSONA_MAP): Gemini=architect, GPT-5.3=detail,
# Fable=simplicity, Opus=pragmatist (production + security). All four are
# US-hosted. The client sends provider.zdr=true by default (see
# client._privacy_provider), and a model with no ZDR endpoint hard-fails
# routing — Fable 5 has no ZDR endpoint on OpenRouter yet, so its slot pins
# provider.zdr=false via MODEL_EXTRA_BODY; drop that pin once OpenRouter adds
# one. The prior non-US members (DeepSeek, Kimi, GLM) and the Fusion
# meta-router were removed entirely; Grok 4.3 was later replaced by Opus 4.8
# because Fable 5's dual-use safety measures make it decline security-focused
# review work, so the panel needs a member that owns security.
# model="all" waits for every member; a member that errors out is covered by
# its FALLBACK_MODELS entry so no persona goes missing. Caveat: Fable 5
# ($10/M in, $50/M out) and Opus 4.8 ($5/M in, $25/M out) are the priciest,
# slowest members, and panel wall-clock time is set by the slowest reviewer.
ALL_REVIEW_MODELS = ["gemini", "openai", "claude", "opus"]

# Fallback for each panel slot when its primary model errors out. Cross-vendor
# so a provider outage doesn't take primary and fallback down together; both
# fallbacks are cheap, fast, and ZDR-routable. Fallback runs send no per-model
# extra body (no reasoning tuning, no provider pins) so they always get the
# client's full default privacy routing.
FALLBACK_MODELS: dict[str, str] = {
    "gemini": "anthropic/claude-haiku-4.5",
    "openai": "anthropic/claude-haiku-4.5",
    "claude": "google/gemini-3.5-flash",
    "opus": "google/gemini-3.5-flash",
}

# Display names for fallback model ids (keyed by id, unlike
# MODEL_DISPLAY_NAMES which is keyed by panel slot name).
FALLBACK_DISPLAY_NAMES: dict[str, str] = {
    "anthropic/claude-haiku-4.5": "Claude Haiku 4.5",
    "google/gemini-3.5-flash": "Gemini 3.5 Flash",
}

# Display names for multi-model output headers
MODEL_DISPLAY_NAMES: dict[str, str] = {
    "gemini": "Gemini 3.5 Flash",
    "openai": "GPT-5.3 Codex",
    "claude": "Claude Fable 5",
    "opus": "Claude Opus 4.8",
}

# Per-model always-on request body additions. Fable 5 pins provider.zdr=false
# because it has no Zero-Data-Retention endpoint on OpenRouter yet, and the
# client's default zdr=true would hard-fail routing for it. The immutable
# data_collection="deny" floor still applies (see client._merge_extra_body),
# so providers may not collect or train on our code — they just aren't held
# to zero retention for this one slot. Remove the pin once OpenRouter lists a
# ZDR endpoint for Fable 5.
MODEL_EXTRA_BODY: dict[str, dict] = {
    "claude": {"provider": {"zdr": False}},
}

# Per-model reasoning configuration for maximum effort via OpenRouter.
REASONING_CONFIG: dict[str, dict] = {
    "gemini": {"reasoning": {"effort": "high"}},
    "openai": {"reasoning": {"effort": "xhigh"}},
    "claude": {"reasoning": {"effort": "xhigh"}, "verbosity": "max"},
    "opus": {"reasoning": {"effort": "xhigh"}, "verbosity": "max"},
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
