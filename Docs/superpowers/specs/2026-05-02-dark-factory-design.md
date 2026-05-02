# Dark Factory — Autonomous Development in Docker

## Goal

An isolated Docker-based development agent that picks up GitHub issues, implements features autonomously using Archon + Claude Code, spins up a preview environment for human verification, and iterates on feedback until the issue is closed and code is merged.

## Architecture

### Container Topology

Three new services are added to the existing MarketHawk `docker-compose.yml`:

```
Host Docker daemon
├── Live stack (existing)
│   ├── postgres, redis, backend, frontend, celery, etc.
│   └── stockscanner-network
│
├── docker-socket-proxy              ← NEW: restricts Docker API access
│   ├── image: tecnativa/docker-socket-proxy
│   ├── mounts /var/run/docker.sock
│   └── exposes tcp:2375 to dark-factory only
│
├── dark-factory (ephemeral)         ← NEW: runs Archon + Claude Code
│   ├── built from Dockerfile.dark-factory
│   ├── DOCKER_HOST=tcp://docker-socket-proxy:2375
│   ├── clones repo from GitHub (no host bind-mount)
│   ├── develops, tests, pushes, creates PR
│   ├── spins up preview stack via proxy
│   └── exits when done (--rm)
│
└── mh-preview-{issue} (dynamic)    ← NEW: created by dark-factory
    ├── postgres    :1{issue}54
    ├── redis       :1{issue}63
    ├── backend     :1{issue}80
    ├── frontend    :1{issue}33
    ├── celery-worker
    └── mh-preview-{issue}_network
```

### Docker Socket Proxy Configuration

