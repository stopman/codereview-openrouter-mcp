# codereview-openrouter-mcp

An MCP server that gives your AI coding assistant a **staff/principal-engineer-level review panel for plans and designs** — all through a single OpenRouter API key.

Before your assistant writes code, its plan gets scrutinized by **GPT-5.6 Sol**, **GPT-5.3 Codex**, **Claude Sonnet 5**, **Claude Opus 4.8**, and **Grok 4.5** — each with a distinct reviewer persona. Catch the flawed assumption before it becomes a flawed implementation.

## Why this exists

Your AI coding assistant writes plans, then turns them into code. But who reviews the plan?

- **One API key** (OpenRouter) gives you access to every major model
- **You pick the reviewer** per-request — or run the whole panel with `model="all"`
- **Five personas, not five echoes** — architect, detail-oriented, first-principles simplicity, production pragmatist + security, and generalist lenses (editable in [`PERSONAS.md`](PERSONAS.md))
- **Maximum reasoning effort** — every plan review runs at the deepest reasoning tier each model supports
- **Secrets are redacted** before your plan leaves your machine (via [detect-secrets](https://github.com/Yelp/detect-secrets))
- **Ground the review in your repo** — attach architecture docs and code snippets so the panel judges the plan against your project's stated goals

This server is plan/design review only — it reviews what you're *about* to build, not diffs of what you built. (Earlier versions also reviewed diffs/commits/branches; that was dropped in favor of doing one thing well.)

## Quick start

### 1. Get an OpenRouter API key

Sign up at [openrouter.ai](https://openrouter.ai) and grab your API key.

### 2. Add to your AI coding assistant

**Claude Code** — add to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "codereview": {
      "command": "uv",
      "args": ["run", "codereview-openrouter-mcp"],
      "env": {
        "OPENROUTER_API_KEY": "your-key-here"
      }
    }
  }
}
```

Or add it via the CLI:

```bash
claude mcp add codereview -- uv run codereview-openrouter-mcp
```

**Amp** — add the same `.mcp.json` configuration to your project root. Amp discovers `review_oracle` as its oracle tool automatically.

Then set `OPENROUTER_API_KEY` in your environment.

### 3. Use it

Once the MCP server is configured, just ask your assistant in natural language:

> "Review my plan for the new auth system"

> "Here's my design doc for the migration — review it with all models"

> "Review my caching plan against README.md and docs/perf-budget.md"

> "Run this plan past the panel before you start"

Your assistant maps these to the MCP tools automatically — you don't need to know the tool names or parameter syntax.

## Tools

### `review_plan` — Review a technical plan or design document

Evaluates a plan for first-principles thinking, simplicity (KISS), security risks, edge cases, and architecture quality. Uses maximum reasoning effort for the deepest analysis.

```
review_plan(plan="We plan to...", codebase_context="", model="sol", repo_path=".", context_files=["docs/roadmap.md"])
```

### `review_oracle` — Alias for `review_plan`

Identical to `review_plan`. Exists for discoverability by AI coding assistants that use the term "oracle" (e.g., Amp).

```
review_oracle(plan="We plan to...", codebase_context="", model="sol")
```

### Grounding the review

Two ways to give the panel real project context:

- **`codebase_context`** — paste the code snippets the plan will modify
- **`context_files`** — a list of paths (relative to `repo_path`) to markdown/text docs (architecture briefs, READMEs, ADRs, related plans). The reviewer models read those docs alongside the plan, so they can evaluate it against the project's stated goals instead of in isolation.

> "Review my plan for the payments migration — make sure it aligns with docs/payments-design.md"

Limits for `context_files`: up to 50 files, 200KB total, 100KB per file. Binary content and path-traversal attempts are skipped with a notice surfaced to the reviewer model. Secrets in context files go through the same redaction pipeline as the plan itself.

## Models

| Name | Model | Best for |
|---|---|---|
| `sol` | OpenAI GPT-5.6 Sol | Architect reviews, deep reasoning (default) |
| `openai` | OpenAI GPT-5.3 Codex | Detail-oriented, deep code understanding |
| `claude` | Anthropic Claude Sonnet 5 | First-principles simplicity |
| `opus` | Anthropic Claude Opus 4.8 | Production pragmatism + security reviews |
| `grok` | xAI Grok 4.5 | Generalist breadth |
| `glm` | Z.ai GLM 5.2 (US-hosted providers only) | Generalist breadth, cheap and fast — benched from the panel, explicit picks only |
| `all` | Panel: GPT-5.6 Sol + GPT-5.3 + Claude Sonnet 5 + Claude Opus 4.8 + Grok 4.5 | Multi-perspective review |

Pass `model="sol"`, `model="openai"`, `model="claude"`, `model="opus"`, `model="grok"`, `model="glm"`, or `model="all"` to either tool. Default is `sol`.

With `model="all"` reviews are fanned out to all five panel members concurrently and the server waits for the whole panel (wall-clock time is set by the slowest reviewer). If a panel member errors out, its persona is re-run on a lightweight fallback model (Claude Haiku 4.5 or Gemini 3.5 Flash — always cross-vendor from the primary) and the substitution is disclosed in the review's section header.

## Customizing reviewer personas

The system prompts for all five personas live in [`PERSONAS.md`](PERSONAS.md) at the repo root — one section per persona, delimited by `## PERSONA: <persona>.plan` marker lines (e.g. `## PERSONA: architect.plan`). Edit the text under a marker to change what that reviewer is told to do.

- **Edits apply live**: the server re-reads the file whenever it changes — no restart needed. The next review uses your updated prompts.
- **Safe to experiment**: if a save is malformed (missing/duplicate/unknown section), the running server keeps the last good version and logs a warning. A broken file at startup fails loudly with the exact problem named.
- Which model gets which persona is mapped in `codereview_openrouter_mcp/prompts.py` (`PERSONA_MAP`).

## Review output

Every plan review follows a structured format (personas vary their body sections):

```markdown
## Plan Review Summary
**Severity**: CRITICAL / HIGH / MEDIUM / LOW / CLEAN
**Concerns Found**: 3

### First-Principles Assessment
### Simplicity (KISS) Assessment
### Security Concerns
### Edge Cases & Failure Modes
### Architecture & Design
### What's Strong
### Overall Verdict
```

With `model="all"`, the response contains one `# Review by <model> — <persona> persona` section per panel member; your assistant synthesizes across them — surfacing agreed-upon findings and arbitrating disagreements.

## Secret scanning

Before any plan text, codebase context, or context file is sent to OpenRouter, it's scanned by [Yelp's detect-secrets](https://github.com/Yelp/detect-secrets) library. If secrets are found:

1. The lines containing secrets are **redacted** (replaced with `[REDACTED]`)
2. The review proceeds with the sanitized content

This catches AWS keys, GitHub tokens, passwords, private keys, connection strings, and more.

## Configuration

| Environment variable | Required | Default | Description |
|---|---|---|---|
| `OPENROUTER_API_KEY` | Yes | — | Your OpenRouter API key |
| `DEFAULT_MODEL` | No | `sol` | Default model when none specified |
| `LOG_LEVEL` | No | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `ALLOWED_REPO_ROOTS` | No | — | Comma-separated list of allowed repository root paths for `context_files` reads. If unset, any path is accessible |
| `OPENROUTER_ZDR` | No | `true` | Route only to Zero-Data-Retention provider endpoints. Strict ZDR is the default and cannot be weakened per-model: every panel model is ZDR-routable, and requests always carry `zdr: true` unless this env var disables it globally. GLM 5.2 additionally routes only to US-headquartered providers via a `provider.only` allowlist, preferring Together → Fireworks → Novita (`provider.order`) with the rest of the allowlist as fallback. `data_collection: "deny"` (no training on your data) is always enforced regardless |

## Development

```bash
git clone https://github.com/stopman/codereview-openrouter-mcp.git
cd codereview-openrouter-mcp
uv run pytest tests/ -v
```

## How it works

```
AI Assistant  -->  MCP Server   -->  detect-secrets      -->  OpenRouter API  -->  LLM panel
 (plan text)       review_plan/      (redact secrets in       (ZDR routing,       (5 personas,
                   review_oracle      plan + docs)             no training)        max reasoning)
                        |
                  context_files
               (repo docs, capped +
                traversal-safe)
```

1. Your AI assistant calls `review_plan` (or `review_oracle`) with the plan text
2. Optional `context_files` are read from the repo (size-capped, path-traversal-safe) and `codebase_context` snippets attached
3. `detect-secrets` scans and redacts secrets from all of it
4. The sanitized content is sent to OpenRouter with a persona-specific staff-engineer system prompt and maximum reasoning effort
5. The chosen model's review is returned to your assistant
6. With `model="all"`, steps 4–5 happen concurrently across the whole panel; failed members are covered by cross-vendor fallbacks

## License

MIT
