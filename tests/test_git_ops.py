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


@pytest.mark.asyncio
async def test_repo_path_allowed_when_configured(temp_git_repo):
    """Paths under allowed roots should pass validation."""
    from unittest.mock import patch

    with patch("codereview_openrouter_mcp.config.settings") as mock_settings:
        mock_settings.allowed_repo_roots = [str(temp_git_repo.parent)]
        assert await validate_repo(str(temp_git_repo)) is True


@pytest.mark.asyncio
async def test_repo_path_rejected_when_outside_roots(temp_git_repo):
    """Paths outside allowed roots should fail validation."""
    from unittest.mock import patch

    with patch("codereview_openrouter_mcp.config.settings") as mock_settings:
        mock_settings.allowed_repo_roots = ["/some/other/root"]
        assert await validate_repo(str(temp_git_repo)) is False


@pytest.mark.asyncio
async def test_repo_path_no_restriction_when_unconfigured(temp_git_repo):
    """When ALLOWED_REPO_ROOTS is empty, all paths allowed."""
    from unittest.mock import patch

    with patch("codereview_openrouter_mcp.config.settings") as mock_settings:
        mock_settings.allowed_repo_roots = []
        assert await validate_repo(str(temp_git_repo)) is True


@pytest.mark.asyncio
async def test_repo_path_rejects_symlink_escape(temp_git_repo, tmp_path):
    """Symlinks that escape allowed roots should be rejected."""
    from unittest.mock import patch

    # Create a symlink from outside allowed root pointing to the repo
    link_path = tmp_path / "sneaky_link"
    link_path.symlink_to(temp_git_repo)

    with patch("codereview_openrouter_mcp.config.settings") as mock_settings:
        # Only allow tmp_path (the link's parent), not temp_git_repo's parent
        # The link resolves to temp_git_repo, which is NOT under /some/allowed/root
        mock_settings.allowed_repo_roots = ["/some/allowed/root"]
        assert await validate_repo(str(link_path)) is False


@pytest.mark.asyncio
async def test_validate_git_ref_rejects_dash_prefix():
    """Refs starting with - must be rejected to prevent argument injection."""
    from codereview_openrouter_mcp.git_ops import _validate_git_ref

    with pytest.raises(GitError, match="Invalid"):
        _validate_git_ref("--no-index")
    with pytest.raises(GitError, match="Invalid"):
        _validate_git_ref("-v")


@pytest.mark.asyncio
async def test_git_error_does_not_leak_raw_stderr(temp_git_repo):
    """Git errors should sanitize stderr, not return it raw."""
    from codereview_openrouter_mcp.git_ops import _run_git

    with pytest.raises(GitError) as exc_info:
        await _run_git(str(temp_git_repo), "show", "nonexistent_ref_that_does_not_exist")

    error_msg = str(exc_info.value)
    # Should NOT contain raw git stderr like "fatal: bad object"
    assert "fatal:" not in error_msg, f"Raw git stderr leaked: {error_msg}"
    # Should contain a sanitized message
    assert "Git operation failed" in error_msg
