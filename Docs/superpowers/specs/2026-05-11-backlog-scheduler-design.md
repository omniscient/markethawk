# Backlog Scheduler Design

**Issue:** #2 — Schedule recurring backlog agent
**Date:** 2026-05-11

## Overview

A Docker-based Kanban flow controller that polls the GitHub project board every 30 seconds and dispatches dark factory runs to process tickets autonomously. The scheduler enforces WIP limits from the board, interprets PR comments via Claude to decide actions, and respects dependency ordering.

## Architecture

### Container: `backlog-scheduler`

A new Docker service under the `scheduler` profile. Based on the dark-factory image (inherits `gh`, `claude`, `jq`, Docker CLI). Does not clone repos or do development work — purely a dispatcher.

```yaml
# docker-compose.yml
backlog-scheduler:
  build:
    context: ./dark-factory
  profiles: [scheduler]
  container_name: backlog-scheduler
  restart: unless-stopped
  entrypoint: ["/opt/dark-factory/scheduler.sh"]
  env_file:
    - .archon/.env
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock
    - .:/workspace/project:ro
```

**Mounts:**
- Docker socket — to launch dark factory containers and count running ones
- Project directory (read-only) — for `docker-compose.yml` access to dispatch runs

**Environment:** Same `.archon/.env` credentials (GH_TOKEN, CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY).

### Usage

```bash
# Start
docker compose --profile scheduler up -d backlog-scheduler

# Watch
docker compose logs -f backlog-scheduler

# Stop
docker compose --profile scheduler down
```

## Decision Logic

Each 30-second cycle runs a priority waterfall. First match wins, one dispatch per cycle.

```
┌──────────────────────────────────────────────────┐
│                 Every 30 seconds                  │
├──────────────────────────────────────────────────┤
│ 1. Read board state (gh project item-list)        │
│ 2. Read board WIP limits (gh api graphql)         │
│ 3. Count running dark-factory containers          │
│                                                   │
│ 4. IN REVIEW items                                │
│    For each (board order):                        │
│    - Has comments after last factory report?       │
│      → Pipe comments to claude -p (Haiku)         │
│      → MERGE:    dispatch "Close issue #N"        │
│      → CONTINUE: dispatch "Continue issue #N"     │
│      → SKIP:     no action                        │
│                                                   │
│ 5. BLOCKED items                                  │
│    For each (board order):                        │
│    - Not already running? (docker ps check)       │
│    - Retry count < 3?                             │
│    → dispatch "Fix issue #N"                      │
│                                                   │
│ 6. READY items                                    │
│    - In Progress count < board limit?             │
│    - In Review count < board limit?               │
│    - Dependencies met? (Depends on #N is Done)    │
│    For first eligible (board order):              │
│    → dispatch "Fix issue #N"                      │
│                                                   │
│ 7. Nothing to do → sleep 30s                      │
└──────────────────────────────────────────────────┘
```

### WIP Limits

Read from the board's configured column limits at each cycle via the GitHub Projects GraphQL API. If a column has no limit configured, the scheduler treats it as unlimited.

### New Comment Detection

The dark factory posts a report comment ending with `*Posted by MarketHawk Dark Factory*`. The scheduler checks:
- If the last comment on the PR/issue is from the factory → no new feedback
- If a human commented after the factory report → new feedback to interpret

### Dependency Check

Parse the issue body for `Depends on: #N` — verify #N is "Done" on the board before picking it. For epics, the dark factory's existing epic resolution handles sub-issue ordering.

### Duplicate Dispatch Prevention

Before dispatching, check `docker ps` for a running dark-factory container whose command includes the issue number. If already running, skip.

### Skip Labels

Items with these labels are never picked up: `needs-discussion`, `epic`. Epics are skipped because the scheduler dispatches sub-issues directly from the Ready column — no reason to route through epic resolution.

## Comment Interpretation

When the scheduler finds new comments on an "In Review" PR, it pipes them to `claude -p` with Haiku for classification.

### Prompt Template

```
You are a PR comment classifier. Read the comments below and decide
the intent. Reply with exactly one word: MERGE, CONTINUE, or SKIP.

MERGE — the reviewer approves the PR (e.g. "looks good", "ship it",
"approved", "LGTM", thumbs up, ready to merge)
CONTINUE — the reviewer wants changes (e.g. "fix the tests",
"can you rename X", "this needs error handling", specific feedback)
SKIP — the comment is informational, a question, or unclear intent
(e.g. "interesting approach", "what does this do?", bot comments)

PR #<number>: <title>
Comments since last factory run:
<comments>
```

If the response isn't exactly one of the three words, treat as SKIP. No action on ambiguity.

## Configuration

```bash
POLL_INTERVAL=30                       # seconds between cycles
SKIP_LABELS="needs-discussion,epic"    # never pick these up directly
MAX_RETRIES=3                          # max dark factory attempts per issue before skipping
```

WIP limits (`MAX_IN_PROGRESS`, `MAX_IN_REVIEW`) come from the board, not from local config.

## Logging

Each cycle logs a one-line summary to stdout (Docker captures it):

```
[2026-05-11T14:30:00Z] in_progress=2/3 in_review=3/5 dispatched="Fix issue #32"
[2026-05-11T14:30:30Z] in_progress=3/3 in_review=3/5 skip=at_capacity
[2026-05-11T14:31:00Z] in_progress=2/3 in_review=3/5 dispatched="Continue issue #31"
[2026-05-11T14:31:30Z] in_progress=2/3 in_review=3/5 dispatched="Close issue #29"
```

## Failure Handling

### Dark factory run fails

The factory's existing error handler moves the ticket to "Blocked" and posts a failure comment. The scheduler picks up "Blocked" items on subsequent cycles and retries. After `MAX_RETRIES` (3) failed attempts per issue, the scheduler skips it and logs a warning. The retry counter resets when the issue gets new human comments.

Retry state is tracked in `/tmp/scheduler-state.json` inside the container.

### Scheduler crashes

`restart: unless-stopped` — Docker restarts the container. The scheduler is stateless (reads board fresh each cycle). The only lost state is the retry counter, which resets on restart — acceptable since scheduler crashes are rare.

### GitHub API errors

If `gh` calls fail, skip the cycle and log the error. At 2 requests per 30-second cycle, we stay well within GitHub's 5,000 requests/hour limit for authenticated users.

## Board Constants

| Constant | Value |
|----------|-------|
| Project ID | `PVT_kwHOAAFds84BWh4w` |
| Status Field ID | `PVTSSF_lAHOAAFds84BWh4wzhR1VaA` |
| Backlog | `f75ad846` |
| Refined | `0c79ebe5` |
| Ready | `61e4505c` |
| In Progress | `47fc9ee4` |
| In Review | `df73e18b` |
| Blocked | `93d87b2f` |
| Done | `98236657` |

## Files

| File | Purpose |
|------|---------|
| `dark-factory/scheduler.sh` | Main polling loop and decision logic |
| `docker-compose.yml` | `backlog-scheduler` service definition |
