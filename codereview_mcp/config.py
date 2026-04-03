import os
import sys

from dotenv import load_dotenv

load_dotenv()


class Settings:
    def __init__(self):
        self.openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
        self.default_model: str = os.getenv("DEFAULT_MODEL", "gemini")
        self.max_diff_chars: int = int(os.getenv("MAX_DIFF_CHARS", "100000"))

    def validate(self):
        if not self.openrouter_api_key:
            print("ERROR: OPENROUTER_API_KEY environment variable is required", file=sys.stderr)
            sys.exit(1)


settings = Settings()
settings.validate()
