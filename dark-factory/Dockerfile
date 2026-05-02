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

# Non-root user (Ubuntu 24.04 ships with ubuntu:1000 — remove it first)
RUN userdel -r ubuntu 2>/dev/null || true && \
    groupadd -f -g 1000 factory && \
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
