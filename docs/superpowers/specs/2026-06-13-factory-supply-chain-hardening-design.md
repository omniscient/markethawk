# Factory Image Supply-Chain Hardening (F-SUPPLY-02)

**Date:** 2026-06-13
**Issue:** #375
**Epic:** #372 (Defensive Security Review 2026-06-12)
**Status:** Spec

---

## Problem

`dark-factory/Dockerfile` installs three dependencies using patterns that execute remote code at build time with no integrity verification:

| Line | Pattern | Risk |
|------|---------|------|
| 22 | `curl … nodesource … \| bash -` | NodeSource setup script executed without any hash or signature check |
| 41 | `curl … bun.sh/install \| BUN_INSTALL=/opt/bun bash` | Bun installer piped directly to bash |
| 69 | `git clone -b feat/workflow-cost-tracking …` | Moving branch ref — content changes without a Dockerfile edit |

The dark-factory container holds `docker-socket-proxy` access with `BUILD` and `POST` permissions. A supply-chain compromise at image build time has blast radius that includes arbitrary container and image creation. This matches **CWE-494** (download of code without integrity check).

---

## Requirements

1. No `| bash` or `| sh` pipes from network sources remain in `dark-factory/Dockerfile`.
2. The Archon clone must reference an immutable ref (commit SHA), not a moving branch name.
3. The Bun installation must pin a specific release version and verify the downloaded binary's sha256sum before it is executed.
4. The Node.js installation must use cryptographically verified packages (GPG-signed apt repository), consistent with the GitHub CLI and Docker CLI installation patterns already in the same Dockerfile.
5. The existing `/opt/bun` install path and `PATH="/opt/bun/bin:..."` env variable must be preserved — the Archon layer downstream depends on them.
6. Changes are confined to `dark-factory/Dockerfile` only; no other files are in scope.

---

## Architecture / Approach

### Fix 1 — Node.js 22: Inline the NodeSource APT repo (no script execution)

Rather than piping the `setup_22.x` script to bash, replicate the existing GPG-keyring pattern that the Dockerfile already uses for **GitHub CLI** (lines 45–50) and **Docker CLI** (lines 53–58): fetch the vendor's GPG key, dearmor it to a trusted keyring, write a `signed-by=` apt sources entry, then `apt-get install nodejs`.

```dockerfile
# Node.js 22.x — GPG-verified apt repo (no curl | bash)
RUN curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
    | gpg --dearmor -o /usr/share/keyrings/nodesource.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/nodesource.gpg] \
https://deb.nodesource.com/node_22.x nodistro main" \
    | tee /etc/apt/sources.list.d/nodesource.list > /dev/null && \
    apt-get update && apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*
```

> **Implementation note**: The `setup_22.x` script configures the apt suite as `nodistro` (NodeSource dropped distro-specific codenames in their v2 packages). The implementing agent should confirm the exact suite string by inspecting the script at `https://deb.nodesource.com/setup_22.x` before committing the hardcoded value.

This approach:
- Eliminates the `| bash` pipe entirely (the GPG key pipe into `gpg --dearmor` is not code execution).
- Uses the same trust model as the existing GitHub CLI and Docker CLI blocks in this Dockerfile — a single uniform pattern for all externally-sourced apt repos.
- Requires no fragile pinned-hash maintenance; the GPG key is long-lived and stable.

### Fix 2 — Bun: Pinned GitHub Release artifact + sha256sum

Download the platform-specific release zip from GitHub Releases at a pinned version, verify against the `SHASUMS256.txt` published alongside that release, then extract the binary.

```dockerfile
# Bun — pinned release artifact with sha256sum verification (no curl | bash)
ARG BUN_VERSION=1.3.14
RUN curl -fsSL -o /tmp/bun.zip \
        "https://github.com/oven-sh/bun/releases/download/bun-v${BUN_VERSION}/bun-linux-x64.zip" && \
    curl -fsSL -o /tmp/bun-checksums.txt \
        "https://github.com/oven-sh/bun/releases/download/bun-v${BUN_VERSION}/SHASUMS256.txt" && \
    grep "bun-linux-x64.zip" /tmp/bun-checksums.txt | sha256sum -c - && \
    mkdir -p /opt/bun/bin && \
    unzip -p /tmp/bun.zip "bun-linux-x64/bun" > /opt/bun/bin/bun && \
    chmod +x /opt/bun/bin/bun && \
    rm /tmp/bun.zip /tmp/bun-checksums.txt
ENV PATH="/opt/bun/bin:${PATH}"
```

The existing `ENV PATH="/opt/bun/bin:${PATH}"` line in the Dockerfile is absorbed into this block; its current standalone position can be removed.

> **Pinned at spec time**: `bun-v1.3.14` (verified available 2026-06-13). The implementing agent should confirm this is still current or use the then-latest version.

> **Implementation note**: The exact inner path within the zip archive (`bun-linux-x64/bun`) should be confirmed via `unzip -l bun-linux-x64.zip` before committing. Alternatively, `unzip bun-linux-x64.zip -d /tmp/bun-extract && mv /tmp/bun-extract/bun-linux-x64/bun /opt/bun/bin/bun` is a safer extraction form.

### Fix 3 — Archon: Commit SHA pin

