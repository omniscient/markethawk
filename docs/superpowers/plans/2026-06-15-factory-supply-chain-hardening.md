# Plan: Factory Image Supply-Chain Hardening (F-SUPPLY-02)

**Date:** 2026-06-15  
**Issue:** #375  
**Epic:** #372  
**Spec:** `docs/superpowers/specs/2026-06-13-factory-supply-chain-hardening-design.md` (on `refine/issue-375--security--f-supply-02--curl-bash-instal`)  
**Branch:** `feat/issue-375-*`

---

## Goal

Eliminate all `curl | bash` / `curl | sh` network-code-execution patterns and the moving branch reference from `dark-factory/Dockerfile`. Three supply-chain fixes confined to a single file:

1. **Node.js 22**: Replace the `curl … nodesource … | bash -` pipe with an inline GPG-keyring apt setup (matching the GitHub CLI and Docker CLI patterns already in the Dockerfile).
2. **Bun**: Replace `curl … bun.sh/install | bash` with a pinned GitHub Release artifact download + `sha256sum` verification before binary extraction.
3. **Archon**: Replace the `-b feat/workflow-cost-tracking` moving branch with an `ARG ARCHON_SHA` + `git checkout` to an immutable commit SHA.

---

## Architecture

This change touches only the build-time layer of the dark-factory image (`dark-factory/Dockerfile`). No runtime behaviour changes; no new services; no docker-compose changes. The blast-radius of a supply-chain compromise in this image includes docker-socket-proxy access (BUILD/POST), so supply-chain integrity is treated as a security requirement, not a cosmetic fix.

The Node.js fix follows the **uniform GPG-keyring trust model** already established in the Dockerfile for two other externally-sourced apt repos (GitHub CLI, Docker CLI). This is intentional — a single consistent pattern is auditable.

The Bun fix preserves the existing `/opt/bun` install path and `PATH="/opt/bun/bin:..."` env var (required by the downstream Archon layer).

The Archon fix makes the fork reference immutable. The `ARG` form allows future SHA bumps via `docker build --build-arg ARCHON_SHA=<new>` without otherwise touching the Dockerfile structure.

---

## Tech Stack

- **Docker / Dockerfile** — `ubuntu:24.04`, multi-layer apt-based installs
- **GPG** — `gpg --dearmor` for key format conversion (already present in image via `gnupg` package, installed in the first `apt-get` layer)
- **sha256sum** — standard coreutils; present in `ubuntu:24.04`
- **unzip** — already installed in the first `apt-get` layer (line 16 of current Dockerfile)
- **BuildKit** — `docker buildx build --builder remote tcp://buildkit:1234 --load` for verification builds (factory-network path; required per dark-factory-ops memory)

---

## File Structure

| File | Change |
|------|--------|
| `dark-factory/Dockerfile` | Lines 21–24: replace Node.js `curl\|bash` block with GPG-keyring apt setup |
| `dark-factory/Dockerfile` | Lines 40–42: replace Bun `curl\|bash` block + absorb standalone `ENV PATH` |
| `dark-factory/Dockerfile` | Lines 68–77: add `ARG ARCHON_SHA`, replace `-b feat/workflow-cost-tracking` with `git checkout` |

No other files are modified.

---

## Task 1: Fix Node.js 22 — GPG-verified apt repo

**Files:** `dark-factory/Dockerfile` (lines 21–24)

### Steps

**1.1 — Pre-flight: confirm NodeSource apt suite name**

Before hardcoding `nodistro`, inspect the NodeSource setup script to confirm the suite string. Run from the implementing agent's shell:

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | grep -E "nodistro|focal|jammy|noble" | head -5
```

Expected output contains `nodistro` (NodeSource dropped distro-specific codenames in their v2 packages). If the script uses a different suite (e.g., `noble`), update the apt sources entry accordingly. Record the confirmed suite name before proceeding.

**1.2 — Verify the vulnerable pattern exists (baseline)**

```bash
grep -n 'nodesource.*bash\|bash.*nodesource' dark-factory/Dockerfile
```

Expected: `22:RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \`

**1.3 — Replace the Node.js block**

Replace lines 21–24 (the `# Node.js 22.x` comment through the closing `rm -rf /var/lib/apt/lists/*`) with the GPG-keyring apt block. The new block must:
- Fetch the NodeSource GPG key and pipe into `gpg --dearmor` (key format transformation — not code execution)
- Write a `signed-by=` apt sources entry using the suite confirmed in step 1.1
- Run `apt-get update && apt-get install -y nodejs`

**Current content to replace (lines 21–24):**
```dockerfile
# Node.js 22.x
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*
```

**Replacement:**
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

> **Note**: `nodistro` is the correct suite name as of spec time (2026-06-13). The implementing agent must confirm this in step 1.1 before committing.

**1.4 — Verify the `| bash` pattern is gone from the Node.js block**

```bash
grep -n 'setup_22.x' dark-factory/Dockerfile
```

Expected: no output (the setup script reference is eliminated entirely).

**1.5 — Commit**

