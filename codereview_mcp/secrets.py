import json
import re
import tempfile
import os

from detect_secrets import SecretsCollection
from detect_secrets.settings import default_settings


def scan_secrets(content: str) -> list[dict]:
    """Scan content for secrets using detect-secrets. Returns list of findings."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(content)
        tmp_path = f.name
    try:
        secrets = SecretsCollection()
        with default_settings():
            secrets.scan_file(tmp_path)
        results = secrets.json()
        return results.get(tmp_path, [])
    finally:
        os.unlink(tmp_path)


def redact_secrets(content: str) -> tuple[str, list[dict]]:
    """Scan for secrets and redact the lines containing them.

    Returns (redacted_content, findings) where findings is a list of
    dicts with 'type' and 'line_number' keys.
    """
    findings = scan_secrets(content)
    if not findings:
        return content, []

    secret_lines = {f["line_number"] for f in findings}
    lines = content.split("\n")
    for line_idx_1based in secret_lines:
        idx = line_idx_1based - 1
        if 0 <= idx < len(lines):
            lines[idx] = "[REDACTED — potential secret detected by detect-secrets]"

    return "\n".join(lines), findings
