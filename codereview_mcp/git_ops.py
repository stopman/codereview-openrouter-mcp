import asyncio
import os


class GitError(Exception):
    pass


async def _run_git(repo_path: str, *args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=repo_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {stderr.decode().strip()}")
    return stdout.decode()


async def validate_repo(repo_path: str) -> bool:
    try:
        await _run_git(repo_path, "rev-parse", "--git-dir")
        return True
    except (GitError, FileNotFoundError):
        return False


async def get_working_diff(repo_path: str) -> str:
    return await _run_git(repo_path, "diff", "HEAD")


async def get_commit_diff(repo_path: str, sha: str = "HEAD") -> str:
    return await _run_git(repo_path, "show", "--format=", sha)


async def get_branch_diff(repo_path: str, branch: str, base: str = "main") -> str:
    return await _run_git(repo_path, "diff", f"{base}...{branch}")


async def get_file_content(repo_path: str, file_path: str) -> str:
    full_path = os.path.join(repo_path, file_path)
    if not os.path.isfile(full_path):
        raise GitError(f"File not found: {full_path}")
    with open(full_path) as f:
        return f.read()


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
            filtered.append(f"[binary file skipped]")
        elif not skip:
            filtered.append(line)
    return "\n".join(filtered)