```bash
git add dark-factory/Dockerfile
git commit -m "fix(supply-chain): replace Node.js curl|bash with GPG-verified apt repo (#375)"
```

---

## Task 2: Fix Bun — Pinned GitHub Release artifact + sha256sum

**Files:** `dark-factory/Dockerfile` (lines 40–42)

### Steps

**2.1 — Pre-flight: confirm Bun zip inner path**

Before writing the `unzip -p` command, confirm the binary's path inside the zip:

```bash
curl -fsSL -o /tmp/bun-check.zip \
  "https://github.com/oven-sh/bun/releases/download/bun-v1.3.14/bun-linux-x64.zip"
unzip -l /tmp/bun-check.zip
rm /tmp/bun-check.zip
```

Expected output contains `bun-linux-x64/bun` as the binary path. If the path differs (e.g., just `bun`), update the `unzip -p` argument accordingly.

**2.2 — Pre-flight: confirm bun-v1.3.14 is available (or identify current stable)**

```bash
curl -fsSL -o /dev/null -w "%{http_code}" \
  "https://github.com/oven-sh/bun/releases/download/bun-v1.3.14/SHASUMS256.txt"
```

If the HTTP status is not 200, find the current latest stable release:

```bash
curl -fsSL "https://api.github.com/repos/oven-sh/bun/releases/latest" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['tag_name'])"
```

Use the confirmed version in the `ARG BUN_VERSION` default.

**2.3 — Verify the vulnerable Bun pattern exists (baseline)**

```bash
grep -n 'bun.sh/install' dark-factory/Dockerfile
```

Expected: `41:RUN curl -fsSL https://bun.sh/install | BUN_INSTALL=/opt/bun bash`

**2.4 — Replace the Bun block**

Replace lines 40–42 (the `# Bun` comment through the `ENV PATH` line) with the pinned-artifact block. The `ENV PATH` line is absorbed into this block (its standalone position at line 42 is removed).

**Current content to replace (lines 40–42):**
```dockerfile
# Bun — install to /opt/bun so it is accessible to non-root users
RUN curl -fsSL https://bun.sh/install | BUN_INSTALL=/opt/bun bash
ENV PATH="/opt/bun/bin:${PATH}"
```

**Replacement:**
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

> **If `unzip -p` path differs**: use `unzip /tmp/bun.zip -d /tmp/bun-extract && mv /tmp/bun-extract/bun-linux-x64/bun /opt/bun/bin/bun` as an alternative extraction form (safer for non-standard inner paths).

**2.5 — Verify the `| bash` pattern is gone from the Bun block**

```bash
grep -n 'bun.sh/install' dark-factory/Dockerfile
```

Expected: no output.

```bash
grep -n 'sha256sum' dark-factory/Dockerfile
```

Expected: one line containing `sha256sum -c -` in the new Bun block.

**2.6 — Commit**

```bash
git add dark-factory/Dockerfile
git commit -m "fix(supply-chain): replace Bun curl|bash with pinned release artifact + sha256sum (#375)"
```

---

## Task 3: Fix Archon — Immutable commit SHA pin

**Files:** `dark-factory/Dockerfile` (lines 68–77)

### Steps

**3.1 — Confirm the Archon SHA is reachable**

```bash
git ls-remote https://github.com/omniscient/Archon.git | grep ee55cfc5d347a38f531fdfba2bee42ab33316ef6
```

Expected: one line referencing the SHA. If no output is returned (the fork has been force-pushed or garbage-collected), resolve the current HEAD of `feat/workflow-cost-tracking`:

```bash
git ls-remote https://github.com/omniscient/Archon.git feat/workflow-cost-tracking
```

Use the returned SHA as `ARCHON_SHA`. Update the `ARG` default value accordingly.

**3.2 — Verify the vulnerable branch ref exists (baseline)**

```bash
grep -n 'feat/workflow-cost-tracking' dark-factory/Dockerfile
```

Expected: `74:RUN git clone -b feat/workflow-cost-tracking https://github.com/omniscient/Archon.git /opt/archon && \`

**3.3 — Replace the Archon block**

Replace lines 68–77 (the full `# Archon CLI` comment block through the closing `ln -sf` line) with the SHA-pinned version. The existing multi-line comment about `bun link` is preserved verbatim — only the clone command changes.

**Current content to replace (lines 68–77):**
```dockerfile
# Archon CLI (from fork — includes workflow cost tracking).
# Deliberately NOT `bun link`: its shim lands in the invoking user's ~/.bun/bin
# (root → /root/.bun/bin), which is off PATH and unreadable for the factory
# user. Cached layers masked this for months; any --no-cache rebuild lost
# `archon` (exit 127 in entrypoint). cli.ts carries a `#!/usr/bin/env bun`
# shebang, so a plain symlink on PATH is all that's needed.
RUN git clone -b feat/workflow-cost-tracking https://github.com/omniscient/Archon.git /opt/archon && \
    cd /opt/archon && bun install && \
    chmod +x /opt/archon/packages/cli/src/cli.ts && \
    ln -sf /opt/archon/packages/cli/src/cli.ts /usr/local/bin/archon
