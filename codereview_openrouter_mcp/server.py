import asyncio
import time
from typing import Callable

from mcp.server.fastmcp import Context, FastMCP

from codereview_openrouter_mcp.client import get_review
from codereview_openrouter_mcp.config import settings
from codereview_openrouter_mcp.git_ops import (
    GitError,
    filter_binary_diffs,
    get_branch_diff,
    get_commit_diff,
    get_file_content,
    get_working_diff,
    read_context_files,
    truncate_diff,
    validate_repo,
)
from codereview_openrouter_mcp.logging import get_logger, setup_logging
from codereview_openrouter_mcp.models import (
    ALL_REVIEW_MODELS,
    FALLBACK_DISPLAY_NAMES,
    FALLBACK_MODELS,
    MODEL_DISPLAY_NAMES,
    get_model_extra_body,
    get_reasoning_config,
    resolve_model,
)
from codereview_openrouter_mcp.prompts import (
    format_plan_review_request,
    format_review_request,
    get_persona,
    get_plan_review_system_prompt,
    get_review_system_prompt,
    sanitize_context,
)
from codereview_openrouter_mcp.secrets import redact_secrets

log = get_logger("server")

SERVER_INSTRUCTIONS = """\
CodeReview MCP — multi-model code and plan review via OpenRouter.

## When to use this server

- A non-trivial code change is ready for a second opinion (review_diff, review_commit, review_branch, review_file)
- A technical plan or design needs scrutiny before implementation (review_plan / review_oracle)
- A focused review is needed on one dimension: security, architecture, edge_cases, style, abstractions (pass `focus=`)

## Picking a model

- `model="all"` (RECOMMENDED for important reviews): runs a 4-model panel with
  complementary personas — GPT-5.5 Pro (architect), GPT-5.3 (detail-oriented),
  Claude Fable 5 (first-principles / simplicity), Claude Opus 4.8
  (production/pragmatist + security).
  Returns the panel's reviews as markdown; the caller (you) synthesizes.
- Single model picks: `gptpro` (default, architect lens, deep reasoning),
  `openai` (detail), `claude` (first-principles simplicity),
  `opus` (production/pragmatist + security).
- For security-focused reviews (`focus="security"`), prefer `opus`: the
  `claude` slot runs Fable 5, whose dual-use safety measures may make it
  decline security analysis.

## Attaching project documentation — IMPORTANT

Every tool accepts an optional `context_files: list[str]` parameter — paths
(relative to `repo_path`) to markdown/text docs (architecture briefs,
READMEs, ADRs, design plans, CLAUDE.md, docs/ folder contents). The
reviewer models read those docs alongside the code so they can judge the
change against the project's *stated goals*, not in isolation.

**Be proactive about this.** Before calling any review tool on a meaningful
change, briefly scan the repo for project-context docs and include the
relevant ones via `context_files`. Common locations to check:

- `ARCHITECTURE.md`, `ARCH.md`, `DESIGN.md` at repo root
- `README.md` (if it actually describes architecture, not just install steps)
- `docs/` — especially `docs/architecture*`, `docs/design*`, `docs/adr/*`,
  `docs/plan*`, `docs/roadmap*`
- `CLAUDE.md`, `AGENTS.md`, `.github/PULL_REQUEST_TEMPLATE.md`
- An in-flight plan doc the user is working from

Pick the docs that are actually relevant to what the change touches —
don't dump every markdown file. Skip changelogs, license files, install
guides, and giant logs. Limits are 50 files / 200KB total / 100KB per file;
oversized, binary, or missing files are skipped with a notice surfaced to
the reviewer.

## Plan reviews specifically

`review_plan` and `review_oracle` also accept `context_files` (with
`repo_path`) — use this when reviewing a design against the codebase the
plan will land in. Pass the architecture doc, the existing module the plan
modifies, and any in-flight related plans.

## Output

Multi-model reviews wait for the entire panel and return one markdown
section per reviewer, headed by model + persona (e.g. `# Review by
GPT-5.5 Pro — architect persona`). If a panel member fails, its
persona is covered by a lightweight fallback model (Claude Haiku 4.5 or
Gemini 3.5 Flash) and the section header discloses the substitution.
When `model="all"`, expect to synthesize across the panel yourself; do not
just paste the raw output to the user — surface the strongest agreed-upon
findings and arbitrate disagreements.
"""

