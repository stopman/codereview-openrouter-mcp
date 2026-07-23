import asyncio
from pathlib import Path

from codereview_openrouter_mcp.logging import get_logger

log = get_logger("context_files")


class ContextFilesError(Exception):
    pass


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
        raise ContextFilesError(f"Cannot resolve repository path: {e}") from e
    raise ContextFilesError(
        "Repository path not in allowed roots. Configure ALLOWED_REPO_ROOTS."
    )


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
    # This is the server's only filesystem access path, so the
    # ALLOWED_REPO_ROOTS restriction is enforced here.
    _check_repo_path_allowed(repo_path)
    if len(file_paths) > MAX_CONTEXT_FILES:
        raise ContextFilesError(
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
