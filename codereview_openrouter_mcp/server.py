import asyncio
import time

from mcp.server.fastmcp import FastMCP

from codereview_openrouter_mcp.client import get_review
from codereview_openrouter_mcp.config import settings
from codereview_openrouter_mcp.git_ops import (
    GitError,
    filter_binary_diffs,
    get_branch_diff,
    get_commit_diff,
    get_file_content,
    get_working_diff,
    truncate_diff,
    validate_repo,
)
from codereview_openrouter_mcp.logging import get_logger, setup_logging
from codereview_openrouter_mcp.models import (
    ALL_REVIEW_MODELS,
    MODEL_DISPLAY_NAMES,
    get_reasoning_config,
    resolve_model,
)
from codereview_openrouter_mcp.prompts import (
    PLAN_REVIEW_SYSTEM_PROMPT,
    REVIEW_SYSTEM_PROMPT,
    format_plan_review_request,
    format_review_request,
    sanitize_context,
)
from codereview_openrouter_mcp.secrets import redact_secrets

log = get_logger("server")

mcp = FastMCP("CodeReview")

PLAN_MAX_TOKENS = 16384
MIN_MULTI_MODEL_RESULTS = 3


async def _do_single_review(
    content: str, model_name: str, system_prompt: str, prompt: str,
    use_reasoning: bool = False,
    max_tokens: int | None = None,
) -> tuple[str, str]:
    """Run a single model review. Returns (model_name, result_text)."""
    model_id = resolve_model(model_name)
    extra_body = get_reasoning_config(model_name) if use_reasoning else None
    try:
        result = await get_review(
            prompt, system_prompt, model_id,
            extra_body=extra_body,
            max_tokens=max_tokens,
        )
        return model_name, result
    except Exception as e:
        log.error("Review failed for model %s: %s", model_name, e)
        return model_name, f"Error: Review with {model_name} failed — {e}"


async def _do_review(content: str, model: str, focus: str, context: str = "") -> str:
    model = model or settings.default_model
    content, findings = await asyncio.to_thread(redact_secrets, content)
    if findings:
        log.warning("Redacted %d potential secret(s) before sending to LLM", len(findings))
        warning = "\n".join(f"  - {f['type']} (line {f['line_number']})" for f in findings)
        context += f"\n\n⚠️ NOTICE: {len(findings)} potential secret(s) were redacted before sending:\n{warning}"
    prompt = format_review_request(content, focus=focus, context=context)

    if model == "all":
        return await _do_multi_model_review(prompt, REVIEW_SYSTEM_PROMPT)

    model_id = resolve_model(model)
    log.info("Sending review request: model=%s, focus=%s, content_len=%d", model_id, focus, len(content))
    t0 = time.monotonic()
    result = await get_review(prompt, REVIEW_SYSTEM_PROMPT, model_id)
    elapsed = time.monotonic() - t0
    log.info("Review completed in %.1fs, response_len=%d", elapsed, len(result))
    return result


async def _do_multi_model_review(
    prompt: str, system_prompt: str,
    use_reasoning: bool = False,
    max_tokens: int | None = None,
) -> str:
    """Fan out review to all models in ALL_REVIEW_MODELS concurrently.

    Returns results from the fastest MIN_MULTI_MODEL_RESULTS models,
    cancelling any still-running tasks.
    """
    min_results = min(MIN_MULTI_MODEL_RESULTS, len(ALL_REVIEW_MODELS))
    log.info("Starting multi-model review across %d models (returning after %d): %s",
             len(ALL_REVIEW_MODELS), min_results, ALL_REVIEW_MODELS)
    t0 = time.monotonic()

    tasks = [
        asyncio.create_task(
            _do_single_review(
                "", model_name, system_prompt, prompt,
                use_reasoning=use_reasoning,
                max_tokens=max_tokens,
            )
        )
        for model_name in ALL_REVIEW_MODELS
    ]

    sections = []
    errors = []
    done_count = 0

    for coro in asyncio.as_completed(tasks):
        try:
            result = await coro
        except Exception as e:
            errors.append(f"Unexpected error: {e}")
            done_count += 1
            continue

        model_name, review_text = result
        display_name = MODEL_DISPLAY_NAMES.get(model_name, model_name)
        done_count += 1

        if review_text.startswith("Error:"):
            errors.append(f"{display_name}: {review_text}")
        else:
            sections.append(f"---\n\n# Review by {display_name}\n\n{review_text}")

        if len(sections) >= min_results:
            break

    # Cancel still-running tasks and await them to avoid resource leaks
    pending = [task for task in tasks if not task.done()]
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    elapsed = time.monotonic() - t0
    remaining = len(ALL_REVIEW_MODELS) - done_count
    log.info("Multi-model review completed in %.1fs (%d succeeded, %d failed, %d skipped)",
             elapsed, len(sections), len(errors), remaining)

    parts = []
    if errors:
        error_block = "\n".join(f"- {e}" for e in errors)
        parts.append(f"⚠️ **Some models failed:**\n{error_block}\n")
    parts.extend(sections)

    if not sections:
        return "Error: All models failed.\n\n" + "\n".join(f"- {e}" for e in errors)

    return "\n\n".join(parts)


