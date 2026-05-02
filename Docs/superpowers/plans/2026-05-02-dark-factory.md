# Dark Factory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an isolated Docker container that autonomously develops MarketHawk features from GitHub issues, spins up preview environments for human verification, and iterates on feedback until merged.

**Architecture:** A `dark-factory` container (Ubuntu + full dev toolchain) connects to the host Docker daemon through a Tecnativa docker-socket-proxy that restricts API access. The factory clones the repo from GitHub, develops with Claude Code, pushes a branch, and creates ephemeral preview stacks (`mh-preview-{issue}`) on deterministic ports. Preview stacks persist after the factory exits so the user can browse and test.

**Tech Stack:** Docker, docker-compose, Tecnativa/docker-socket-proxy, Ubuntu 22.04, Node 22, Python 3.12, Bun, Claude Code CLI, Archon CLI, GitHub CLI

**Spec:** `docs/superpowers/specs/2026-05-02-dark-factory-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `dark-factory/Dockerfile` | Create | Container image with full dev toolchain |
| `dark-factory/entrypoint.sh` | Create | Startup: git config, gh auth, clone, dispatch to Archon or Claude |
| `dark-factory/docker-compose.preview.yml` | Create | Parameterized preview stack template |
| `dark-factory/.dockerignore` | Create | Keep build context small |
| `.archon/workflows/archon-dark-factory.yaml` | Create | Archon DAG workflow for the full lifecycle |
| `.archon/commands/dark-factory-implement.md` | Create | Command prompt for the implement phase |
| `.archon/commands/dark-factory-validate.md` | Create | Command prompt for the validate phase |
| `docker-compose.yml` | Modify | Add docker-socket-proxy and dark-factory services |
| `.env.example` | Modify | Document ANTHROPIC_API_KEY and GH_TOKEN |
| `CLAUDE.md` | Modify | Document dark factory usage |
| `.gitignore` | Modify | Add dark-factory build artifacts |

---

### Task 1: Create the dark-factory Dockerfile

**Files:**
- Create: `dark-factory/Dockerfile`
- Create: `dark-factory/.dockerignore`

- [ ] **Step 1: Create the dark-factory directory**

```bash
mkdir -p dark-factory
```

- [ ] **Step 2: Create .dockerignore**

Write `dark-factory/.dockerignore`:

```
.git
node_modules
__pycache__
*.pyc
```

- [ ] **Step 3: Write the Dockerfile**

Write `dark-factory/Dockerfile`:

```dockerfile
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# System dependencies
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    git \
    jq \
    bubblewrap \
    socat \
    ca-certificates \
    gnupg \
    unzip \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Node.js 22.x
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Python 3.12
RUN apt-get update && apt-get install -y \
    python3.12 \
    python3.12-venv \
    python3-pip \
    && ln -sf /usr/bin/python3.12 /usr/bin/python \
    && ln -sf /usr/bin/python3.12 /usr/bin/python3 \
    && rm -rf /var/lib/apt/lists/*

# Bun
RUN curl -fsSL https://bun.sh/install | bash
ENV PATH="/root/.bun/bin:${PATH}"

# GitHub CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | gpg --dearmor -o /usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | tee /etc/apt/sources.list.d/github-cli.list > /dev/null && \
    apt-get update && apt-get install -y gh && \
    rm -rf /var/lib/apt/lists/*

# Docker CLI (client only — no daemon)
RUN curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu jammy stable" \
    | tee /etc/apt/sources.list.d/docker.list > /dev/null && \
    apt-get update && apt-get install -y docker-ce-cli docker-compose-plugin && \
    rm -rf /var/lib/apt/lists/*

# Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Archon CLI (from source)
RUN git clone https://github.com/coleam00/Archon.git /opt/archon && \
    cd /opt/archon && bun install && \
    cd /opt/archon/packages/cli && bun link

# Non-root user
RUN groupadd -g 1000 factory && \
    useradd -m -u 1000 -g factory factory

# Workspace directory
RUN mkdir -p /workspace && chown factory:factory /workspace

# Copy entrypoint and preview template
COPY --chown=factory:factory entrypoint.sh /usr/local/bin/entrypoint.sh
COPY --chown=factory:factory docker-compose.preview.yml /opt/dark-factory/docker-compose.preview.yml
RUN chmod +x /usr/local/bin/entrypoint.sh

# Move bun to factory user
RUN cp -r /root/.bun /home/factory/.bun && \
    chown -R factory:factory /home/factory/.bun
ENV PATH="/home/factory/.bun/bin:/usr/local/bin:${PATH}"

USER factory
WORKDIR /workspace

ENTRYPOINT ["entrypoint.sh"]
```

- [ ] **Step 4: Verify Dockerfile syntax**

```bash
cd dark-factory && docker build --check . 2>&1 || echo "docker build --check not supported, will validate on full build"
```

- [ ] **Step 5: Commit**

```bash
git add dark-factory/Dockerfile dark-factory/.dockerignore
git commit -m "feat(dark-factory): add Dockerfile with full dev toolchain"
```

---

### Task 2: Create the entrypoint script

**Files:**
- Create: `dark-factory/entrypoint.sh`

- [ ] **Step 1: Write entrypoint.sh**

Write `dark-factory/entrypoint.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

# --- Configuration ---
REPO_URL="https://${GH_TOKEN}@github.com/omniscient/markethawk.git"
CLONE_DIR="/workspace/markethawk"
FACTORY_NAME="MarketHawk Factory"
FACTORY_EMAIL="factory@markethawk"

# --- Validate required environment ---
for var in GH_TOKEN ANTHROPIC_API_KEY; do
  if [ -z "${!var:-}" ]; then
    echo "ERROR: $var is not set. Add it to .archon/.env" >&2
    exit 1
  fi
done

# --- Git identity ---
git config --global user.name "$FACTORY_NAME"
git config --global user.email "$FACTORY_EMAIL"

# --- GitHub CLI auth ---
echo "$GH_TOKEN" | gh auth login --with-token 2>/dev/null
echo "Authenticated as: $(gh auth status 2>&1 | grep 'Logged in' || echo 'unknown')"

# --- Parse arguments ---
ARGUMENTS="${*}"
if [ -z "$ARGUMENTS" ]; then
  echo "Usage: docker compose --profile factory run --rm dark-factory \"Fix issue #3\""
  echo "       docker compose --profile factory run --rm dark-factory \"Continue issue #3\""
  echo "       docker compose --profile factory run --rm dark-factory \"Close issue #3\""
  exit 1
fi

# --- Clone the repo ---
echo "Cloning markethawk..."
if [ -d "$CLONE_DIR" ]; then
  rm -rf "$CLONE_DIR"
fi
git clone "$REPO_URL" "$CLONE_DIR"
cd "$CLONE_DIR"

# --- Copy preview template into clone ---
mkdir -p "$CLONE_DIR/dark-factory"
cp /opt/dark-factory/docker-compose.preview.yml "$CLONE_DIR/dark-factory/docker-compose.preview.yml"

# --- Install backend/frontend deps for local testing ---
echo "Installing backend dependencies..."
cd "$CLONE_DIR/backend" && pip install --quiet -r requirements.txt
echo "Installing frontend dependencies..."
cd "$CLONE_DIR/frontend" && npm install --silent
cd "$CLONE_DIR"

# --- Run via Archon workflow ---
export ARCHON_SUPPRESS_NESTED_CLAUDE_WARNING=1
echo "Starting dark factory: $ARGUMENTS"
archon workflow run archon-dark-factory "$ARGUMENTS"
```

- [ ] **Step 2: Make it executable and verify syntax**

```bash
chmod +x dark-factory/entrypoint.sh
bash -n dark-factory/entrypoint.sh && echo "Syntax OK"
```

- [ ] **Step 3: Commit**

```bash
git add dark-factory/entrypoint.sh
git commit -m "feat(dark-factory): add entrypoint script with lifecycle dispatch"
```

---

### Task 3: Create the preview stack template

**Files:**
- Create: `dark-factory/docker-compose.preview.yml`

- [ ] **Step 1: Write the preview compose file**

Write `dark-factory/docker-compose.preview.yml`:

```yaml
# Preview environment for MarketHawk feature branches.
# Invoked as: ISSUE_NUM=3 docker compose -p mh-preview-3 -f dark-factory/docker-compose.preview.yml up -d --build
#
# Port scheme: 1{ISSUE_NUM_PADDED}XX where XX is the service suffix.
# Example for issue #3:  frontend=10333, backend=10380, postgres=10354, redis=10363
# Example for issue #12: frontend=11233, backend=11280, postgres=11254, redis=11263

services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: stockscanner
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: preview_password
    ports:
      - "1${ISSUE_NUM_PADDED:-00}54:5432"
    volumes:
      - preview_postgres_data:/var/lib/postgresql/data
    networks:
      - preview-network
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 10

  redis:
    image: redis:7-alpine
    ports:
      - "1${ISSUE_NUM_PADDED:-00}63:6379"
    networks:
      - preview-network
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10

  backend:
    build:
      context: ../backend
      dockerfile: Dockerfile
    environment:
      DATABASE_URL: postgresql://postgres:preview_password@postgres:5432/stockscanner
      REDIS_URL: redis://redis:6379/0
      ENVIRONMENT: development
      LOG_LEVEL: INFO
      POLYGON_API_KEY: ${POLYGON_API_KEY:-}
    ports:
      - "1${ISSUE_NUM_PADDED:-00}80:8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - preview-network
    restart: unless-stopped

  frontend:
    build:
      context: ../frontend
      dockerfile: Dockerfile
    environment:
      VITE_API_TARGET: http://backend:8000
    ports:
      - "1${ISSUE_NUM_PADDED:-00}33:3333"
    networks:
      - preview-network
    restart: unless-stopped

  celery-worker:
    build:
      context: ../backend
      dockerfile: Dockerfile
    command: celery -A app.core.celery_app:celery_app worker --loglevel=info
    environment:
      DATABASE_URL: postgresql://postgres:preview_password@postgres:5432/stockscanner
      REDIS_URL: redis://redis:6379/0
      ENVIRONMENT: development
      LOG_LEVEL: INFO
      POLYGON_API_KEY: ${POLYGON_API_KEY:-}
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - preview-network
    restart: unless-stopped

volumes:
  preview_postgres_data:

networks:
  preview-network:
    driver: bridge
```

- [ ] **Step 2: Validate the compose file syntax**

```bash
cd dark-factory && ISSUE_NUM_PADDED=03 docker compose -f docker-compose.preview.yml config > /dev/null && echo "Config valid"
```

- [ ] **Step 3: Commit**

```bash
git add dark-factory/docker-compose.preview.yml
git commit -m "feat(dark-factory): add preview stack compose template"
```

---

### Task 4: Add docker-socket-proxy and dark-factory to docker-compose.yml

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add the docker-socket-proxy service**

Add after the `seq` service block (before `volumes:`), in `docker-compose.yml`:

```yaml
  # Docker Socket Proxy — restricted API access for dark-factory
  docker-socket-proxy:
    image: tecnativa/docker-socket-proxy
    container_name: markethawk-socket-proxy
    environment:
      CONTAINERS: 1
      IMAGES: 1
      NETWORKS: 1
      VOLUMES: 1
      SERVICES: 0
      EXEC: 0
      POST: 1
      BUILD: 1
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - factory-network
    restart: unless-stopped

  # Dark Factory — autonomous development agent (run on demand)
  dark-factory:
    build:
      context: ./dark-factory
      dockerfile: Dockerfile
    container_name: markethawk-dark-factory
    environment:
      DOCKER_HOST: tcp://docker-socket-proxy:2375
    env_file:
      - path: .archon/.env
        required: true
    depends_on:
      - docker-socket-proxy
    networks:
      - factory-network
    profiles:
      - factory
```

- [ ] **Step 2: Add the factory-network to the networks section**

In `docker-compose.yml`, update the `networks:` block:

```yaml
networks:
  stockscanner-network:
    driver: bridge
  factory-network:
    driver: bridge
```

- [ ] **Step 3: Validate the compose config**

```bash
docker compose config > /dev/null && echo "Config valid"
```

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(dark-factory): add socket proxy and dark-factory services to compose"
```

---

### Task 5: Create the Archon workflow

**Files:**
- Create: `.archon/workflows/archon-dark-factory.yaml`

- [ ] **Step 1: Write the workflow DAG**

Write `.archon/workflows/archon-dark-factory.yaml`:

```yaml
name: archon-dark-factory
description: |
  Use when: Running inside the dark-factory Docker container to implement a GitHub issue.
  Triggers: "Fix issue", "Continue issue", "Close issue".
  Does: Parses intent -> fetches issue context -> branches -> implements with TDD ->
        spins up preview stack -> validates against preview -> pushes and creates PR.
  NOT for: Running outside the dark-factory container.

provider: claude
model: sonnet

worktree:
  enabled: false

nodes:
  # Layer 0: Parse the command and fetch issue context
  - id: parse-intent
    prompt: |
      Parse this command and extract two things:
      1. The GitHub issue number
      2. The intent: "new" (first time working on this issue), "continue" (iterate on existing work), or "close" (merge and tear down)

      Command: $ARGUMENTS

      Output ONLY valid JSON, nothing else:
      {"issue_number": <int>, "intent": "<new|continue|close>"}
    allowed_tools: []
    model: haiku
    output_format:
      type: object
      properties:
        issue_number:
          type: integer
        intent:
          type: string
          enum: [new, continue, close]
      required: [issue_number, intent]

  - id: fetch-issue
    bash: |
      gh issue view $parse-intent.output.issue_number --json title,body,labels,comments
    depends_on: [parse-intent]
    timeout: 15000

  # Layer 1: Route based on intent
  - id: close-preview
    bash: |
      ISSUE=$parse-intent.output.issue_number
      PADDED=$(printf "%02d" "$ISSUE")
      echo "Tearing down mh-preview-${ISSUE}..."
      docker compose -p "mh-preview-${ISSUE}" down -v 2>/dev/null || echo "No preview stack found"
      PR_NUM=$(gh pr list --head "feat/issue-${ISSUE}" --json number --jq '.[0].number // empty')
      if [ -n "$PR_NUM" ]; then
        gh pr merge "$PR_NUM" --merge --delete-branch || echo "PR not mergeable (check approval status)"
      fi
      gh issue comment "$ISSUE" --body "Dark factory: preview torn down, PR merged (if approved). Issue work complete."
      echo "CLOSED"
    depends_on: [parse-intent, fetch-issue]
    when: "$parse-intent.output.intent == 'close'"
    timeout: 30000

  - id: setup-branch
    bash: |
      ISSUE=$parse-intent.output.issue_number
      INTENT=$parse-intent.output.intent
      SLUG=$(echo $fetch-issue.output | jq -r '.title // "feature"' | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | head -c 40)
      BRANCH="feat/issue-${ISSUE}-${SLUG}"

      if [ "$INTENT" = "continue" ]; then
        git fetch origin "$BRANCH" 2>/dev/null && git checkout "$BRANCH" || git checkout -b "$BRANCH"
      else
        git checkout -b "$BRANCH"
      fi
      echo "$BRANCH"
    depends_on: [parse-intent, fetch-issue]
    when: "$parse-intent.output.intent != 'close'"
    timeout: 15000

  # Layer 2: Implement the feature
  - id: implement
    command: dark-factory-implement
    depends_on: [setup-branch, fetch-issue]
    when: "$parse-intent.output.intent != 'close'"
    idle_timeout: 600000

  # Layer 3: Spin up preview and validate
  - id: preview-up
    bash: |
      ISSUE=$parse-intent.output.issue_number
      PADDED=$(printf "%02d" "$ISSUE")
      export ISSUE_NUM_PADDED="$PADDED"
      export POLYGON_API_KEY="${POLYGON_API_KEY:-}"

      echo "Starting preview stack mh-preview-${ISSUE} (ports: 1${PADDED}33, 1${PADDED}80)..."
      docker compose -p "mh-preview-${ISSUE}" \
        -f dark-factory/docker-compose.preview.yml \
        up -d --build

      echo "Waiting for backend health..."
      for i in $(seq 1 60); do
        if curl -sf "http://localhost:1${PADDED}80/api/health" > /dev/null 2>&1; then
          echo "Backend healthy!"
          echo "PREVIEW_FRONTEND=http://localhost:1${PADDED}33"
          echo "PREVIEW_BACKEND=http://localhost:1${PADDED}80"
          exit 0
        fi
        sleep 3
      done
      echo "WARNING: Backend did not become healthy within 180s"
      exit 1
    depends_on: [implement]
    when: "$parse-intent.output.intent != 'close'"
    timeout: 300000

  - id: validate
    command: dark-factory-validate
    depends_on: [preview-up]
    when: "$parse-intent.output.intent != 'close'"
    idle_timeout: 300000

  # Layer 4: Push and create PR
  - id: push-and-pr
    bash: |
      ISSUE=$parse-intent.output.issue_number
      PADDED=$(printf "%02d" "$ISSUE")
      BRANCH=$(git branch --show-current)

      git push -u origin "$BRANCH"

      EXISTING_PR=$(gh pr list --head "$BRANCH" --json number --jq '.[0].number // empty')
      if [ -n "$EXISTING_PR" ]; then
        echo "PR #${EXISTING_PR} already exists, updated with latest push."
        echo "$EXISTING_PR"
      else
        PR_URL=$(gh pr create \
          --title "$(gh issue view $ISSUE --json title --jq '.title')" \
          --body "## Summary
      Automated implementation for issue #${ISSUE}.

      ## Preview
      - Frontend: http://localhost:1${PADDED}33
      - Backend API: http://localhost:1${PADDED}80/docs

      ## Commands
      \`\`\`bash
      # Iterate after feedback
      docker compose --profile factory run --rm dark-factory \"Continue issue #${ISSUE}\"

      # Tear down preview when done
      docker compose --profile factory run --rm dark-factory \"Close issue #${ISSUE}\"
      \`\`\`

      ---
      *Generated by MarketHawk Dark Factory*" \
          --draft)
        echo "Created PR: $PR_URL"
      fi
    depends_on: [validate]
    when: "$parse-intent.output.intent != 'close'"
    timeout: 30000
```

- [ ] **Step 2: Validate the workflow**

```bash
archon validate workflows archon-dark-factory
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add .archon/workflows/archon-dark-factory.yaml
git commit -m "feat(dark-factory): add Archon DAG workflow for autonomous development"
```

---

### Task 6: Create Archon command files

**Files:**
- Create: `.archon/commands/dark-factory-implement.md`
- Create: `.archon/commands/dark-factory-validate.md`

- [ ] **Step 1: Write the implement command**

Write `.archon/commands/dark-factory-implement.md`:

```markdown
---
description: Implement a feature or fix from a GitHub issue inside the dark factory
argument-hint: (no arguments - reads issue context from workflow)
---

# Dark Factory — Implement

**Workflow ID**: $WORKFLOW_ID

---

## Phase 1: LOAD

Read the project rules:
- Read `CLAUDE.md` for all development rules, architecture, and validation requirements.
- The issue context has been fetched by the workflow. It is available in the conversation.

## Phase 2: PLAN

Based on the issue description and codebase analysis:
1. Identify which files need to change (backend models, routers, services, frontend components, etc.)
2. Determine if database migrations are needed
3. Write a brief plan (10-20 lines) as a checklist in `$ARTIFACTS_DIR/plan.md`

### PHASE_2_CHECKPOINT
- [ ] Plan written to `$ARTIFACTS_DIR/plan.md`
- [ ] All affected files identified

## Phase 3: IMPLEMENT (TDD)

For each change in the plan:

1. **Write the failing test first** — pytest for backend, type-check for frontend
2. **Run the test to confirm it fails** — `cd backend && python -m pytest tests/ -x -v` or `cd frontend && npx tsc --noEmit`
3. **Implement the minimal code to pass** — follow existing patterns in the codebase
4. **Run the test to confirm it passes**
5. **Commit** — small, focused commits with descriptive messages

If the change requires a new SQLAlchemy model:
1. Create the model file in `backend/app/models/`
2. Import it in `backend/app/models/__init__.py`
3. Generate migration: `cd backend && python -m alembic revision --autogenerate -m "description"`
4. Apply migration: `cd backend && python -m alembic upgrade head`

### PHASE_3_CHECKPOINT
- [ ] All tests pass: `cd backend && python -m pytest`
- [ ] Frontend type-checks: `cd frontend && npx tsc --noEmit` (if frontend changed)
- [ ] All changes committed
- [ ] Implementation summary written to `$ARTIFACTS_DIR/implementation.md`

## Phase 4: REPORT

Write a summary of what was implemented to `$ARTIFACTS_DIR/implementation.md`:
- Files created/modified
- Tests added
- Migrations created (if any)
- Any decisions or trade-offs made
```

- [ ] **Step 2: Write the validate command**

Write `.archon/commands/dark-factory-validate.md`:

```markdown
---
description: Validate the implementation against the running preview stack
argument-hint: (no arguments - reads from workflow context)
---

# Dark Factory — Validate

**Workflow ID**: $WORKFLOW_ID

---

## Phase 1: LOAD

Read the implementation context:
- Read `$ARTIFACTS_DIR/implementation.md` for what was implemented
- Read `CLAUDE.md` for validation rules

## Phase 2: VALIDATE

Run the full validation suite against the preview stack:

### Backend validation
```bash
cd backend && python -m pytest -v
```

### Frontend validation (if frontend was modified)
```bash
cd frontend && npx tsc --noEmit
```

### Endpoint validation against preview
For each new or changed endpoint identified in the implementation:
```bash
curl -sf http://localhost:${PREVIEW_PORT}/api/<endpoint> | python -m json.tool
```

Record all results — passes and failures.

### PHASE_2_CHECKPOINT
- [ ] pytest results recorded
- [ ] tsc results recorded (if applicable)
- [ ] Endpoint curl tests recorded
- [ ] All results written to `$ARTIFACTS_DIR/validation.md`

## Phase 3: FIX (if needed)

If any validation fails:
1. Fix the issue
2. Re-run the failing test
3. Commit the fix
4. Re-validate

Repeat until all validations pass.

## Phase 4: REPORT

Write validation results to `$ARTIFACTS_DIR/validation.md`:
- Pass/fail status for each check
- Specific error details for any failures
- Final status: PASS or FAIL
```

- [ ] **Step 3: Validate the commands**

```bash
archon validate commands dark-factory-implement
archon validate commands dark-factory-validate
```

- [ ] **Step 4: Commit**

```bash
git add .archon/commands/dark-factory-implement.md .archon/commands/dark-factory-validate.md
git commit -m "feat(dark-factory): add Archon command files for implement and validate phases"
```

---

### Task 7: Update .env.example and CLAUDE.md

**Files:**
- Modify: `.env.example`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add dark factory credentials to .env.example**

Append to `.env.example` before the end:

```
# =============================================================================
# OPTIONAL: Dark Factory (Autonomous Development Agent)
# =============================================================================
# Required for running the dark-factory container.
# Anthropic API key for Claude Code:
# ANTHROPIC_API_KEY=sk-ant-...
#
# GitHub Personal Access Token (fine-grained, repo scope for omniscient/markethawk):
# GH_TOKEN=ghp_...
#
# These should also be added to .archon/.env (which is gitignored).
```

- [ ] **Step 2: Add dark factory section to CLAUDE.md**

Add after the "Setup for AI Development" section (before "## Development Rules") in `CLAUDE.md`:

```markdown
## Dark Factory (Autonomous Docker Development)

An isolated Docker container that autonomously develops features from GitHub issues. Runs Claude Code inside a sandboxed environment with no host access.

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
ANTHROPIC_API_KEY=sk-ant-...
GH_TOKEN=ghp_...
```

The `GH_TOKEN` should be a fine-grained PAT scoped to `omniscient/markethawk` with `repo` permissions.

### Preview Environments

Each issue gets its own preview stack on deterministic ports:
- Frontend: `http://localhost:1{NN}33` (e.g. `:10333` for issue #3)
- Backend: `http://localhost:1{NN}80` (e.g. `:10380` for issue #3)

Preview URLs are included in the PR body. The preview persists after the factory exits so you can browse and test.

### Architecture

See [dark factory design spec](docs/superpowers/specs/2026-05-02-dark-factory-design.md) for the full architecture, security model, and container topology.
```

- [ ] **Step 3: Commit**

```bash
git add .env.example CLAUDE.md
git commit -m "docs: add dark factory setup to env example and CLAUDE.md"
```

---

### Task 8: Update .gitignore and final validation

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add dark-factory build artifacts to .gitignore**

Add to `.gitignore` after the Archon section:

```gitignore
# Dark factory runtime
dark-factory/tmp/
```

- [ ] **Step 2: Build the dark-factory image**

```bash
docker compose --profile factory build dark-factory
```

Expected: image builds successfully. This will take 3-5 minutes on first run (downloading Ubuntu, Node, Python, etc.).

- [ ] **Step 3: Verify the socket proxy starts**

```bash
docker compose up -d docker-socket-proxy
docker compose ps docker-socket-proxy
```

Expected: `markethawk-socket-proxy` is running.

- [ ] **Step 4: Verify Docker CLI access through the proxy**

```bash
docker compose --profile factory run --rm dark-factory bash -c "docker ps --format '{{.Names}}' | head -5"
```

Expected: lists containers visible through the proxy (including the proxy itself).

- [ ] **Step 5: Dry-run the dark factory with a simple prompt**

```bash
docker compose --profile factory run --rm dark-factory "Say hello and list the files in the repo root"
```

Expected: Claude Code clones the repo, lists files, and exits. This validates the full chain: image → entrypoint → git clone → Claude Code invocation.

- [ ] **Step 6: Commit and final status**

```bash
git add .gitignore
git commit -m "chore: add dark-factory build artifacts to gitignore"
```

- [ ] **Step 7: Verify all files are committed**

```bash
git status
git log --oneline -10
```

Expected: clean working tree, 7 commits from this plan.