mcp = FastMCP("CodeReview", instructions=SERVER_INSTRUCTIONS)

PLAN_MAX_TOKENS = 16384

def _compose_extra_body(model_name: str, use_reasoning: bool = False) -> dict | None:
    extra_body = get_model_extra_body(model_name)
    if use_reasoning:
        extra_body.update(get_reasoning_config(model_name))
    return extra_body or None


class _Progress:
    """Monotonically increasing progress tracker. Null-safe and exception-safe."""

    def __init__(self, ctx: Context | None, total: int):
        self._ctx = ctx
        self.total = total
        self._step = 0

    async def update(self, message: str) -> None:
        self._step += 1
        if self._ctx is None:
            return
        try:
            await self._ctx.report_progress(self._step, self.total, message)
        except Exception:
            log.debug("Progress update failed", exc_info=True)


async def _do_single_review(
    content: str, model_name: str, system_prompt: str, prompt: str,
    use_reasoning: bool = False,
    max_tokens: int | None = None,
) -> tuple[str, str]:
    """Run a single model review. Returns (model_name, result_text)."""
    model_id = resolve_model(model_name)
    extra_body = _compose_extra_body(model_name, use_reasoning=use_reasoning)
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


async def _load_project_docs(
    repo_path: str,
    context_files: list[str] | None,
) -> str:
    """Read optional context files and redact any secrets before returning."""
    if not context_files:
        return ""
    docs_text, skipped = await read_context_files(repo_path, context_files)
    if skipped:
        log.info("Context files skipped: %s", skipped)
    if not docs_text:
        return ""
    docs_text, doc_findings = await asyncio.to_thread(redact_secrets, docs_text)
    if doc_findings:
        log.warning("Redacted %d potential secret(s) from context files", len(doc_findings))
    return docs_text


async def _do_review(
    content: str, model: str, focus: str, progress: _Progress,
    context: str = "",
    project_docs: str = "",
) -> str:
    model = model or settings.default_model
    content, findings = await asyncio.to_thread(redact_secrets, content)
    if findings:
        log.warning("Redacted %d potential secret(s) before sending to LLM", len(findings))
        warning = "\n".join(f"  - {f['type']} (line {f['line_number']})" for f in findings)
        context += f"\n\n⚠️ NOTICE: {len(findings)} potential secret(s) were redacted before sending:\n{warning}"
    prompt = format_review_request(content, focus=focus, context=context, project_docs=project_docs)

    if model == "all":
        result = await _do_multi_model_review(prompt, get_review_system_prompt, progress=progress)
        await progress.update("Review complete")
        return result

    model_id = resolve_model(model)
    display = MODEL_DISPLAY_NAMES.get(model, model_id)
    system_prompt = get_review_system_prompt(model)
    persona = get_persona(model) or "default"
    log.info("Sending review request: model=%s, persona=%s, focus=%s, content_len=%d",
             model_id, persona, focus, len(content))
    await progress.update(f"Sending to {display} ({persona}) for review...")
    t0 = time.monotonic()
    result = await get_review(
        prompt, system_prompt, model_id,
        extra_body=_compose_extra_body(model),
    )
    elapsed = time.monotonic() - t0
    log.info("Review completed in %.1fs, response_len=%d", elapsed, len(result))
    await progress.update(f"Review complete ({elapsed:.0f}s)")
    return result


