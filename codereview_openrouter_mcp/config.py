import os

from dotenv import load_dotenv

from codereview_openrouter_mcp.logging import get_logger

load_dotenv(override=True)

log = get_logger("config")


def _safe_positive_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        log.warning("Invalid integer '%s', using default %d", value, default)
        return default
    if parsed <= 0:
        log.warning("Value must be positive (got %d), using default %d", parsed, default)
        return default
    return parsed


class Settings:
    def __init__(self):
        self.openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
        self.default_model: str = os.getenv("DEFAULT_MODEL", "gptpro")
        self.max_diff_chars: int = _safe_positive_int(os.getenv("MAX_DIFF_CHARS"), 500000)
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
        # Privacy: only route to Zero-Data-Retention provider endpoints.
        # Default on. Disable (OPENROUTER_ZDR=false) if a model has no ZDR
        # endpoint and you hit hard routing failures. data_collection="deny"
        # is always sent regardless, so providers never train on our data.
        self.require_zdr: bool = os.getenv("OPENROUTER_ZDR", "true").strip().lower() not in (
            "false",
            "0",
            "no",
        )
        self.allowed_repo_roots: list[str] = [
            p.strip() for p in os.getenv("ALLOWED_REPO_ROOTS", "").split(",") if p.strip()
        ]

    def validate(self):
        if not self.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY environment variable is required")


settings = Settings()
