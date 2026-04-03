from codereview_mcp.secrets import redact_secrets, scan_secrets


def test_scan_detects_aws_key():
    content = "AWS_KEY=AKIAIOSFODNN7EXAMPLE\nnormal_code = True\n"
    findings = scan_secrets(content)
    assert len(findings) >= 1
    types = [f["type"] for f in findings]
    assert "AWS Access Key" in types


def test_scan_detects_github_token():
    content = "token = ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij\n"
    findings = scan_secrets(content)
    assert len(findings) >= 1
    types = [f["type"] for f in findings]
    assert "GitHub Token" in types


def test_scan_clean_content():
    content = "def hello():\n    return 'world'\n"
    findings = scan_secrets(content)
    assert len(findings) == 0


def test_redact_replaces_secret_lines():
    content = "line1\npassword = 'super_secret_123'\nline3\n"
    redacted, findings = redact_secrets(content)
    assert len(findings) >= 1
    assert "super_secret_123" not in redacted
    assert "[REDACTED" in redacted
    assert "line1" in redacted
    assert "line3" in redacted


def test_redact_clean_content_unchanged():
    content = "def hello():\n    return 'world'\n"
    redacted, findings = redact_secrets(content)
    assert findings == []
    assert redacted == content
