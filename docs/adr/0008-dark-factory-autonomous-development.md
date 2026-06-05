# ADR-008: Dark Factory Autonomous Development Model

**Date**: 2026-05-28  
**Status**: Accepted (updated 2026-06-05 — socket proxy implemented, factory user added)

## Context

Implementing GitHub issues manually requires context-switching between the issue tracker, IDE, terminal, and browser for every feature. The Dark Factory automates the repetitive mechanics: clone, branch, implement, test, preview, PR — leaving the human to read the PR and give feedback.

The core challenge is giving an AI agent enough access to build and run Docker containers (it needs to spin up a preview stack per issue) without giving it unrestricted access to the host Docker daemon. Unrestricted Docker socket access is equivalent to root on the host; any prompt injection or compromised dependency could destroy the live stack.

### Trust model

The Dark Factory routes Docker API calls through a `tecnativa/docker-socket-proxy` sidecar. The proxy allowlist is `CONTAINERS=1, IMAGES=1, NETWORKS=1, VOLUMES=1, BUILD=1, POST=1`; it blocks `SERVICES=0, EXEC=0, AUTH=0, SECRETS=0`. The raw socket is mounted read-only on the proxy only (`/var/run/docker.sock:ro`); `dark-factory` and `backlog-scheduler` connect via `DOCKER_HOST=tcp://docker-socket-proxy:2375`. The factory container has no bind-mount to the host filesystem — it clones fresh from GitHub each run.

### Known limitation accepted by convention

`tecnativa/docker-socket-proxy` does not support label-based container filtering. The factory can technically enumerate all containers via the Docker API, not just its own `mh-preview-*` stacks. Stronger isolation (a custom proxy with namespace enforcement) would require writing and maintaining a custom API gateway. The risk is accepted: the factory is a trusted first-party tool, not an adversarial workload. The entrypoint script and Archon workflows only operate on `mh-preview-*` prefixed resources by convention.

## Decision

Dark Factory runs as an ephemeral `--rm` container (`dark-factory`) connected to Docker via a `docker-socket-proxy` sidecar. The factory has no persistent state on the host; all work goes through GitHub (branches, PRs). Preview stacks are named `mh-preview-{issue}` and run on deterministic ports (`1{NN}33` for frontend, `1{NN}80` for backend).

Claude Code runs inside the factory as a non-root user (`factory`, UID 1000) — enforced via `USER factory` in `dark-factory/Dockerfile`. `--dangerously-skip-permissions` is required and is a built-in safety check that fails if run as root.

Credentials (`ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN`, `GH_TOKEN`) are injected from `.archon/.env`, mounted read-only. They are kept separate from `.env` to avoid mixing AI credentials with database passwords.

## Consequences

- The Docker socket proxy is the security boundary. If the proxy configuration is changed to grant additional permissions (e.g., `EXEC: 1`), the isolation guarantee weakens significantly.
- The factory can see running containers outside the `mh-preview-*` namespace via the Docker API. This is a known, accepted risk for a trusted internal tool.
- Preview stacks persist after the factory exits so the human can browse them. They must be torn down manually or via `docker compose --profile factory run --rm dark-factory "Close issue #N"`.
- Port collisions are possible if two issues share the last two digits. The port scheme (`1{NN}33`) uses the issue number directly; issues > 99 use two-digit truncation of the last two digits.
- The factory is stateless per run: if interrupted, it can be resumed with `"Continue issue #N"` — Archon reads the existing branch and open PR to reconstruct context.

### Residual Risk Acceptance (2026-06-05)

`tecnativa/docker-socket-proxy` does not support label-based container filtering. With `POST=1, CONTAINERS=1`, the factory can create or list any container on the host, not only `mh-preview-*` stacks. This risk is accepted: the factory is a trusted first-party tool run by the repo owner, not an adversarial workload. The entrypoint and Archon workflows operate on `mh-preview-*` resources by convention. A custom proxy with namespace-enforcement would require writing and maintaining a bespoke API gateway — cost not justified at this scale. Reviewed and accepted: issue #203.