async def _do_multi_model_review(
    prompt: str,
    system_prompt_fn: Callable[[str], str],
    use_reasoning: bool = False,
    max_tokens: int | None = None,
    progress: _Progress | None = None,
) -> str:
    """Fan out review to all models in ALL_REVIEW_MODELS concurrently.

    Each model receives the system prompt returned by `system_prompt_fn(model_name)`,
    so a multi-model panel can mix personas (architect / detail / simplicity /
    pragmatist) rather than asking every model the same generic question.

    Waits for the whole panel — no quorum, no cancellation. A member whose
    review fails is retried once on its FALLBACK_MODELS entry with the same
    persona prompt (and default privacy routing), so every persona is
    represented unless the fallback fails too. Returns Markdown with one
    section per reviewer; fallback sections disclose the substitution in the
    header. Synthesis across the panel is left to the caller (typically the
    Claude agent invoking this MCP), which already has the originating context.
    """
    panel_size = len(ALL_REVIEW_MODELS)
    log.info("Starting multi-model review across %d models (waiting for all): %s",
             panel_size, ALL_REVIEW_MODELS)
    t0 = time.monotonic()

    tasks = {
        asyncio.create_task(
            _do_single_review(
                "", model_name, system_prompt_fn(model_name), prompt,
                use_reasoning=use_reasoning,
                max_tokens=max_tokens,
            )
        ): model_name
        for model_name in ALL_REVIEW_MODELS
    }

    sections = []
    errors = []
    fallback_tasks: list[asyncio.Task] = []

    async def _fallback_review(slot: str, fallback_id: str) -> tuple[str, str, str]:
        """Re-run a failed slot's persona on its fallback model.

        extra_body=None on purpose: fallbacks run with the client's default
        privacy routing and no reasoning tuning — never the primary slot's
        provider pins (e.g. the fable ZDR exemption).
        """
        try:
            text = await get_review(
                prompt, system_prompt_fn(slot), fallback_id,
                extra_body=None, max_tokens=max_tokens,
            )
        except Exception as e:
            log.error("Fallback %s for slot %s failed: %s", fallback_id, slot, e)
            text = f"Error: Fallback review with {fallback_id} failed — {e}"
        return slot, fallback_id, text

    for coro in asyncio.as_completed(tasks.keys()):
        try:
            result = await coro
        except Exception as e:
            errors.append(f"Unexpected error: {e}")
            continue

        model_name, review_text = result
        display_name = MODEL_DISPLAY_NAMES.get(model_name, model_name)

        persona = get_persona(model_name)
        persona_label = f" — {persona} persona" if persona else ""

        if review_text.startswith("Error:"):
            fallback_id = FALLBACK_MODELS.get(model_name)
            if fallback_id:
                fb_display = FALLBACK_DISPLAY_NAMES.get(fallback_id, fallback_id)
                errors.append(
                    f"{display_name}{persona_label}: {review_text} (fell back to {fb_display})"
                )
                # Launch immediately so the fallback overlaps still-running primaries.
                fallback_tasks.append(
                    asyncio.create_task(_fallback_review(model_name, fallback_id))
                )
            else:
                errors.append(f"{display_name}{persona_label}: {review_text}")
        else:
            sections.append(f"---\n\n# Review by {display_name}{persona_label}\n\n{review_text}")
            if progress:
                await progress.update(
                    f"{display_name} complete ({len(sections)}/{panel_size})",
                )

    for coro in asyncio.as_completed(fallback_tasks):
        slot, fallback_id, review_text = await coro
        display_name = MODEL_DISPLAY_NAMES.get(slot, slot)
        fb_display = FALLBACK_DISPLAY_NAMES.get(fallback_id, fallback_id)
        persona = get_persona(slot)
        persona_label = f" — {persona} persona" if persona else ""

        if review_text.startswith("Error:"):
            errors.append(f"{fb_display} (fallback for {display_name}){persona_label}: {review_text}")
        else:
            sections.append(
                f"---\n\n# Review by {fb_display} (fallback for {display_name})"
                f"{persona_label}\n\n{review_text}"
            )
            if progress:
                await progress.update(
                    f"{fb_display} (fallback for {display_name}) complete "
                    f"({len(sections)}/{panel_size})",
                )

    elapsed = time.monotonic() - t0
    log.info("Multi-model review completed in %.1fs (%d sections, %d fallbacks launched, %d failure notes)",
             elapsed, len(sections), len(fallback_tasks), len(errors))

    parts = []
    if errors:
        error_block = "\n".join(f"- {e}" for e in errors)
        parts.append(f"⚠️ **Some models failed:**\n{error_block}\n")
    parts.extend(sections)

    if not sections:
        return "Error: All models failed.\n\n" + "\n".join(f"- {e}" for e in errors)

    return "\n\n".join(parts)


async def _prepare_diff(diff: str) -> str:
    raw_len = len(diff)
    diff = filter_binary_diffs(diff)
    diff = truncate_diff(diff, settings.max_diff_chars)
    log.info("Diff prepared: raw=%d chars, after_filter=%d chars", raw_len, len(diff))
    return diff