```

**Replacement:**
```dockerfile
# Archon CLI (from fork — includes workflow cost tracking).
# Deliberately NOT `bun link`: its shim lands in the invoking user's ~/.bun/bin
# (root → /root/.bun/bin), which is off PATH and unreadable for the factory
# user. Cached layers masked this for months; any --no-cache rebuild lost
# `archon` (exit 127 in entrypoint). cli.ts carries a `#!/usr/bin/env bun`
# shebang, so a plain symlink on PATH is all that's needed.
# Pinned to an immutable commit SHA for supply-chain integrity (issue #375).
# To upgrade: update ARCHON_SHA to the new commit hash after reviewing the diff.
ARG ARCHON_SHA=ee55cfc5d347a38f531fdfba2bee42ab33316ef6
RUN git clone https://github.com/omniscient/Archon.git /opt/archon && \
    git -C /opt/archon checkout "${ARCHON_SHA}" && \
    cd /opt/archon && bun install && \
    chmod +x /opt/archon/packages/cli/src/cli.ts && \
    ln -sf /opt/archon/packages/cli/src/cli.ts /usr/local/bin/archon
```

**3.4 — Verify the moving branch reference is gone**

```bash
grep -n 'feat/workflow-cost-tracking' dark-factory/Dockerfile
```

Expected: no output.

```bash
grep -n 'ARCHON_SHA' dark-factory/Dockerfile
```

Expected: two lines — the `ARG` definition and the `git -C /opt/archon checkout "${ARCHON_SHA}"` call.

**3.5 — Commit**

```bash
git add dark-factory/Dockerfile
git commit -m "fix(supply-chain): pin Archon clone to immutable commit SHA, drop moving branch ref (#375)"
```

---

## Task 4: Final Verification

**Files:** None (read-only verification pass)

### Steps

**4.1 — Grep gate: no `| bash` or `| sh` pipes from network sources**

```bash
grep -nE '\| bash|\| sh' dark-factory/Dockerfile
```

Expected output: **empty** (zero lines).

If any line appears, it must be investigated before proceeding. The only permitted pipe-to-interpreter is `gpg --dearmor` (key format transformation, not code execution).

**4.2 — Grep gate: no moving branch reference**

```bash
grep -n 'feat/workflow-cost-tracking' dark-factory/Dockerfile
```

Expected output: **empty** (zero lines).

**4.3 — Grep gate: sha256sum is present for Bun**

```bash
grep -c 'sha256sum' dark-factory/Dockerfile
```

Expected output: `1` (exactly one line — the Bun verification step).

**4.4 — Grep gate: ARCHON_SHA ARG is present**

```bash
grep -c 'ARCHON_SHA' dark-factory/Dockerfile
```

Expected output: `2` (the `ARG` definition and the `checkout` call).

**4.5 — Image build via BuildKit remote builder**

Per dark-factory-ops memory (`[PATTERN]` — factory builds must use buildx with the remote builder, not `compose up --build`, due to docker-socket-proxy constraints):

```bash
docker buildx build \
  --builder remote tcp://buildkit:1234 \
  --load \
  -t markethawk-factory:supply-chain-test \
  -f dark-factory/Dockerfile \
  .
```

Expected: build completes without error. Specifically verify these layers succeed:
- `Step: RUN curl … nodesource.gpg` — GPG key download and dearmor
- `Step: RUN curl … bun-linux-x64.zip` — Bun download + `sha256sum -c -` passes
- `Step: RUN git clone … && git -C /opt/archon checkout` — SHA checkout succeeds

If `sha256sum -c -` fails (checksum mismatch), the build fails at that layer — investigate whether the downloaded zip is corrupt or the SHASUMS256.txt lists a different filename.

**4.6 — Binary smoke test**

After a successful build, verify the three affected binaries are functional in a temporary container:

```bash
# Node.js
docker run --rm markethawk-factory:supply-chain-test node --version
# Expected: v22.x.x

# Bun
docker run --rm markethawk-factory:supply-chain-test bun --version
# Expected: 1.3.14 (or the version pinned in BUN_VERSION ARG)

# Archon
docker run --rm markethawk-factory:supply-chain-test archon --version
# Expected: archon version string (non-zero exit is acceptable if the CLI requires subcommands;
# verify with: docker run --rm markethawk-factory:supply-chain-test archon --help)
```

**4.7 — Clean up test image**

```bash
docker image rm markethawk-factory:supply-chain-test
```

**4.8 — Final commit verification**

```bash
git log --oneline -4
```

Expected: three commits on the feature branch — one each for Node.js, Bun, and Archon fixes.

```bash
git diff origin/main...HEAD --name-only
```

Expected: `dark-factory/Dockerfile` only. No other files.

---

## Rollback

If the image build fails and the root cause cannot be resolved quickly:

```bash
git revert HEAD~3..HEAD  # revert all three fix commits
git push origin <branch>
```

The original Dockerfile is preserved in git history; reverting restores the pre-fix state.

---

*Plan generated by MarketHawk Refinement Pipeline — 2026-06-15*
