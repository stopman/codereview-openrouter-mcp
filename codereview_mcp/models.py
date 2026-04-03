MODELS: dict[str, str] = {
    "gemini": "google/gemini-3.1-pro-preview",
    "openai": "openai/gpt-5.3-codex",
    "claude": "anthropic/claude-opus-4.6",
    "deepseek": "deepseek/deepseek-r1",
}

DEFAULT_MODEL = "gemini"


def resolve_model(name: str) -> str:
    model_id = MODELS.get(name)
    if not model_id:
        available = ", ".join(MODELS.keys())
        raise ValueError(f"Unknown model '{name}'. Available: {available}")
    return model_id