async def _prepare_diff(diff: str) -> str:
    diff = filter_binary_diffs(diff)
    diff = truncate_diff(diff, settings.max_diff_chars)
    return diff


@mcp.tool(
    description="""Review current working tree changes (staged + unstaged diff).

    Args:
        repo_path: Path to the git repository (defaults to current directory)
        model: Model to use for review. Options: all, gemini, openai, claude, deepseek, kimi. Default: all (parallel multi-model review)
        focus: Review focus. Default: all (security, architecture, edge_cases, style, abstractions). Pass a single area to narrow the review.
    """
)
async def review_diff(
    repo_path: str = ".",
    model: str = "all",
    focus: str = "all",
) -> str:
    log.info("review_diff called: repo_path=%s, model=%s, focus=%s", repo_path, model, focus)
    try:
        if not await validate_repo(repo_path):
            return f"Error: '{repo_path}' is not a git repository."
        diff = await get_working_diff(repo_path)
        if not diff.strip():
            log.info("review_diff: no working tree changes found")
            return "No working tree changes found. Nothing to review."
        diff = await _prepare_diff(diff)
        return await _do_review(diff, model, focus, context="Working tree diff (staged + unstaged changes)")
    except (GitError, ValueError) as e:
        log.error("review_diff failed: %s", e)
        return f"Error: {e}"


@mcp.tool(
    description="""Review a specific commit by SHA.

    Args:
        repo_path: Path to the git repository (defaults to current directory)
        sha: Commit SHA to review (defaults to HEAD)
        model: Model to use for review. Options: all, gemini, openai, claude, deepseek, kimi. Default: all (parallel multi-model review)
        focus: Review focus. Default: all (security, architecture, edge_cases, style, abstractions). Pass a single area to narrow the review.
    """
)
async def review_commit(
    repo_path: str = ".",
    sha: str = "HEAD",
    model: str = "all",
    focus: str = "all",
) -> str:
    log.info("review_commit called: repo_path=%s, sha=%s, model=%s, focus=%s", repo_path, sha, model, focus)
    try:
        if not await validate_repo(repo_path):
            return f"Error: '{repo_path}' is not a git repository."
        diff = await get_commit_diff(repo_path, sha)
        if not diff.strip():
            log.info("review_commit: no changes in commit %s", sha)
            return f"No changes found in commit {sha}."
        diff = await _prepare_diff(diff)
        return await _do_review(diff, model, focus, context=f"Commit {sanitize_context(sha)}")
    except (GitError, ValueError) as e:
        log.error("review_commit failed: %s", e)
        return f"Error: {e}"


@mcp.tool(
    description="""Review all changes on a branch compared to a base branch.

    Args:
        repo_path: Path to the git repository (defaults to current directory)
        branch: Branch to review
        base: Base branch to compare against (defaults to main)
        model: Model to use for review. Options: all, gemini, openai, claude, deepseek, kimi. Default: all (parallel multi-model review)
        focus: Review focus. Default: all (security, architecture, edge_cases, style, abstractions). Pass a single area to narrow the review.
    """
)
async def review_branch(
    branch: str,
    repo_path: str = ".",
    base: str = "main",
    model: str = "all",
    focus: str = "all",
) -> str:
    log.info("review_branch called: branch=%s, base=%s, repo_path=%s, model=%s, focus=%s", branch, base, repo_path, model, focus)
    try:
        if not await validate_repo(repo_path):
            return f"Error: '{repo_path}' is not a git repository."
        diff = await get_branch_diff(repo_path, branch, base)
        if not diff.strip():
            log.info("review_branch: no changes between %s and %s", base, branch)
            return f"No changes found between {base} and {branch}."
        diff = await _prepare_diff(diff)
        return await _do_review(diff, model, focus, context=f"Branch {sanitize_context(branch)} vs {sanitize_context(base)}")
    except (GitError, ValueError) as e:
        log.error("review_branch failed: %s", e)
        return f"Error: {e}"


