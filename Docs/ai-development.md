# AI-Assisted Development

This repo uses two complementary systems for structured, agent-driven development, plus an autonomous Docker pipeline. This doc covers all three. For day-to-day human setup and ops, see [DEVELOPMENT.md](../DEVELOPMENT.md).

## Overview

This repo uses two complementary systems for structured, agent-driven development. Both are pre-configured — see [Setup for AI Development](#setup-for-ai-development) to get ready.

### Superpowers (interactive, in-session)

The [superpowers plugin](https://github.com/claude-plugins-official/superpowers) drives brainstorming, planning, implementation, and review **inside your Claude Code session**. Use it when you want collaborative control over each phase.

Key skills (invoke with the `Skill` tool):
- `superpowers:brainstorming` — explore requirements before building anything
- `superpowers:writing-plans` — create step-by-step implementation plans
- `superpowers:executing-plans` / `superpowers:subagent-driven-development` — implement from a plan
- `superpowers:verification-before-completion` — verify before claiming done
- `superpowers:requesting-code-review` — review completed work

### Archon (autonomous, isolated)

[Archon](https://github.com/coleam00/Archon) runs workflows in isolated git worktrees — fire-and-forget pipelines that produce PRs. Use it for well-scoped work you trust to run autonomously.

Run workflows with: `archon workflow run <name> "description"` or ask Claude Code: *"Use archon to fix issue #3"*

Key workflows:
- `archon-fix-github-issue` — investigate + fix + PR + review
- `archon-idea-to-pr` — feature idea to reviewed PR
- `archon-smart-pr-review` — adaptive complexity PR review
- `archon-piv-loop` — guided plan-implement-validate with human-in-the-loop

Run `archon workflow list` for the full catalog.

### When to Use Which

| Scenario | Tool |
|----------|------|
| You want to shape the design interactively | Superpowers |
| Well-defined issue or feature, hands-off | Archon |
| Bug investigation needing your input | Superpowers |
| PR review | Archon (`archon-smart-pr-review`) |
| Multi-step feature with checkpoints | Superpowers or Archon PIV loop |

### Backlog

Work items are tracked as [GitHub Issues](https://github.com/omniscient/markethawk/issues) with priority labels (`priority: must-have`, `priority: should-have`) and size labels (`size: S/M/L`).

## Setup for AI Development

These steps get a fresh clone ready for both human and AI-driven development. Claude Code agents can follow these instructions directly — if someone says "set everything up", run through this list.

### Prerequisites

Verify these are installed (the system won't work without them):

```bash
docker --version          # Docker Desktop (includes Compose)
git --version             # Git
gh --version              # GitHub CLI — required for Archon issue/PR automation
bun --version             # Bun runtime — required for Archon CLI
claude --version          # Claude Code CLI
pre-commit --version      # Pre-commit hook framework
```

**Install anything missing:**
- Docker Desktop: https://www.docker.com/products/docker-desktop
- GitHub CLI: `winget install GitHub.cli` (Windows) / `brew install gh` (macOS)
- Bun: `irm bun.sh/install.ps1 | iex` (Windows) / `curl -fsSL https://bun.sh/install | bash` (macOS/Linux)
- Claude Code: `npm install -g @anthropic-ai/claude-code`
- pre-commit: `pip install pre-commit` (macOS/Linux/Windows)

### Step 1 — Authenticate GitHub CLI

```bash
gh auth login              # Follow the prompts — needs repo scope at minimum
gh auth status             # Confirm: "Logged in to github.com"
```

### Step 2 — Environment and services

```bash
cp .env.example .env       # Then fill in API keys — see ../ENV_VARIABLES.md
docker-compose up -d       # Start all services
docker-compose exec backend python -m alembic upgrade head  # Apply migrations
```

### Step 2.5 — Install pre-commit hooks

```bash
pre-commit install    # registers hooks in .git/hooks/pre-commit
```

### Step 3 — Verify Archon

Archon is pre-configured in this repo (`.archon/config.yaml` + `.claude/skills/archon/`).

```bash
archon version             # Should show version + database type
archon workflow list       # Should list 20+ workflows
```

If `archon` is not found, install and link from the Archon source repo:
```bash
cd <archon-repo> && bun install && cd packages/cli && bun link
```

### Step 4 — Verify Claude Code plugins

Open Claude Code in this repo. The project settings (`.claude/settings.json`) enable the superpowers and frontend-design plugins automatically. Verify skills are available:
- The skill list in the system prompt should include `superpowers:brainstorming`, `superpowers:writing-plans`, etc.
- The `archon` skill should appear for workflow delegation

### Step 5 — Validate the stack

```bash
curl -s http://localhost:8000/api/health | python -m json.tool   # Backend healthy
docker-compose ps                                                 # All containers Up
```

You're ready. Pick an issue from the [backlog](https://github.com/omniscient/markethawk/issues) and start building.

## Dark Factory (Autonomous Docker Development)

An isolated Docker container that autonomously develops features from GitHub issues. Runs Claude Code inside a sandboxed environment with no host access. Preview stacks and the dark-factory container deliberately omit `docker-compose.override.yml` and always run baked images — do not rely on bind-mount behavior in autonomous workflows.

### Quick Start

```bash
# Build the dark factory image (first time only)
docker compose --profile factory build dark-factory

# Start a new feature from a GitHub issue
docker compose --profile factory run --rm dark-factory "Fix issue #3"

# Iterate after reviewing the preview and leaving feedback
docker compose --profile factory run --rm dark-factory "Continue issue #3"

# Tear down preview and merge when satisfied
docker compose --profile factory run --rm dark-factory "Close issue #3"
```

### Prerequisites

Add to `.archon/.env` (not `.env` — keep AI credentials separate):
```
# Option A: Use your Claude Max subscription (recommended — no per-token cost)
# Generate with: claude setup-token
CLAUDE_CODE_OAUTH_TOKEN=<token-from-setup-token>

# Option B: Use Anthropic API key (pay-per-token)
# ANTHROPIC_API_KEY=sk-ant-...

GH_TOKEN=ghp_...
```

The `GH_TOKEN` should be a fine-grained PAT scoped to `omniscient/markethawk` with `repo` permissions.

### Preview Environments

Each issue gets its own preview stack on deterministic ports:
- Frontend: `http://localhost:1{NN}33` (e.g. `:10333` for issue #3)
- Backend: `http://localhost:1{NN}80` (e.g. `:10380` for issue #3)

Preview URLs are included in the PR body. The preview persists after the factory exits so you can browse and test.

### Architecture

See [dark factory design spec](superpowers/specs/2026-05-02-dark-factory-design.md) for the full architecture, security model, and container topology.
