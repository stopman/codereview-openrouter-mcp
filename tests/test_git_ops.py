import os
import tempfile

import pytest

from codereview_mcp.git_ops import (
    filter_binary_diffs,
    get_working_diff,
    truncate_diff,
    validate_repo,
)


@pytest.fixture
def temp_git_repo(tmp_path):
    """Create a temporary git repository."""
    os.system(f"cd {tmp_path} && git init && git config user.email 'test@test.com' && git config user.name 'Test'")
    # Create initial commit
    test_file = tmp_path / "hello.py"
    test_file.write_text("print('hello')\n")
    os.system(f"cd {tmp_path} && git add . && git commit -m 'init'")
    return tmp_path


@pytest.mark.asyncio
async def test_validate_repo_valid(temp_git_repo):
    assert await validate_repo(str(temp_git_repo)) is True


@pytest.mark.asyncio
async def test_validate_repo_invalid(tmp_path):
    assert await validate_repo(str(tmp_path)) is False


@pytest.mark.asyncio
async def test_get_working_diff_no_changes(temp_git_repo):
    diff = await get_working_diff(str(temp_git_repo))
    assert diff.strip() == ""


@pytest.mark.asyncio
async def test_get_working_diff_with_changes(temp_git_repo):
    test_file = temp_git_repo / "hello.py"
    test_file.write_text("print('world')\n")
    diff = await get_working_diff(str(temp_git_repo))
    assert "hello" in diff
    assert "world" in diff


def test_truncate_diff_short():
    assert truncate_diff("short", 100) == "short"


def test_truncate_diff_long():
    long_text = "x" * 200
    result = truncate_diff(long_text, 100)
    assert len(result) > 100  # includes truncation message
    assert "TRUNCATED" in result
    assert result.startswith("x" * 100)


def test_filter_binary_diffs():
    diff = """diff --git a/image.png b/image.png
Binary file image.png has changed
diff --git a/code.py b/code.py
--- a/code.py
+++ b/code.py
+print('hello')"""
    result = filter_binary_diffs(diff)
    assert "[binary file skipped]" in result
    assert "print('hello')" in result
