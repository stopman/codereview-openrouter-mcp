import os
import tempfile

from detect_secrets import SecretsCollection
from detect_secrets.settings import default_settings

from codereview_openrouter_mcp.logging import get_logger

log = get_logger("secrets")


def scan_secrets(content: str) -> list[dict]:
    """Scan content for secrets using detect-secrets. Returns list of findings."""
    log.debug("Scanning content (%d chars) for secrets", len(content))
    fd, tmp_path = tempfile.mkstemp(suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        secrets = SecretsCollection()
        with default_settings():
            secrets.scan_file(tmp_path)
        results = secrets.json()
        findings = results.get(tmp_path, [])
        if findings:
            log.info("Secret scan found %d potential secret(s)", len(findings))
        else:
            log.debug("Secret scan clean — no findings")
        return findings
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


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

    log.info("Redacted %d line(s) containing potential secrets", len(secret_lines))
    return "\n".join(lines), findings