@mcp.tool(
    description="""Review a single file in its entirety.

    Args:
        file_path: Path to the file relative to repo_path
        repo_path: Path to the git repository (defaults to current directory)
        model: Model to use for review. Options: all, gemini, openai, claude, deepseek, kimi. Default: all (parallel multi-model review)
        focus: Review focus. Default: all (security, architecture, edge_cases, style, abstractions). Pass a single area to narrow the review.
    """
)
async def review_file(
    file_path: str,
    repo_path: str = ".",
    model: str = "all",
    focus: str = "all",
) -> str:
    log.info("review_file called: file_path=%s, repo_path=%s, model=%s, focus=%s", file_path, repo_path, model, focus)
    try:
        if not await validate_repo(repo_path):
            return f"Error: '{repo_path}' is not a git repository."
        content = await get_file_content(repo_path, file_path)
        if not content.strip():
            log.info("review_file: file '%s' is empty", file_path)
            return f"File '{file_path}' is empty. Nothing to review."
        content = truncate_diff(content, settings.max_diff_chars)
        return await _do_review(content, model, focus, context=f"Full file review: {sanitize_context(file_path)}")
    except (GitError, ValueError) as e:
        log.error("review_file failed: %s", e)
        return f"Error: {e}"


async def _do_plan_review(plan: str, codebase_context: str, model: str) -> str:
    """Shared logic for review_plan and review_oracle."""
    model = model or settings.default_model

    plan, plan_findings = await asyncio.to_thread(redact_secrets, plan)
    if codebase_context:
        codebase_context, ctx_findings = await asyncio.to_thread(redact_secrets, codebase_context)
    else:
        ctx_findings = []
    all_findings = plan_findings + ctx_findings
    if all_findings:
        log.warning("Redacted %d potential secret(s) from plan review input", len(all_findings))

    prompt = format_plan_review_request(plan, codebase_context)

    if model == "all":
        return await _do_multi_model_review(
            prompt, PLAN_REVIEW_SYSTEM_PROMPT,
            use_reasoning=True, max_tokens=PLAN_MAX_TOKENS,
        )

    model_id = resolve_model(model)
    extra_body = get_reasoning_config(model)

    t0 = time.monotonic()
    result = await get_review(
        prompt, PLAN_REVIEW_SYSTEM_PROMPT, model_id,
        extra_body=extra_body,
        max_tokens=PLAN_MAX_TOKENS,
    )
    elapsed = time.monotonic() - t0
    log.info("Plan review completed in %.1fs, response_len=%d", elapsed, len(result))
    return result


@mcp.tool(
    description="""Review a technical plan or design document.

    Evaluates the plan for first-principles thinking, simplicity (KISS),
    security risks, edge cases, and architecture quality.

    Uses maximum reasoning effort for the deepest possible analysis.

    Args:
        plan: The plan or design document text to review
        codebase_context: Optional relevant code snippets for grounding the review
        model: Model to use for review. Options: all, gemini, openai, claude, deepseek, kimi. Default: all (parallel multi-model review)
    """
)
async def review_plan(
    plan: str,
    codebase_context: str = "",
    model: str = "all",
) -> str:
    log.info("review_plan called: model=%s, plan_len=%d", model, len(plan))
    try:
        return await _do_plan_review(plan, codebase_context, model)
    except ValueError as e:
        log.error("review_plan failed: %s", e)
        return f"Error: {e}"


@mcp.tool(
    description="""Review a technical plan, design document, or reasoning task (oracle).

    This is the same as review_plan — an alias for discoverability by
    AI coding assistants that use the term "oracle" (e.g. Amp) instead of
    "plan" (e.g. Claude Code).

    Evaluates the plan for first-principles thinking, simplicity (KISS),
    security risks, edge cases, and architecture quality.

    Uses maximum reasoning effort for the deepest possible analysis.

    Args:
        plan: The plan, design document, or reasoning task to review
        codebase_context: Optional relevant code snippets for grounding the review
        model: Model to use for review. Options: all, gemini, openai, claude, deepseek, kimi. Default: all (parallel multi-model review)
    """
)
async def review_oracle(
    plan: str,
    codebase_context: str = "",
    model: str = "all",
) -> str:
    log.info("review_oracle called: model=%s, plan_len=%d", model, len(plan))
    try:
        return await _do_plan_review(plan, codebase_context, model)
    except ValueError as e:
        log.error("review_oracle failed: %s", e)
        return f"Error: {e}"


def main():
    settings.validate()
    setup_logging(settings.log_level)
    log.info("CodeReview MCP server starting (log_level=%s)", settings.log_level)
    if not settings.allowed_repo_roots:
        log.warning("ALLOWED_REPO_ROOTS is not set — server can access any git repo on this system")
    mcp.run()


if __name__ == "__main__":
    main()
