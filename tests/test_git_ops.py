import subprocess

import pytest

from codereview_openrouter_mcp.git_ops import (
    GitError,
    filter_binary_diffs,
    get_commit_diff,
    get_file_content,
    get_working_diff,
    resolve_ref,
    truncate_diff,
    validate_repo,
)


@pytest.fixture
def temp_git_repo(tmp_path):
    """Create a temporary git repository."""
    subprocess.run(
        ["git", "init"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    test_file = tmp_path / "hello.py"
    test_file.write_text("print('hello')\n")
    subprocess.run(
        ["git", "add", "."],
        cwd=tmp_path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path, check=True, capture_output=True,
    )
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


@pytest.mark.asyncio
async def test_get_file_content_path_traversal(temp_git_repo):
    """Path traversal must be rejected."""
    with pytest.raises(GitError, match="Path traversal"):
        await get_file_content(str(temp_git_repo), "../../etc/passwd")


@pytest.mark.asyncio
async def test_get_file_content_valid(temp_git_repo):
    content = await get_file_content(str(temp_git_repo), "hello.py")
    assert "hello" in content


@pytest.mark.asyncio
async def test_get_file_content_not_found(temp_git_repo):
    with pytest.raises(GitError, match="File not found"):
        await get_file_content(str(temp_git_repo), "nonexistent.py")


def test_truncate_diff_short():
    assert truncate_diff("short", 100) == "short"


def test_truncate_diff_long():
    long_text = "x" * 200
    result = truncate_diff(long_text, 100)
    assert len(result) > 100
    assert "TRUNCATED" in result
    assert result.startswith("x" * 100)


@pytest.mark.asyncio
async def test_resolve_ref_full_sha(temp_git_repo):
    """Full SHA should resolve to itself."""
    full = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=temp_git_repo, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert await resolve_ref(str(temp_git_repo), full) == full


@pytest.mark.asyncio
async def test_resolve_ref_abbreviated_sha(temp_git_repo):
    """Abbreviated SHA should resolve to the full SHA."""
    full = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=temp_git_repo, capture_output=True, text=True, check=True,
    ).stdout.strip()
    short = full[:7]
    assert await resolve_ref(str(temp_git_repo), short) == full


@pytest.mark.asyncio
async def test_resolve_ref_head(temp_git_repo):
    """HEAD should resolve to a full SHA."""
    result = await resolve_ref(str(temp_git_repo), "HEAD")
    assert len(result) == 40


@pytest.mark.asyncio
async def test_resolve_ref_invalid(temp_git_repo):
    """Invalid ref should raise GitError."""
    with pytest.raises(GitError):
        await resolve_ref(str(temp_git_repo), "nonexistent_ref_abc123")


@pytest.mark.asyncio
async def test_get_commit_diff_abbreviated_sha(temp_git_repo):
    """get_commit_diff should work with abbreviated SHAs."""
    full = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=temp_git_repo, capture_output=True, text=True, check=True,
    ).stdout.strip()
    short = full[:7]
    diff = await get_commit_diff(str(temp_git_repo), short)
    assert "hello" in diff


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