Uses [Tecnativa/docker-socket-proxy](https://github.com/Tecnativa/docker-socket-proxy) with restricted permissions:

| Setting | Value | Purpose |
|---------|-------|---------|
| CONTAINERS | 1 | Create/start/stop/remove containers |
| IMAGES | 1 | Pull images for preview stacks |
| NETWORKS | 1 | Create/remove preview networks |
| VOLUMES | 1 | Create/remove preview volumes |
| SERVICES | 0 | Block Swarm service access |
| EXEC | 0 | Block exec into containers |
| POST | 1 | Allow create/start/stop operations |
| BUILD | 1 | Allow building preview images |

**Note:** Tecnativa/docker-socket-proxy does not natively support label-based container filtering. The factory can technically see all containers via the Docker API. Mitigation: the entrypoint script and Archon workflow only operate on `mh-preview-*` prefixed resources by convention. For stronger isolation, a custom proxy or Docker API auth plugin could be added later.

## Dark Factory Image

### Dockerfile.dark-factory

**Base:** Ubuntu 22.04

**Toolchain:**

| Tool | Version | Purpose |
|------|---------|---------|
| Node.js | 22.x | Claude Code CLI, frontend type-checking |
| Python | 3.12 | Backend deps, pytest, alembic |
| Bun | latest | Archon CLI runtime |
| Git | latest | Clone, branch, push |
| GitHub CLI | latest | Issues, PRs, comments |
| Claude Code | latest | AI development agent |
| Archon CLI | npm install | Workflow orchestration (installed globally via npm) |
| Docker CLI | latest (client only) | Manage preview stacks via proxy |
| curl, jq | latest | Endpoint validation |
| bubblewrap, socat | latest | Claude Code sandboxing |

**No Docker daemon** — only the CLI client, pointed at the socket proxy.

**Non-root user:** `factory` (UID 1000). No sudo. Claude Code's `--dangerously-skip-permissions` requires non-root, which is a built-in safety check.

### Entrypoint Script

`dark-factory/entrypoint.sh`:

1. Configure git identity: `MarketHawk Factory <factory@markethawk>`
2. Authenticate `gh` using `GH_TOKEN` from environment
3. Clone `omniscient/markethawk` from GitHub (fresh every run — `.claude/skills/archon/` and `.archon/config.yaml` come with the clone since they're committed)
4. Run the dark factory Archon workflow with the user's arguments
5. Exit

### Secrets Injection

The container reads credentials from `.archon/.env` (mounted read-only), which contains:

```
ANTHROPIC_API_KEY=sk-ant-...
GH_TOKEN=ghp_...
```

`GH_TOKEN` requires `repo` scope. A fine-grained PAT scoped to `omniscient/markethawk` is recommended.

No secrets are baked into the image. The `.archon/.env` file is already gitignored.

## Preview Stack

### Template File

`dark-factory/docker-compose.preview.yml` — a parameterized compose file that creates a complete MarketHawk environment scoped to an issue number.

Uses environment variable substitution for the issue number:

```yaml
# Invoked as: ISSUE_NUM=3 docker compose -p mh-preview-3 -f docker-compose.preview.yml up -d
```

### Port Scheme

Each preview gets deterministic ports based on issue number:

| Service | Formula | Issue #3 | Issue #12 |
|---------|---------|----------|-----------|
| Frontend | `1{issue}33` | `:10333` | `:11233` |
| Backend | `1{issue}80` | `:10380` | `:11280` |
| Postgres | `1{issue}54` | `:10354` | `:11254` |
| Redis | `1{issue}63` | `:10363` | `:11263` |

### Naming Convention

All preview resources use the prefix `mh-preview-{issue}`:
- Project: `mh-preview-3`
- Network: `mh-preview-3_network`
- Containers: `mh-preview-3-backend-1`
- Volumes: `mh-preview-3_postgres_data`

### Database Seeding

Each preview postgres starts empty. Migrations are applied via `alembic upgrade head`. No live data is cloned. Test data seeding can be added later.

### Preview Lifecycle

| Event | Action |
|-------|--------|
| Factory first run for issue #3 | Clone, develop, push, create `mh-preview-3` stack, add preview URL to PR |
| User browses `http://localhost:10333` | Full MarketHawk running the feature branch |
| User comments on issue | "The chart tooltip is misaligned" |
| Factory re-run ("Continue issue #3") | Pull branch, read feedback, fix, push, restart preview |
| User approves / closes issue | Factory merges PR, runs `docker compose -p mh-preview-3 down -v` |

## Security Model

### Isolation Layers

| Layer | Protects | Mechanism |
|-------|----------|-----------|
| Docker socket proxy | Host Docker daemon | Restricted API: only container/network/image/volume ops |
| Non-root user | Container internals | `factory` UID 1000, no sudo, no capability escalation |
| Fresh clone per run | Host filesystem | No bind-mounts; code cloned from GitHub |
| Convention-scoped access | Other containers | Workflow only operates on `mh-preview-*` resources by convention; proxy restricts API surface |
| Read-only secret mount | Credentials | `.archon/.env` mounted `:ro` |
| Network isolation | Cross-stack leakage | Each preview gets its own network; factory has no access to live stack |
| No published ports on factory | Inbound access | Factory is outbound-only |

### What the factory CAN do

- Read GitHub issues and PRs
- Clone the MarketHawk repo from GitHub
- Push branches and create PRs
- Create/manage preview containers (prefixed `mh-preview-*`)
- Call the Anthropic API
- Access npm/pip registries

### What the factory CANNOT do

- Read or write files on the host machine
- See or interact with the live MarketHawk stack
- Start privileged containers
- Mount host directories
- Access the Docker daemon directly (only via proxy)
- Run with elevated capabilities
- Modify its own credential file

## Developer Experience

### Commands

```bash
# Start a new feature from an issue
docker compose run --rm dark-factory "Fix issue #3"

# Iterate after feedback
docker compose run --rm dark-factory "Continue issue #3"

# Tear down a preview when done
docker compose run --rm dark-factory "Close issue #3"
```

### What the Factory Does Inside

The factory runs a custom Archon workflow (`archon-dark-factory`) that encodes the full lifecycle:

1. **Parse** — extract issue number and intent (new / continue / close)
2. **Clone and branch** — `git clone`, create or checkout `feat/issue-{n}-{slug}`
3. **Read context** — fetch issue description and PR comments via `gh`
4. **Plan** — write implementation plan following superpowers conventions
5. **Implement** — TDD loop: write tests, implement, validate, iterate
6. **Type-check** — `npx tsc --noEmit` for frontend changes
7. **Backend tests** — `python -m pytest`
8. **Spin up preview** — `docker compose -p mh-preview-{n} up -d`
9. **Wait for health** — poll preview backend health endpoint
10. **Live validation** — curl-test new/changed endpoints against preview
11. **Push and PR** — create or update PR with preview URL in body
12. **Exit** — factory container stops, preview keeps running

### PR Body Format

```markdown
## Summary
<what was done>

## Preview
Frontend: http://localhost:10333
Backend API: http://localhost:10380/docs

## Test Results
- pytest: 42 passed
- tsc: clean
- Endpoint validation: 3/3 passed

## To iterate
`docker compose run --rm dark-factory "Continue issue #3"`

## To tear down
`docker compose run --rm dark-factory "Close issue #3"`
```

### On "Close issue #3"

1. Merge the PR (if approved)
2. Delete the remote branch
3. Tear down `mh-preview-3` (containers + volumes)
4. Comment on the issue with a summary

## Credential Setup for Developers

Each developer adds two values to `.archon/.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
GH_TOKEN=ghp_...
```

The `GH_TOKEN` should be a fine-grained PAT scoped to `omniscient/markethawk` with `repo` permissions. This file is gitignored.

## Files to Create

| File | Purpose |
|------|---------|
| `Dockerfile.dark-factory` | Dark factory image with full dev toolchain |
| `dark-factory/entrypoint.sh` | Startup script: git config, gh auth, clone, run workflow |
| `dark-factory/docker-compose.preview.yml` | Template for preview environments |
| `.archon/workflows/archon-dark-factory.yaml` | Custom Archon workflow for the full lifecycle |
| `.archon/commands/dark-factory-*.md` | Command prompts for each workflow phase |
| Updates to `docker-compose.yml` | Add docker-socket-proxy and dark-factory services |
| Updates to `.env.example` | Document GH_TOKEN and ANTHROPIC_API_KEY |
| Updates to `CLAUDE.md` | Document dark factory usage |