@mcp.tool(
    description="""Review current working tree changes (staged + unstaged diff).

    Args:
        repo_path: Path to the git repository (defaults to current directory)
        model: Model to use for review. Options: gptpro, openai, claude, opus, all
        focus: Review focus. Options: all, security, architecture, edge_cases, style, abstractions
        context_files: Optional but recommended for non-trivial changes —
            paths (relative to repo_path) to markdown/text docs to attach as
            project context. Before calling, scan the repo for
            ARCHITECTURE.md / DESIGN.md / docs/ / CLAUDE.md / AGENTS.md /
            in-flight plan files and include the ones relevant to what the
            change touches, so the reviewer can evaluate the change against
            the project's stated goals instead of in isolation. Skip
            changelogs, install guides, and large logs. Max 50 files,
            200K chars total, 100KB per file.
    """
)
async def review_diff(
    repo_path: str = ".",
    model: str = "gptpro",
    focus: str = "all",
    context_files: list[str] | None = None,
    ctx: Context | None = None,
) -> str:
    log.info("review_diff called: repo_path=%s, model=%s, focus=%s, context_files=%s",
             repo_path, model, focus, context_files)
    total = 2 + (len(ALL_REVIEW_MODELS) + 1 if model == "all" else 2)
    progress = _Progress(ctx, total)
    try:
        await progress.update("Validating repository...")
        if not await validate_repo(repo_path):
            return f"Error: '{repo_path}' is not a git repository."
        diff = await get_working_diff(repo_path)
        if not diff.strip():
            log.info("review_diff: no working tree changes found")
            return "No working tree changes found. Nothing to review."
        await progress.update("Preparing diff...")
        diff = await _prepare_diff(diff)
        project_docs = await _load_project_docs(repo_path, context_files)
        return await _do_review(
            diff, model, focus, progress,
            context="Working tree diff (staged + unstaged changes)",
            project_docs=project_docs,
        )
    except (GitError, ValueError) as e:
        log.error("review_diff failed: %s", e)
        return f"Error: {e}"


@mcp.tool(
    description="""Review a specific commit by SHA.

    Args:
        repo_path: Path to the git repository (defaults to current directory)
        sha: Commit SHA to review (defaults to HEAD)
        model: Model to use for review. Options: gptpro, openai, claude, opus, all
        focus: Review focus. Options: all, security, architecture, edge_cases, style, abstractions
        context_files: Optional but recommended for non-trivial changes —
            paths (relative to repo_path) to markdown/text docs to attach as
            project context. Before calling, scan the repo for
            ARCHITECTURE.md / DESIGN.md / docs/ / CLAUDE.md / AGENTS.md /
            in-flight plan files and include the ones relevant to what the
            change touches, so the reviewer can evaluate the change against
            the project's stated goals instead of in isolation. Skip
            changelogs, install guides, and large logs. Max 50 files,
            200K chars total, 100KB per file.
    """
)
async def review_commit(
    repo_path: str = ".",
    sha: str = "HEAD",
    model: str = "gptpro",
    focus: str = "all",
    context_files: list[str] | None = None,
    ctx: Context | None = None,
) -> str:
    log.info("review_commit called: repo_path=%s, sha=%s, model=%s, focus=%s, context_files=%s",
             repo_path, sha, model, focus, context_files)
    total = 2 + (len(ALL_REVIEW_MODELS) + 1 if model == "all" else 2)
    progress = _Progress(ctx, total)
    try:
        await progress.update("Validating repository...")
        if not await validate_repo(repo_path):
            return f"Error: '{repo_path}' is not a git repository."
        diff = await get_commit_diff(repo_path, sha)
        if not diff.strip():
            log.info("review_commit: no changes in commit %s", sha)
            return f"No changes found in commit {sha}."
        await progress.update("Preparing diff...")
        diff = await _prepare_diff(diff)
        project_docs = await _load_project_docs(repo_path, context_files)
        return await _do_review(
            diff, model, focus, progress,
            context=f"Commit {sanitize_context(sha)}",
            project_docs=project_docs,
        )
    except (GitError, ValueError) as e:
        log.error("review_commit failed: %s", e)
        return f"Error: {e}"