Add a `git checkout` to an immutable commit SHA immediately after the clone, replacing the moving branch reference.

```dockerfile
# Archon CLI (from fork — includes workflow cost tracking).
# Pinned to an immutable commit SHA for supply-chain integrity (issue #375).
# To upgrade: update ARCHON_SHA to the new commit hash after reviewing the diff.
ARG ARCHON_SHA=ee55cfc5d347a38f531fdfba2bee42ab33316ef6
RUN git clone https://github.com/omniscient/Archon.git /opt/archon && \
    git -C /opt/archon checkout "${ARCHON_SHA}" && \
    cd /opt/archon && bun install && \
    chmod +x /opt/archon/packages/cli/src/cli.ts && \
    ln -sf /opt/archon/packages/cli/src/cli.ts /usr/local/bin/archon
```

The SHA `ee55cfc5d347a38f531fdfba2bee42ab33316ef6` is the current HEAD of `feat/workflow-cost-tracking` as of 2026-06-13 (resolved via `git ls-remote`). Using `ARG` exposes the version at build-time for `docker build --build-arg ARCHON_SHA=<new>` overrides.

The existing comment block about `bun link` and the factory user PATH issue is preserved verbatim — only the `git clone` line changes.

---

## Alternatives Considered

### Node.js: Pinned SHA of the setup_22.x script

Rejected. The `setup_22.x` script is a moving convenience installer — NodeSource updates it whenever the bootstrapping logic changes. A pinned hash breaks on every upstream update and encourages developers to "just bump the hash" without re-auditing, defeating the supply-chain goal. The inline apt-repo approach is both more robust and consistent with the existing Dockerfile pattern.

### Node.js: Download Node.js binary tarball from nodejs.org/dist/

Rejected. Entirely independent of NodeSource, but adds ongoing maintenance burden: manual PATH and symlink wiring, no apt-managed security patches, manual version bumps. Node in this image's sole purpose is hosting `@anthropic-ai/claude-code` (one CLI); the extra complexity is not justified.

### Bun: Use bun.sh install script with a pinned version flag

Rejected. The install script still pipes from a remote source to bash — exactly the `| bash` pattern the issue's verification criterion forbids.

### Archon: Mutable tag on the fork

Rejected. The `omniscient/Archon` fork is unsigned; a mutable tag (e.g., `markethawk-stable`) can be force-pushed and provides no real integrity gain over a branch name. Only an immutable commit SHA satisfies the verification criterion.

### Archon: Git submodule

Rejected. Adds cross-repo submodule wiring (`.gitmodules`, recursive clone requirements for all contributors) to what is currently a single `git clone` line in a Dockerfile. Not justified for a single dependency.

---

## Open Questions (non-blocking)

1. **NodeSource apt suite string** — Verify that the `nodistro` suite name is correct for the `node_22.x` channel on Ubuntu 24.04 before committing; inspect the script body at `https://deb.nodesource.com/setup_22.x` to confirm.
2. **Bun zip inner path** — Confirm the path of the Bun binary inside `bun-linux-x64.zip` (expected: `bun-linux-x64/bun`) via `unzip -l` before committing the extract command.
3. **Bun version cadence** — `bun-v1.3.14` is pinned at spec time; no automated upgrade is in scope. Future bumps require a deliberate Dockerfile edit.
4. **Archon SHA expiry** — The pinned SHA `ee55cfc5d347a38f531fdfba2bee42ab33316ef6` will drift from `feat/workflow-cost-tracking` as the fork advances. The upgrade path (update `ARCHON_SHA` in the Dockerfile) is intentionally manual and deliberate.

---

## Assumptions

- [Assumption] The Dockerfile targets `ubuntu:24.04` on `x86_64`; `dpkg --print-architecture` returns `amd64`, so the correct Bun artifact is `bun-linux-x64.zip`.
- [Assumption] The `omniscient/Archon` fork has no GPG-signed tags on `feat/workflow-cost-tracking` as of spec time. If a signed tag is created before implementation, prefer it over a raw SHA.
- [Assumption] `bun-v1.3.14` is the most recent stable Bun release as of 2026-06-13. The implementing agent should use this version or the then-current stable release.

---

## Implementation Checklist

- [ ] Replace Node.js `curl | bash` block with inline GPG-keyring apt setup (verify `nodistro` suite name first)
- [ ] Remove standalone `RUN curl -fsSL https://bun.sh/install | BUN_INSTALL=/opt/bun bash` block; add pinned GitHub Release download + sha256sum + extract block; absorb the existing `ENV PATH` line
- [ ] Add `ARG ARCHON_SHA=ee55cfc5d347a38f531fdfba2bee42ab33316ef6` and `git -C /opt/archon checkout "${ARCHON_SHA}"` to the Archon clone block; remove `-b feat/workflow-cost-tracking`
- [ ] Build: `docker compose --profile factory build dark-factory`
- [ ] Verify: `grep -nE '\| bash|\| sh' dark-factory/Dockerfile` returns no output
- [ ] Verify: `grep -n 'feat/workflow-cost-tracking' dark-factory/Dockerfile` returns no output

---

*Spec generated by MarketHawk Refinement Pipeline — 2026-06-13*
