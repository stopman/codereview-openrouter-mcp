import asyncio

from mcp.server.fastmcp import FastMCP

from codereview_mcp.client import get_review
from codereview_mcp.config import settings
from codereview_mcp.git_ops import (
    GitError,
    filter_binary_diffs,
    get_branch_diff,
    get_commit_diff,
    get_file_content,
    get_working_diff,
    truncate_diff,
    validate_repo,
)
from codereview_mcp.models import resolve_model
from codereview_mcp.prompts import REVIEW_SYSTEM_PROMPT, format_review_request
from codereview_mcp.secrets import redact_secrets

mcp = FastMCP("CodeReview")


async def _do_review(content: str, model: str, focus: str, context: str = "") -> str:
    model_id = resolve_model(model or settings.default_model)
    content, findings = await asyncio.to_thread(redact_secrets, content)
    if findings:
        warning = "\n".join(f"  - {f['type']} (line {f['line_number']})" for f in findings)
        context += f"\n\n⚠️ NOTICE: {len(findings)} potential secret(s) were redacted before sending:\n{warning}"
    prompt = format_review_request(content, focus=focus, context=context)
    return await get_review(prompt, REVIEW_SYSTEM_PROMPT, model_id)


async def _prepare_diff(diff: str) -> str:
    diff = filter_binary_diffs(diff)
    diff = truncate_diff(diff, settings.max_diff_chars)
    return diff


@mcp.tool(
    description="""Review current working tree changes (staged + unstaged diff).

    Args:
        repo_path: Path to the git repository (defaults to current directory)
        model: Model to use for review. Options: gemini, openai, claude, deepseek
        focus: Review focus. Options: all, security, architecture, edge_cases, style, abstractions
    """
)
async def review_diff(
    repo_path: str = ".",
    model: str = "gemini",
    focus: str = "all",
) -> str:
    try:
        if not await validate_repo(repo_path):
            return f"Error: '{repo_path}' is not a git repository."
        diff = await get_working_diff(repo_path)
        if not diff.strip():
            return "No working tree changes found. Nothing to review."
        diff = await _prepare_diff(diff)
        return await _do_review(diff, model, focus, context="Working tree diff (staged + unstaged changes)")
    except (GitError, ValueError) as e:
        return f"Error: {e}"


@mcp.tool(
    description="""Review a specific commit by SHA.

    Args:
        repo_path: Path to the git repository (defaults to current directory)
        sha: Commit SHA to review (defaults to HEAD)
        model: Model to use for review. Options: gemini, openai, claude, deepseek
        focus: Review focus. Options: all, security, architecture, edge_cases, style, abstractions
    """
)
async def review_commit(
    repo_path: str = ".",
    sha: str = "HEAD",
    model: str = "gemini",
    focus: str = "all",
) -> str:
    try:
        if not await validate_repo(repo_path):
            return f"Error: '{repo_path}' is not a git repository."
        diff = await get_commit_diff(repo_path, sha)
        if not diff.strip():
            return f"No changes found in commit {sha}."
        diff = await _prepare_diff(diff)
        return await _do_review(diff, model, focus, context=f"Commit {sha}")
    except (GitError, ValueError) as e:
        return f"Error: {e}"


@mcp.tool(
    description="""Review all changes on a branch compared to a base branch.

    Args:
        repo_path: Path to the git repository (defaults to current directory)
        branch: Branch to review
        base: Base branch to compare against (defaults to main)
        model: Model to use for review. Options: gemini, openai, claude, deepseek
        focus: Review focus. Options: all, security, architecture, edge_cases, style, abstractions
    """
)
async def review_branch(
    branch: str,
    repo_path: str = ".",
    base: str = "main",
    model: str = "gemini",
    focus: str = "all",
) -> str:
    try:
        if not await validate_repo(repo_path):
            return f"Error: '{repo_path}' is not a git repository."
        diff = await get_branch_diff(repo_path, branch, base)
        if not diff.strip():
            return f"No changes found between {base} and {branch}."
        diff = await _prepare_diff(diff)
        return await _do_review(diff, model, focus, context=f"Branch {branch} vs {base}")
    except (GitError, ValueError) as e:
        return f"Error: {e}"


@mcp.tool(
    description="""Review a single file in its entirety.

    Args:
        file_path: Path to the file relative to repo_path
        repo_path: Path to the git repository (defaults to current directory)
        model: Model to use for review. Options: gemini, openai, claude, deepseek
        focus: Review focus. Options: all, security, architecture, edge_cases, style, abstractions
    """
)
async def review_file(
    file_path: str,
    repo_path: str = ".",
    model: str = "gemini",
    focus: str = "all",
) -> str:
    try:
        if not await validate_repo(repo_path):
            return f"Error: '{repo_path}' is not a git repository."
        content = await get_file_content(repo_path, file_path)
        if not content.strip():
            return f"File '{file_path}' is empty. Nothing to review."
        content = truncate_diff(content, settings.max_diff_chars)
        return await _do_review(content, model, focus, context=f"Full file review: {file_path}")
    except (GitError, ValueError) as e:
        return f"Error: {e}"


def main():
    settings.validate()
    mcp.run()


if __name__ == "__main__":
    main()
