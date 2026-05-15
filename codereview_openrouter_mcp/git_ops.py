import asyncio
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
    _check_repo_path_allowed(repo_path)
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
        # Sanitize: log full error for operators, but raise a generic message
        # to avoid leaking internal paths, repo structure, or secrets
        raise GitError(f"Git operation failed: {args[0]}")
    log.debug("Git command succeeded: %s (stdout=%d bytes)", cmd_str, len(stdout))
    return stdout.decode(errors="replace")


def _check_repo_path_allowed(repo_path: str) -> None:
    """Check repo_path is under an allowed root (if configured)."""
    from codereview_openrouter_mcp.config import settings

    if not settings.allowed_repo_roots:
        return
    try:
        resolved = Path(repo_path).resolve()
        for root in settings.allowed_repo_roots:
            if resolved.is_relative_to(Path(root).resolve()):
                return
    except OSError as e:
        raise GitError(f"Cannot resolve repository path: {e}") from e
    raise GitError("Repository path not in allowed roots. Configure ALLOWED_REPO_ROOTS.")


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


MAX_CONTEXT_FILES = 50
MAX_CONTEXT_FILES_CHARS = 200_000
MAX_SINGLE_CONTEXT_FILE_CHARS = 100_000


def _looks_binary(sample: bytes) -> bool:
    return b"\x00" in sample


async def read_context_files(
    repo_path: str,
    file_paths: list[str],
    max_total_chars: int = MAX_CONTEXT_FILES_CHARS,
) -> tuple[str, list[str]]:
    """Read multiple text files from a repo with path-traversal safety and a
    total-size cap. Returns (concatenated_text, skipped_messages).

    Each file is wrapped in XML tags so the model treats it as a strict
    content boundary, not as instructions. Any literal </file> or
    </project_context> sequences in file content are defanged so a malicious
    or accidental fragment cannot close the boundary early. If the budget
    runs out mid-file, the file is truncated and the closing tag is emitted
    safely so the surrounding XML stays balanced.

    Skipped files (missing, too large, binary, traversal attempt) are reported
    via the second return value so the caller can surface a notice to the LLM.
    """
    if not file_paths:
        return "", []
    if len(file_paths) > MAX_CONTEXT_FILES:
        raise GitError(
            f"Too many context files ({len(file_paths)}); max {MAX_CONTEXT_FILES}."
        )

    repo_root = Path(repo_path).resolve()
    blocks: list[str] = []
    skipped: list[str] = []
    remaining = max_total_chars

    for rel_path in file_paths:
        if remaining <= 0:
            skipped.append(f"{rel_path}: budget exhausted")
            continue

        try:
            target = (repo_root / rel_path).resolve()
        except (OSError, ValueError) as e:
            skipped.append(f"{rel_path}: cannot resolve ({e})")
            continue

        if not target.is_relative_to(repo_root):
            skipped.append(f"{rel_path}: path escapes repository root")
            continue
        if not target.is_file():
            skipped.append(f"{rel_path}: not found")
            continue

        try:
            file_size = target.stat().st_size
        except OSError as e:
            skipped.append(f"{rel_path}: stat failed ({e})")
            continue

        if file_size > MAX_SINGLE_CONTEXT_FILE_CHARS:
            skipped.append(
                f"{rel_path}: too large ({file_size} bytes, max {MAX_SINGLE_CONTEXT_FILE_CHARS})"
            )
            continue

        try:
            raw = await asyncio.to_thread(target.read_bytes)
        except OSError as e:
            skipped.append(f"{rel_path}: read failed ({e})")
            continue

        if _looks_binary(raw[:8192]):
            skipped.append(f"{rel_path}: binary content")
            continue

        content = raw.decode("utf-8", errors="replace")
        truncated = False
        if len(content) > remaining:
            content = content[:remaining]
            truncated = True

        # Defang any closing tags that would otherwise break the XML envelope.
        safe = (
            content.replace("</file>", "&lt;/file&gt;")
                   .replace("</project_context>", "&lt;/project_context&gt;")
        )
        suffix = "\n[TRUNCATED: file exceeds remaining context-files budget]" if truncated else ""
        blocks.append(f'<file name="{rel_path}">\n{safe}{suffix}\n</file>')
        remaining -= len(content)

    if not blocks and not skipped:
        return "", []

    body_parts = []
    if skipped:
        notice = "\n".join(f"- {s}" for s in skipped)
        body_parts.append(
            f"<context_notice>\nThe following requested files were not included:\n{notice}\n</context_notice>"
        )
    body_parts.extend(blocks)
    body = "\n\n".join(body_parts)
    wrapped = f"<project_context>\n{body}\n</project_context>"
    return wrapped, skipped


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
