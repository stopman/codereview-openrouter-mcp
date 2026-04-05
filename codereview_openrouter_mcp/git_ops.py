import asyncio
import os
import re
from pathlib import Path

from codereview_openrouter_mcp.logging import get_logger

log = get_logger("git")

GIT_TIMEOUT_SECONDS = 30
_SAFE_REF_RE = re.compile(r"^[a-zA-Z0-9_./@^~:][a-zA-Z0-9_./@^~:\-]*$")


class GitError(Exception):
    pass


def _validate_git_ref(ref: str, label: str = "ref") -> None:
    if not _SAFE_REF_RE.match(ref):
        raise GitError(f"Invalid {label}: '{ref}' — must match [a-zA-Z0-9_./@^~:-]")


async def _run_git(repo_path: str, *args: str) -> str:
    cmd_str = f"git {' '.join(args)}"
    log.debug("Running: %s (cwd=%s)", cmd_str, repo_path)
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=repo_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=GIT_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        log.error("Git command timed out after %ds: %s", GIT_TIMEOUT_SECONDS, cmd_str)
        raise GitError(f"git {' '.join(args)} timed out after {GIT_TIMEOUT_SECONDS}s")
    if proc.returncode != 0:
        err_msg = stderr.decode(errors='replace').strip()
        log.error("Git command failed (rc=%d): %s — %s", proc.returncode, cmd_str, err_msg)
        raise GitError(f"git {' '.join(args)} failed: {err_msg}")
    log.debug("Git command succeeded: %s (stdout=%d bytes)", cmd_str, len(stdout))
    return stdout.decode(errors="replace")


async def validate_repo(repo_path: str) -> bool:
    try:
        await _run_git(repo_path, "rev-parse", "--git-dir")
        return True
    except (GitError, FileNotFoundError):
        return False


async def get_working_diff(repo_path: str) -> str:
    return await _run_git(repo_path, "diff", "HEAD")


async def resolve_ref(repo_path: str, ref: str) -> str:
    """Resolve an abbreviated or symbolic ref to a full SHA."""
    _validate_git_ref(ref, "git ref")
    result = await _run_git(repo_path, "rev-parse", ref)
    return result.strip()


async def get_commit_diff(repo_path: str, sha: str = "HEAD") -> str:
    sha = await resolve_ref(repo_path, sha)
    return await _run_git(repo_path, "show", "--format=", sha, "--")


async def get_branch_diff(repo_path: str, branch: str, base: str = "main") -> str:
    _validate_git_ref(branch, "branch")
    _validate_git_ref(base, "base branch")
    return await _run_git(repo_path, "diff", f"{base}...{branch}", "--")


async def get_file_content(repo_path: str, file_path: str) -> str:
    repo_root = Path(repo_path).resolve()
    target = (repo_root / file_path).resolve()
    if not target.is_relative_to(repo_root):
        raise GitError(f"Path traversal detected: '{file_path}' escapes repository root.")
    if not target.is_file():
        raise GitError(f"File not found: {target}")
    content = await asyncio.to_thread(target.read_text, encoding="utf-8", errors="replace")
    return content


def truncate_diff(diff: str, max_chars: int) -> str:
    if len(diff) <= max_chars:
        return diff
    return diff[:max_chars] + f"\n\n... [TRUNCATED: diff was {len(diff)} chars, showing first {max_chars}]"


def filter_binary_diffs(diff: str) -> str:
    lines = diff.split("\n")
    filtered = []
    skip = False
    for line in lines:
        if line.startswith("diff --git"):
            skip = False
            filtered.append(line)
        elif "Binary file" in line or line.startswith("GIT binary patch"):
            skip = True
            filtered.append("[binary file skipped]")
        elif not skip:
            filtered.append(line)
    return "\n".join(filtered)
