from codereview_mcp.prompts import REVIEW_SYSTEM_PROMPT, format_review_request, FOCUS_PROMPTS


def test_system_prompt_covers_all_dimensions():
    """System prompt must mention all 6 review dimensions."""
    assert "Security" in REVIEW_SYSTEM_PROMPT
    assert "Edge Cases" in REVIEW_SYSTEM_PROMPT
    assert "Architecture" in REVIEW_SYSTEM_PROMPT
    assert "Implementation" in REVIEW_SYSTEM_PROMPT
    assert "Style" in REVIEW_SYSTEM_PROMPT
    assert "Abstractions" in REVIEW_SYSTEM_PROMPT


def test_format_review_request_all():
    result = format_review_request("print('hi')", focus="all")
    assert "print('hi')" in result
    assert "Focus" not in result


def test_format_review_request_with_focus():
    result = format_review_request("code here", focus="security")
    assert "Focus" in result
    assert "security" in result.lower()


def test_format_review_request_with_context():
    result = format_review_request("code", context="Working tree diff")
    assert "Working tree diff" in result


def test_all_focus_options_exist():
    expected = {"security", "architecture", "edge_cases", "style", "abstractions"}
    assert set(FOCUS_PROMPTS.keys()) == expected
