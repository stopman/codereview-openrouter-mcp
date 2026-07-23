import os

from dotenv import load_dotenv

from planreview_openrouter_mcp.logging import get_logger

load_dotenv(override=True)

log = get_logger("config")


class Settings:
    def __init__(self):
        self.openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
        self.default_model: str = os.getenv("DEFAULT_MODEL", "sol")
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
