# codereview-openrouter-mcp

An MCP server that gives your AI coding assistant access to **staff/principal-engineer-level code review** from the world's best LLMs — all through a single OpenRouter API key.

Pick your reviewer per-request: **Gemini 3.5 Flash**, **GPT-5.3 Codex**, **Claude Opus 4.8**, **DeepSeek V4 Pro**, **Fusion (Budget)**, **GLM-5.2**, or **Kimi K2.6**. Compare opinions. Get a second (or third) opinion on your code before it ships.

## Why this exists

Your AI coding assistant writes code. But who reviews it?

Other code review MCP servers lock you into one model, require multiple API keys, or don't actually do LLM-powered review at all. This one:

- **One API key** (OpenRouter) gives you access to every major model
- **You pick the reviewer** per-request — compare what Gemini thinks vs Claude vs OpenAI vs DeepSeek vs Fusion
- **`model="all"`** fans out to all models in parallel and returns the first 3 responses — instant multi-perspective review
- **Secrets are redacted** before your code leaves your machine (via [detect-secrets](https://github.com/Yelp/detect-secrets))
- **Staff engineer prompt** — not generic "review this code" but a structured 6-dimension review covering security, architecture, edge cases, implementation, style, and abstractions
- **Plan/design review** — review technical plans and design documents, not just code

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

Once the MCP server is configured, just ask Claude Code in natural language. Here are example prompts organized by workflow:

#### Reviewing before you commit

> "Review my current changes before I commit"

> "Use codereview to review my working diff with Gemini"

> "Do a security-focused review of my staged changes"

#### Reviewing commits

> "Review the last commit using Claude"

> "Review commit abc123 with OpenAI, focus on edge cases"

> "Review the last commit with all models and compare their findings"

#### Reviewing branches / PRs

> "Review the feature/auth branch against main using Claude"

> "Review this branch with DeepSeek, focus on architecture"

#### Reviewing individual files

> "Do a security-focused review of server.py with OpenAI"

> "Review src/auth.py with Kimi, focus on abstractions"

#### Reviewing plans and designs

> "Review my plan for the new auth system"

> "Here's my design doc for the migration — review it with all models"

#### Multi-model comparison

> "Review the last commit with all models"

> "Review my changes with both Gemini and Claude and compare what they find"

#### Specifying focus areas

> "Review my diff, focus on security only"

> "Review this file with OpenAI, focus on edge_cases"

> "Architecture-focused review of the feature/payments branch"

#### Attaching project docs for context

Every review tool accepts an optional `context_files` parameter — a list of paths (relative to the repo) to markdown/text files that describe the project. The reviewer models will read those docs alongside the code, so they can evaluate the change against the project's stated goals, architecture, or current plan.

> "Review my diff with all models, and include ARCHITECTURE.md and docs/plan-q2.md as context"

> "Review the feature/payments branch — make sure it aligns with docs/payments-design.md"

> "Review my caching plan against README.md and docs/perf-budget.md"

Limits: up to 50 files, 200KB total across all context files, 100KB per file. Binary content and path-traversal attempts are skipped with a notice surfaced to the reviewer model. Secrets in context files go through the same redaction pipeline as the code itself.

Claude Code will map these natural-language requests to the appropriate MCP tool calls automatically — you don't need to know the tool names or parameter syntax.

## Tools

All review tools accept an optional `context_files: list[str]` parameter — paths (relative to `repo_path`) to additional markdown/text docs (architecture briefs, READMEs, ADRs, design plans) to include as project context.

### `review_diff` — Review working tree changes

Reviews your current staged + unstaged changes (what you'd see in `git diff HEAD`).

```
review_diff(repo_path=".", model="gemini", focus="all", context_files=["ARCHITECTURE.md"])
```

**Example prompt:** *"Review my current changes before I commit"*

### `review_commit` — Review a specific commit

Reviews any commit by SHA.

```
review_commit(repo_path=".", sha="HEAD", model="openai", focus="security", context_files=["docs/threat-model.md"])
```

**Example prompt:** *"Review the last commit using OpenAI, focus on security"*

### `review_branch` — Review a branch

Reviews all changes on a branch compared to a base branch.

```
review_branch(branch="feature/auth", repo_path=".", base="main", model="claude", context_files=["docs/auth-design.md"])
```

**Example prompt:** *"Review the feature/auth branch against main using Claude"*

### `review_file` — Review a single file

Full-file review for when you want a complete assessment.

```
review_file(file_path="src/auth.py", repo_path=".", model="claude", focus="architecture", context_files=["README.md", "ARCHITECTURE.md"])
```

**Example prompt:** *"Review src/auth.py with Claude, focus on architecture"*

### `review_plan` — Review a technical plan or design document

Evaluates a plan for first-principles thinking, simplicity (KISS), security risks, edge cases, and architecture quality. Uses maximum reasoning effort for the deepest analysis.

```
review_plan(plan="We plan to...", codebase_context="", model="gemini", repo_path=".", context_files=["docs/roadmap.md"])
```

**Example prompt:** *"Review my plan for the database migration"*

### `review_oracle` — Alias for `review_plan`

Identical to `review_plan`. Exists for discoverability by AI coding assistants that use the term "oracle" (e.g., Amp).

```
review_oracle(plan="We plan to...", codebase_context="", model="gemini")
```

## Models

| Name | Model | Best for |
|---|---|---|
| `gemini` | Google Gemini 3.5 Flash | Large diffs, fast turnaround |
| `openai` | OpenAI GPT-5.3 Codex | Deep code understanding |
| `claude` | Anthropic Claude Opus 4.8 | First-principles simplicity, deepest reasoning |
| `deepseek` | DeepSeek V4 Pro | Cost-effective deep reasoning |
| `fusion` | OpenRouter Fusion (`openrouter/fusion`) with `fusion` preset `general-budget` | Budget multi-model synthesis |
| `glm` | Z.AI GLM-5.2 | Pragmatic production feedback |
| `kimi` | Kimi K2.6 | Long-horizon coding, multimodal |
| `all` | Panel: Gemini + GPT-5.3 + Claude Opus 4.8 + GLM-5.2 | Multi-perspective review |

Pass `model="gemini"`, `model="openai"`, `model="claude"`, `model="deepseek"`, `model="fusion"`, `model="glm"`, `model="kimi"`, or `model="all"` to any tool. Default is `gemini`.

When `model="all"` is used, reviews are fanned out to all models concurrently. The server returns as soon as the first 3 responses arrive; slower models are cancelled.

## Focus areas

Narrow the review to what matters most (applies to code review tools, not plan review):

| Focus | What it covers |
|---|---|
| `all` | Full 6-dimension review (default) |
| `security` | Injection, auth flaws, secrets exposure, input validation |
| `architecture` | Design patterns, coupling, scalability, abstractions |
| `edge_cases` | Boundary inputs, race conditions, error handling, failure modes |
| `style` | Naming, readability, dead code, consistency |
| `abstractions` | API design, leaky abstractions, over/under-engineering |

## Review output

### Code reviews

Every code review follows a structured format:

```markdown
## Code Review Summary
**Severity**: CRITICAL / HIGH / MEDIUM / LOW / CLEAN
**Issues Found**: 5

### Critical Issues
- [SECURITY] auth.py:42 — SQL injection via unsanitized input
  Recommendation: Use parameterized queries...

### Architecture & Design
### Edge Cases & Error Handling
### Implementation Details
### Code Style & Conventions
### Abstractions & API Design
### Positive Observations
### Overall Assessment
```

### Plan reviews

Plan reviews use a different structure:

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

## Multi-model comparison

The real power is comparing reviewers. Use `model="all"` or ask for multiple models:

> "Review the last commit with all models"

> "Review the last commit with both Gemini and OpenAI"

Different models catch different things — Gemini might flag a performance issue that OpenAI misses, while Claude spots an architectural concern neither caught.

## Secret scanning

Before any code is sent to OpenRouter, it's scanned by [Yelp's detect-secrets](https://github.com/Yelp/detect-secrets) library. If secrets are found:

1. The lines containing secrets are **redacted** (replaced with `[REDACTED]`)
2. A warning is appended to the review context listing what was found
3. The review proceeds with the sanitized content

This catches AWS keys, GitHub tokens, passwords, private keys, connection strings, and more. Secret scanning also applies to plan reviews.

## Configuration

| Environment variable | Required | Default | Description |
|---|---|---|---|
| `OPENROUTER_API_KEY` | Yes | — | Your OpenRouter API key |
| `DEFAULT_MODEL` | No | `gemini` | Default model when none specified |
| `MAX_DIFF_CHARS` | No | `500000` | Max characters before truncation |
| `LOG_LEVEL` | No | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `ALLOWED_REPO_ROOTS` | No | — | Comma-separated list of allowed repository root paths. If unset, all repos are accessible |
| `OPENROUTER_ZDR` | No | `true` | Route only to Zero-Data-Retention provider endpoints. Set `false` if a model has no ZDR endpoint and routing fails. `data_collection: "deny"` (no training on your data) is always enforced regardless |

## Development

```bash
git clone https://github.com/stopman/codereview-openrouter-mcp.git
cd codereview-openrouter-mcp
uv run pytest tests/ -v
```

## How it works

```
AI Assistant  -->  MCP Server  -->  detect-secrets (redact)  -->  OpenRouter API  -->  LLM(s)
                   (6 tools)        (scan & redact secrets)       (unified routing)    (Gemini/OpenAI/Claude/
                       |                                                                DeepSeek/Fusion/GLM/Kimi)
                    git ops
               (diff/show/branch)
```

1. Your AI assistant calls an MCP tool (e.g., `review_diff`, `review_plan`)
2. For code reviews, the server runs `git` to extract the relevant code/diff
3. `detect-secrets` scans and redacts any secrets found
4. The sanitized content is sent to OpenRouter with a staff-engineer system prompt
5. The chosen model's review is returned to your assistant
6. With `model="all"`, steps 4–5 happen concurrently across all models

## License

MIT
