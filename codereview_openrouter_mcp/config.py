import os
import sys

from dotenv import load_dotenv

load_dotenv()


def _safe_positive_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        print(f"WARNING: Invalid integer '{value}', using default {default}", file=sys.stderr)
        return default
    if parsed <= 0:
        print(f"WARNING: Value must be positive (got {parsed}), using default {default}", file=sys.stderr)
        return default
    return parsed


class Settings:
    def __init__(self):
        self.openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
        self.default_model: str = os.getenv("DEFAULT_MODEL", "gemini")
        self.max_diff_chars: int = _safe_positive_int(os.getenv("MAX_DIFF_CHARS"), 100000)

    def validate(self):
        if not self.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY environment variable is required")


settings = Settings()
