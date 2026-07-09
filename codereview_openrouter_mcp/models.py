from copy import deepcopy

MODELS: dict[str, str] = {
    "gpt56": "openai/gpt-5.6-sol",
    "openai": "openai/gpt-5.3-codex",
    "claude": "anthropic/claude-sonnet-5",
    "opus": "anthropic/claude-opus-4.8",
    "glm": "z-ai/glm-5.2",
    "grok": "x-ai/grok-4.5",
}

DEFAULT_MODEL = "gpt56"

# Deprecated slot names still accepted from callers. Renaming a slot breaks
# every saved config/script that passes the old name, so upgrades keep the
# old key as an alias to the new slot instead of hard-failing.
MODEL_ALIASES: dict[str, str] = {
    "gpt55": "gpt56",  # GPT-5.5 -> GPT-5.6 Sol (2026-07-09)
}

# Models to use when model="all" for parallel multi-model review. Each fills
# a distinct persona slot (see PERSONA_MAP): GPT-5.6 Sol=architect,
# GPT-5.3=detail, Sonnet 5=simplicity, Opus=pragmatist (production +
# security), Grok 4.5=adversary (edge cases / failure injection), GLM 5.2=
# generalist. STRICT ZDR: every panel model must be ZDR-routable on
# OpenRouter — the client sends provider.zdr=true and always overrides any
# attempt to weaken it (see client._merge_extra_body), so a model with no
# ZDR endpoint hard-fails routing and cannot sit on the panel. That is why
# Claude Fable 5 is absent: it has no ZDR endpoint. DeepSeek, Kimi, and the
# Fusion meta-router remain excluded. Meta's Muse Spark 1.1 (2026-07-09) is
# a future candidate once it lands on OpenRouter with ZDR endpoints.
# GPT-5.6 Sol is the flagship tier of the 5.6 series (Terra=mid, Luna=fast);
# the Sol Pro variant (same weights, reasoning.mode=pro serving) is skipped
# to keep panel latency bounded. Grok 4.5 returned (4.3 was dropped for
# Opus 4.8) as the adversary slot, ZDR-verified 2026-07-09 and pinned to
# xAI's first-party hosting (see MODEL_EXTRA_BODY). GLM 5.2 (a Z.ai model)
# is allowed only because its slot pins a US-based provider allowlist on
# top of ZDR — verified live: OpenRouter routes it via Novita (US) under
# both constraints.
# model="all" waits for every member; a member that errors out is covered by
# its FALLBACK_MODELS entry so no persona goes missing. Panel wall-clock
# time is set by the slowest reviewer.
ALL_REVIEW_MODELS = ["gpt56", "openai", "claude", "opus", "grok", "glm"]

# Fallback for each panel slot when its primary model errors out. Cross-vendor
# so a provider outage doesn't take primary and fallback down together; both
# fallbacks are cheap, fast, and ZDR-routable. Fallback runs send no per-model
# extra body (no reasoning tuning, no provider pins) so they always get the
# client's full default privacy routing.
FALLBACK_MODELS: dict[str, str] = {
    "gpt56": "anthropic/claude-haiku-4.5",
    "openai": "anthropic/claude-haiku-4.5",
    "claude": "google/gemini-3.5-flash",
    "opus": "google/gemini-3.5-flash",
    "glm": "anthropic/claude-haiku-4.5",
    "grok": "google/gemini-3.5-flash",
}

# Display names for fallback model ids (keyed by id, unlike
# MODEL_DISPLAY_NAMES which is keyed by panel slot name).
FALLBACK_DISPLAY_NAMES: dict[str, str] = {
    "anthropic/claude-haiku-4.5": "Claude Haiku 4.5",
    "google/gemini-3.5-flash": "Gemini 3.5 Flash",
}

# Display names for multi-model output headers
MODEL_DISPLAY_NAMES: dict[str, str] = {
    "gpt56": "GPT-5.6 Sol",
    "openai": "GPT-5.3 Codex",
    "claude": "Claude Sonnet 5",
    "opus": "Claude Opus 4.8",
    "glm": "GLM 5.2",
    "grok": "Grok 4.5",
}

# Per-model always-on request body additions — an extension point for
# NON-PRIVACY provider/plugin preferences only. Privacy keys cannot be
# pinned here: client._merge_extra_body always overrides them (strict ZDR,
# no per-model exemptions), so every panel model must be ZDR-routable
# outright.
# GLM 5.2 is developed by Z.ai (non-US), so its slot restricts routing to
# US-headquartered hosting providers (per OpenRouter's provider registry)
# via provider.only; combined with the injected zdr=true this routes to
# US-based Zero-Data-Retention endpoints only.
US_GLM_PROVIDER_ALLOWLIST = [
    "deepinfra",
    "fireworks",
    "together",
    "cloudflare",
    "venice",
    "wandb",
    "parasail",
    "novita",
    "gmicloud",
    "atlas-cloud",
    "morph",
]

# Within the allowlist, prefer the major US hosts first (all verified live as
# ZDR-qualified for GLM 5.2); OpenRouter falls back to the remaining
# allowlisted ZDR endpoints automatically.
US_GLM_PROVIDER_ORDER = ["together", "fireworks", "novita"]

MODEL_EXTRA_BODY: dict[str, dict] = {
    "glm": {
        "provider": {
            "only": US_GLM_PROVIDER_ALLOWLIST,
            "order": US_GLM_PROVIDER_ORDER,
        }
    },
    # Grok 4.5 is served ZDR by xAI itself today, but pin first-party
    # hosting anyway: if a third-party Grok reseller appears on OpenRouter
    # later, review content still cannot route to it.
    "grok": {
        "provider": {
            "only": ["xai"],
        }
    },
}

# Per-model reasoning configuration for maximum effort via OpenRouter.
# The GPT slots do not support the verbosity parameter, only reasoning effort.
# Grok 4.5 caps at "high" — it rejects xhigh.
REASONING_CONFIG: dict[str, dict] = {
    "gpt56": {"reasoning": {"effort": "xhigh"}},
    "openai": {"reasoning": {"effort": "xhigh"}},
    "claude": {"reasoning": {"effort": "xhigh"}, "verbosity": "max"},
    "opus": {"reasoning": {"effort": "xhigh"}, "verbosity": "max"},
    "glm": {"reasoning": {"effort": "xhigh"}},
    "grok": {"reasoning": {"effort": "high"}},
}


def canonicalize_model(name: str) -> str:
    """Map deprecated slot aliases to their current slot name."""
    return MODEL_ALIASES.get(name, name)


def resolve_model(name: str) -> str:
    name = canonicalize_model(name)
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
