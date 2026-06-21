FROM ubuntu:26.04@sha256:f3d28607ddd78734bb7f71f117f3c6706c666b8b76cbff7c9ff6e5718d46ff64

ENV DEBIAN_FRONTEND=noninteractive

# System dependencies
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    git \
    jq \
    bc \
    bubblewrap \
    socat \
    ca-certificates \
    gnupg \
    unzip \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Node.js 22.x — pinned-keyring APT repo instead of `curl … setup_22.x | bash`.
# apt cryptographically verifies every package against the pinned NodeSource
# signing key, so no remote script is piped to a shell. Mirrors the gh/docker
# installs below.
RUN curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
    | gpg --dearmor -o /usr/share/keyrings/nodesource.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" \
    > /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Python 3.12 (ships with Ubuntu 24.04)
RUN apt-get update && apt-get install -y \
    python3.12 \
    python3.12-venv \
    python3-pip \
    && ln -sf /usr/bin/python3.12 /usr/bin/python \
    && ln -sf /usr/bin/python3.12 /usr/bin/python3 \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /usr/lib/python*/EXTERNALLY-MANAGED

# codeindex dependency analyzer (dark-factory / agent tooling only — never in backend/requirements.txt)
# pre-commit for the codeindex-blast warn-only hook
RUN pip install --quiet "git+https://github.com/scheidydude/codeindex.git" pre-commit

# Bun — pinned release artifact verified against a hardcoded sha256 instead of
# `curl … bun.sh/install | bash`. The expected hash lives in git, so a tampered
# download (or tampered checksum file) is rejected at build time. Installed to
# /opt/bun so it is accessible to non-root users.
ENV BUN_VERSION=1.3.14
RUN case "$(dpkg --print-architecture)" in \
      amd64) BUN_ARCH=x64;     BUN_SHA=951ee2aee855f08595aeec6225226a298d3fea83a3dcd6465c09cbccdf7e848f ;; \
      arm64) BUN_ARCH=aarch64; BUN_SHA=a27ffb63a8310375836e0d6f668ae17fa8d8d18b88c37c821c65331973a19a3b ;; \
      *) echo "unsupported architecture for bun: $(dpkg --print-architecture)" >&2; exit 1 ;; \
    esac && \
    cd /tmp && \
    curl -fsSL -o bun.zip "https://github.com/oven-sh/bun/releases/download/bun-v${BUN_VERSION}/bun-linux-${BUN_ARCH}.zip" && \
    echo "${BUN_SHA}  bun.zip" | sha256sum -c - && \
    unzip -q bun.zip && \
    mkdir -p /opt/bun/bin && \
    mv "bun-linux-${BUN_ARCH}/bun" /opt/bun/bin/bun && \
    chmod +x /opt/bun/bin/bun && \
    rm -rf bun.zip "bun-linux-${BUN_ARCH}"
ENV PATH="/opt/bun/bin:${PATH}"

# GitHub CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | gpg --dearmor -o /usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | tee /etc/apt/sources.list.d/github-cli.list > /dev/null && \
    apt-get update && apt-get install -y gh && \
    rm -rf /var/lib/apt/lists/*

# yq — YAML processor used by entrypoint.sh and scheduler.sh to read config.yaml
RUN YQ_ARCH=$(dpkg --print-architecture) && \
    curl -fsSL "https://github.com/mikefarah/yq/releases/download/v4.44.3/yq_linux_${YQ_ARCH}" -o /usr/local/bin/yq && \
    chmod +x /usr/local/bin/yq

# Docker CLI (client only — no daemon)
RUN curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu noble stable" \
    | tee /etc/apt/sources.list.d/docker.list > /dev/null && \
    apt-get update && apt-get install -y docker-ce-cli docker-compose-plugin docker-buildx-plugin && \
    rm -rf /var/lib/apt/lists/*

# Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Archon CLI (from fork — includes workflow cost tracking).
# Pinned to an immutable commit on feat/workflow-cost-tracking instead of the
# moving branch tip, so a rebuild always fetches the reviewed code. Bump the SHA
# deliberately to pick up Archon updates.
# Deliberately NOT `bun link`: its shim lands in the invoking user's ~/.bun/bin
# (root → /root/.bun/bin), which is off PATH and unreadable for the factory
# user. Cached layers masked this for months; any --no-cache rebuild lost
# `archon` (exit 127 in entrypoint). cli.ts carries a `#!/usr/bin/env bun`
# shebang, so a plain symlink on PATH is all that's needed.
RUN git clone https://github.com/omniscient/Archon.git /opt/archon && \
    cd /opt/archon && \
    git checkout f83fb556a2a864014e12ecfe6f60c7a1d18928b9 && \
    bun install && \
    chmod +x /opt/archon/packages/cli/src/cli.ts && \
    ln -sf /opt/archon/packages/cli/src/cli.ts /usr/local/bin/archon

# Workspace directory
RUN mkdir -p /workspace

# Copy entrypoint, scheduler, preview template, seed data, and base compose file
COPY dark-factory/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY dark-factory/scheduler.sh /opt/dark-factory/scheduler.sh
COPY dark-factory/smoke_gate.sh /opt/dark-factory/smoke_gate.sh
COPY dark-factory/docker-compose.preview.yml /opt/dark-factory/docker-compose.preview.yml
COPY dark-factory/seed/ /opt/dark-factory/seed/
COPY docker-compose.yml /opt/dark-factory/docker-compose.yml
COPY .claude/skills/refinement/ /opt/refinement-skills/
RUN chmod +x /usr/local/bin/entrypoint.sh /opt/dark-factory/scheduler.sh /opt/dark-factory/smoke_gate.sh

# Non-root factory user — must be created AFTER all root-level installs.
# ubuntu:24.04 ships a default 'ubuntu' user at UID/GID 1000; evict it first or
# groupadd/useradd fail on any clean (--no-cache) build. Latent until the layer
# cache is dropped — cached builds skipped this layer for months.
RUN userdel -r ubuntu 2>/dev/null || true && \
    groupdel ubuntu 2>/dev/null || true && \
    groupadd --gid 1000 factory && \
    useradd --uid 1000 --gid 1000 --create-home --home-dir /home/factory factory

# Transfer workspace ownership to the factory user.
# /opt/dark-factory too: scheduler.sh (runs as factory) provisions
# /opt/dark-factory/.archon/.env at startup — root-owned dir crash-loops it.
# /var/lib/dark-factory pre-created so the scheduler_state named volume
# initializes factory-owned on first use instead of as a root-owned mountpoint.
RUN mkdir -p /var/lib/dark-factory && \
    chown -R factory:factory /workspace /opt/dark-factory /var/lib/dark-factory

USER factory
WORKDIR /workspace

ENTRYPOINT ["entrypoint.sh"]