@mcp.tool(
    description="""Review all changes on a branch compared to a base branch.

    Args:
        repo_path: Path to the git repository (defaults to current directory)
        branch: Branch to review
        base: Base branch to compare against (defaults to main)
        model: Model to use for review. Options: gptpro, openai, claude, opus, all
        focus: Review focus. Options: all, security, architecture, edge_cases, style, abstractions
        context_files: Optional but recommended for non-trivial changes —
            paths (relative to repo_path) to markdown/text docs to attach as
            project context. Before calling, scan the repo for
            ARCHITECTURE.md / DESIGN.md / docs/ / CLAUDE.md / AGENTS.md /
            in-flight plan files and include the ones relevant to what the
            change touches, so the reviewer can evaluate the change against
            the project's stated goals instead of in isolation. Skip
            changelogs, install guides, and large logs. Max 50 files,
            200K chars total, 100KB per file.
    """
)
async def review_branch(
    branch: str,
    repo_path: str = ".",
    base: str = "main",
    model: str = "gptpro",
    focus: str = "all",
    context_files: list[str] | None = None,
    ctx: Context | None = None,
) -> str:
    log.info("review_branch called: branch=%s, base=%s, repo_path=%s, model=%s, focus=%s, context_files=%s",
             branch, base, repo_path, model, focus, context_files)
    total = 2 + (len(ALL_REVIEW_MODELS) + 1 if model == "all" else 2)
    progress = _Progress(ctx, total)
    try:
        await progress.update("Validating repository...")
        if not await validate_repo(repo_path):
            return f"Error: '{repo_path}' is not a git repository."
        diff = await get_branch_diff(repo_path, branch, base)
        if not diff.strip():
            log.info("review_branch: no changes between %s and %s", base, branch)
            return f"No changes found between {base} and {branch}."
        await progress.update("Preparing diff...")
        diff = await _prepare_diff(diff)
        project_docs = await _load_project_docs(repo_path, context_files)
        return await _do_review(
            diff, model, focus, progress,
            context=f"Branch {sanitize_context(branch)} vs {sanitize_context(base)}",
            project_docs=project_docs,
        )
    except (GitError, ValueError) as e:
        log.error("review_branch failed: %s", e)
        return f"Error: {e}"


@mcp.tool(
    description="""Review a single file in its entirety.

    Args:
        file_path: Path to the file relative to repo_path
        repo_path: Path to the git repository (defaults to current directory)
        model: Model to use for review. Options: gptpro, openai, claude, opus, all
        focus: Review focus. Options: all, security, architecture, edge_cases, style, abstractions
        context_files: Optional but recommended for non-trivial changes —
            paths (relative to repo_path) to markdown/text docs to attach as
            project context. Before calling, scan the repo for
            ARCHITECTURE.md / DESIGN.md / docs/ / CLAUDE.md / AGENTS.md /
            in-flight plan files and include the ones relevant to what the
            change touches, so the reviewer can evaluate the change against
            the project's stated goals instead of in isolation. Skip
            changelogs, install guides, and large logs. Max 50 files,
            200K chars total, 100KB per file.
    """
)
async def review_file(
    file_path: str,
    repo_path: str = ".",
    model: str = "gptpro",
    focus: str = "all",
    context_files: list[str] | None = None,
    ctx: Context | None = None,
) -> str:
    log.info("review_file called: file_path=%s, repo_path=%s, model=%s, focus=%s, context_files=%s",
             file_path, repo_path, model, focus, context_files)
    total = 2 + (len(ALL_REVIEW_MODELS) + 1 if model == "all" else 2)
    progress = _Progress(ctx, total)
    try:
        await progress.update("Validating repository...")
        if not await validate_repo(repo_path):
            return f"Error: '{repo_path}' is not a git repository."
        content = await get_file_content(repo_path, file_path)
        if not content.strip():
            log.info("review_file: file '%s' is empty", file_path)
            return f"File '{file_path}' is empty. Nothing to review."
        await progress.update("Reading file...")
        content = truncate_diff(content, settings.max_diff_chars)
        project_docs = await _load_project_docs(repo_path, context_files)
        return await _do_review(
            content, model, focus, progress,
            context=f"Full file review: {sanitize_context(file_path)}",
            project_docs=project_docs,
        )
    except (GitError, ValueError) as e:
        log.error("review_file failed: %s", e)
        return f"Error: {e}"


