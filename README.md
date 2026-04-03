# codereview-openrouter-mcp

An MCP server that gives your AI coding assistant access to **staff/principal-engineer-level code review** from the world's best LLMs — all through a single OpenRouter API key.

Pick your reviewer per-request: **Gemini 3.1 Pro**, **GPT-5.3 Codex**, **Claude Opus 4.6**, or **DeepSeek R1**. Compare opinions. Get a second (or third, or fourth) opinion on your code before it ships.

## Why this exists

Your AI coding assistant writes code. But who reviews it?

Other code review MCP servers lock you into one model, require multiple API keys, or don't actually do LLM-powered review at all. This one:

- **One API key** (OpenRouter) gives you access to every major model
- **You pick the reviewer** per-request — compare what Gemini thinks vs Claude vs OpenAI
- **Secrets are redacted** before your code leaves your machine (via [detect-secrets](https://github.com/Yelp/detect-secrets))
- **Staff engineer prompt** — not generic "review this code" but a structured 6-dimension review covering security, architecture, edge cases, implementation, style, and abstractions

## Quick start

### 1. Get an OpenRouter API key

Sign up at [openrouter.ai](https://openrouter.ai) and grab your API key.

### 2. Add to Claude Code

Add to your project's `.mcp.json`:

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

Then set `OPENROUTER_API_KEY` in your environment.

### 3. Use it

Ask Claude Code to review your work:

> "Use codereview to review my working changes with Gemini"

> "Review the last commit using Claude"

> "Do a security-focused review of server.py with DeepSeek"

## Tools

### `review_diff` — Review working tree changes

Reviews your current staged + unstaged changes (what you'd see in `git diff HEAD`).

```
review_diff(repo_path=".", model="gemini", focus="all")
```

**Example prompt:** *"Review my current changes before I commit"*

### `review_commit` — Review a specific commit

Reviews any commit by SHA.

```
review_commit(repo_path=".", sha="HEAD", model="openai", focus="security")
```

**Example prompt:** *"Review the last commit using OpenAI, focus on security"*

### `review_branch` — Review a branch

Reviews all changes on a branch compared to a base branch.

```
review_branch(branch="feature/auth", repo_path=".", base="main", model="claude")
```

**Example prompt:** *"Review the feature/auth branch against main using Claude"*

### `review_file` — Review a single file

Full-file review for when you want a complete assessment.

```
review_file(file_path="src/auth.py", repo_path=".", model="deepseek", focus="architecture")
```

**Example prompt:** *"Review src/auth.py with DeepSeek, focus on architecture"*

## Models

| Name | Model | Best for |
|---|---|---|
| `gemini` | Google Gemini 3.1 Pro | Large diffs, fast turnaround |
| `openai` | OpenAI GPT-5.3 Codex | Deep code understanding |
| `claude` | Anthropic Claude Opus 4.6 | Nuanced architectural feedback |
| `deepseek` | DeepSeek R1 | Reasoning-heavy analysis |

Pass `model="gemini"`, `model="openai"`, `model="claude"`, or `model="deepseek"` to any tool. Default is `gemini`.

## Focus areas

Narrow the review to what matters most:

| Focus | What it covers |
|---|---|
| `all` | Full 6-dimension review (default) |
| `security` | Injection, auth flaws, secrets exposure, input validation |
| `architecture` | Design patterns, coupling, scalability, abstractions |
| `edge_cases` | Boundary inputs, race conditions, error handling, failure modes |
| `style` | Naming, readability, dead code, consistency |
| `abstractions` | API design, leaky abstractions, over/under-engineering |

## Review output

Every review follows a structured format:

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

## Multi-model comparison

The real power is comparing reviewers. Ask for the same review from multiple models:

> "Review the last commit with both Gemini and OpenAI"

You'll get two independent expert opinions. Different models catch different things — Gemini might flag a performance issue that OpenAI misses, while Claude spots an architectural concern neither caught.

## Secret scanning

Before any code is sent to OpenRouter, it's scanned by [Yelp's detect-secrets](https://github.com/Yelp/detect-secrets) library. If secrets are found:

1. The lines containing secrets are **redacted** (replaced with `[REDACTED]`)
2. A warning is appended to the review context listing what was found
3. The review proceeds with the sanitized content

This catches AWS keys, GitHub tokens, passwords, private keys, connection strings, and more.

## Configuration

| Environment variable | Required | Default | Description |
|---|---|---|---|
| `OPENROUTER_API_KEY` | Yes | — | Your OpenRouter API key |
| `DEFAULT_MODEL` | No | `gemini` | Default model when none specified |
| `MAX_DIFF_CHARS` | No | `100000` | Max characters before truncation |

## Development

```bash
git clone https://github.com/stopman/codereview-openrouter-mcp.git
cd codereview-openrouter-mcp
uv run pytest tests/ -v
```

## How it works

```
Claude Code  -->  MCP Server  -->  detect-secrets (redact)  -->  OpenRouter API  -->  LLM
                  (4 tools)        (scan & redact secrets)       (unified routing)    (Gemini/OpenAI/Claude/DeepSeek)
                      |
                   git ops
              (diff/show/branch)
```

1. Claude Code calls an MCP tool (e.g., `review_diff`)
2. The server runs `git` to extract the relevant code/diff
3. `detect-secrets` scans and redacts any secrets found
4. The sanitized code is sent to OpenRouter with a staff-engineer system prompt
5. The chosen model's review is returned to Claude Code

## License

MIT
