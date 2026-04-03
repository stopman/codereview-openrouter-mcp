import os

# Set a dummy API key so config.py doesn't exit during tests
os.environ.setdefault("OPENROUTER_API_KEY", "test-key-for-testing")