async def _do_plan_review(
    plan: str, codebase_context: str, model: str, progress: _Progress,
    project_docs: str = "",
) -> str:
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

    prompt = format_plan_review_request(plan, codebase_context, project_docs=project_docs)

    if model == "all":
        result = await _do_multi_model_review(
            prompt, get_plan_review_system_prompt,
            use_reasoning=True, max_tokens=PLAN_MAX_TOKENS, progress=progress,
        )
        await progress.update("Plan review complete")
        return result

    model_id = resolve_model(model)
    display = MODEL_DISPLAY_NAMES.get(model, model_id)
    extra_body = _compose_extra_body(model, use_reasoning=True)
    system_prompt = get_plan_review_system_prompt(model)
    persona = get_persona(model) or "default"

    await progress.update(f"Sending plan to {display} ({persona}) for review...")
    t0 = time.monotonic()
    result = await get_review(
        prompt, system_prompt, model_id,
        extra_body=extra_body,
        max_tokens=PLAN_MAX_TOKENS,
    )
    elapsed = time.monotonic() - t0
    log.info("Plan review completed in %.1fs, response_len=%d", elapsed, len(result))
    await progress.update(f"Plan review complete ({elapsed:.0f}s)")
    return result


@mcp.tool(
    description="""Review a technical plan or design document.

    Evaluates the plan for first-principles thinking, simplicity (KISS),
    security risks, edge cases, and architecture quality.

    Uses maximum reasoning effort for the deepest possible analysis.

    Args:
        plan: The plan or design document text to review
        codebase_context: Optional relevant code snippets for grounding the review
        model: Model to use for review. Options: gptpro, openai, claude, opus, all
        repo_path: Path to the git repository — required only if context_files is set
        context_files: Optional but recommended for plan reviews — paths
            (relative to repo_path) to markdown/text docs that ground the
            plan in the codebase it will land in. Scan for ARCHITECTURE.md
            / DESIGN.md / docs/ / CLAUDE.md / AGENTS.md / related in-flight
            plans, and attach the relevant ones. Skip changelogs and
            install guides. Max 50 files, 200K chars total, 100KB per file.
    """
)
async def review_plan(
    plan: str,
    codebase_context: str = "",
    model: str = "gptpro",
    repo_path: str = ".",
    context_files: list[str] | None = None,
    ctx: Context | None = None,
) -> str:
    log.info("review_plan called: model=%s, plan_len=%d, context_files=%s",
             model, len(plan), context_files)
    total = 1 + (len(ALL_REVIEW_MODELS) + 1 if model == "all" else 2)
    progress = _Progress(ctx, total)
    try:
        await progress.update("Preparing plan review...")
        project_docs = await _load_project_docs(repo_path, context_files)
        return await _do_plan_review(
            plan, codebase_context, model, progress,
            project_docs=project_docs,
        )
    except (GitError, ValueError) as e:
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
        model: Model to use for review. Options: gptpro, openai, claude, opus, all
        repo_path: Path to the git repository — required only if context_files is set
        context_files: Optional but recommended for plan reviews — paths
            (relative to repo_path) to markdown/text docs that ground the
            plan in the codebase it will land in. Scan for ARCHITECTURE.md
            / DESIGN.md / docs/ / CLAUDE.md / AGENTS.md / related in-flight
            plans, and attach the relevant ones. Skip changelogs and
            install guides. Max 50 files, 200K chars total, 100KB per file.
    """
)
async def review_oracle(
    plan: str,
    codebase_context: str = "",
    model: str = "gptpro",
    repo_path: str = ".",
    context_files: list[str] | None = None,
    ctx: Context | None = None,
) -> str:
    log.info("review_oracle called: model=%s, plan_len=%d, context_files=%s",
             model, len(plan), context_files)
    total = 1 + (len(ALL_REVIEW_MODELS) + 1 if model == "all" else 2)
    progress = _Progress(ctx, total)
    try:
        await progress.update("Preparing plan review...")
        project_docs = await _load_project_docs(repo_path, context_files)
        return await _do_plan_review(
            plan, codebase_context, model, progress,
            project_docs=project_docs,
        )
    except (GitError, ValueError) as e:
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
