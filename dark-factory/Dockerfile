FROM ubuntu:24.04

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

# Python 3.12 (ships with Ubuntu 24.04)
RUN apt-get update && apt-get install -y \
    python3.12 \
    python3.12-venv \
    python3-pip \
    && ln -sf /usr/bin/python3.12 /usr/bin/python \
    && ln -sf /usr/bin/python3.12 /usr/bin/python3 \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /usr/lib/python*/EXTERNALLY-MANAGED

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
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu noble stable" \
    | tee /etc/apt/sources.list.d/docker.list > /dev/null && \
    apt-get update && apt-get install -y docker-ce-cli docker-compose-plugin && \
    rm -rf /var/lib/apt/lists/*

# Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Archon CLI (from source)
RUN git clone https://github.com/coleam00/Archon.git /opt/archon && \
    cd /opt/archon && bun install && \
    cd /opt/archon/packages/cli && bun link

# Workspace directory
RUN mkdir -p /workspace

# Copy entrypoint, preview template, and seed data
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY docker-compose.preview.yml /opt/dark-factory/docker-compose.preview.yml
COPY seed_preview.sql /opt/dark-factory/seed_preview.sql
RUN chmod +x /usr/local/bin/entrypoint.sh

WORKDIR /workspace

ENTRYPOINT ["entrypoint.sh"]
