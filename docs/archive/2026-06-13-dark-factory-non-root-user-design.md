# Dark Factory: Non-Root `factory` User Verification & Publish

**Date:** 2026-06-13  
**Issue:** #261  
**Epic:** #272 (Container & deployment security hardening)  
**Gating resolved:** #266 (CLOSED — ubuntu UID-1000 conflict investigated)  
**Status:** Spec  

---

## Problem

The dark-factory container was originally designed to run as a dedicated non-root `factory` user (uid/gid 1000), but a prior scope-enforcement excise from issue #202 removed that setup, reverting both the user creation and the Bun install path from `/opt/bun` to `/root/.bun`. Issue #266 investigated why it was removed and confirmed the root cause: `ubuntu:24.04` ships a default `ubuntu` user at UID/GID 1000, so a clean `--no-cache` build fails at `useradd` with a UID-already-in-use error. Cached builds masked this for months.

All five code changes have since been committed:

1. Bun installed to `/opt/bun` (non-root accessible), `PATH` updated  
2. Default `ubuntu` user evicted before creating `factory` user  
3. `factory` user/group created at uid/gid 1000 with `/home/factory`  
4. `/workspace`, `/opt/dark-factory`, `/var/lib/dark-factory` chowned to `factory`  
5. `USER factory` / `WORKDIR /workspace` set in Dockerfile  
6. `entrypoint.sh` already uses `${HOME}` (not `/root/.archon`)  

**What remains:** the baked image in the container registry still reflects the old root configuration. A clean (`--no-cache`) rebuild is required to exercise the ubuntu-eviction and user-creation layers, followed by smoke testing both services that share the image, and then republishing.

The factory container **cannot self-implement this change** — it runs from the baked image, not the source tree. The running container cannot rebuild its own image. This is the same self-modification constraint as issue #326.

---

## Requirements

1. The baked image must be rebuilt with `--no-cache` to guarantee the ubuntu-eviction and user-creation layers execute (cached builds silently skip them).  
2. The rebuilt container must run as `factory` (uid=1000, gid=1000), not root.  
3. All tooling installed for root during the build layer (`bun`, `archon`, `claude`, `gh`, `docker`) must be accessible on PATH when running as `factory`.  
4. The `ARTIFACTS_DIR` path in entrypoint must resolve to `/home/factory/.archon/...`, not `/root/.archon/...`.  
5. The `backlog-scheduler` service (shares same image, custom entrypoint) must also start and write to `/var/lib/dark-factory` as `factory`.  
6. After smoke tests pass, the rebuilt image must be published to `ghcr.io/omniscient/markethawk-dark-factory:latest` and pulled on the host stack.  

---

## Architecture / Approach

This is a verification-and-publish task, not an implementation task. No new code is required.

### Why `--no-cache` is mandatory

The ubuntu-eviction RUN layer (`userdel -r ubuntu; groupdel ubuntu; useradd ...`) only executes if Docker cannot reuse a prior cached layer. On GitHub-hosted runners the layer cache is generally cold on a fresh merge, so a push-to-main CI rebuild will usually exercise the layer — but this is not guaranteed. To be certain, use one of:

**Option A — CI workflow dispatch with `--no-cache` (preferred):**  
The `.github/workflows/ci-publish.yml` `build-dark-factory` job does not currently pass `--no-cache` to `docker/build-push-action`. Add `no-cache: true` to the `with:` block, trigger `workflow_dispatch` from the Actions tab, then revert the flag after the image is confirmed clean.

**Option B — Local host build + push:**
```bash
docker compose build --no-cache dark-factory
docker tag markethawk-dark-factory:latest ghcr.io/omniscient/markethawk-dark-factory:latest
docker push ghcr.io/omniscient/markethawk-dark-factory:latest
```

### Smoke checklist after image rebuild

#### Service 1: `dark-factory` (factory profile)

```bash
# Verify identity — must print "factory" (uid=1000)
docker compose --profile factory run --rm dark-factory whoami
docker compose --profile factory run --rm dark-factory id

# Verify tool PATH as factory user
docker compose --profile factory run --rm dark-factory sh -c \
  "bun --version && archon --version && claude --version && gh --version && docker version"

# Verify ARTIFACTS_DIR resolves to /home/factory/.archon (not /root)
docker compose --profile factory run --rm dark-factory sh -c \
  "echo HOME=\$HOME; ls /home/factory/"

# Verify /workspace is writable as factory
docker compose --profile factory run --rm dark-factory sh -c \
  "touch /workspace/.smoke-test && rm /workspace/.smoke-test && echo OK"

# Verify /opt/dark-factory is writable (scheduler.sh writes .archon/.env here)
docker compose --profile factory run --rm dark-factory sh -c \
  "touch /opt/dark-factory/.smoke-test && rm /opt/dark-factory/.smoke-test && echo OK"
```

#### Service 2: `backlog-scheduler` (scheduler profile)

The scheduler uses a custom `entrypoint: ["/opt/dark-factory/scheduler.sh"]` and runs long-lived (`restart: unless-stopped`). It shares the same image but has different operational paths.

```bash
# Start scheduler and check it doesn't immediately crash
docker compose --profile scheduler up -d backlog-scheduler
sleep 5
docker compose --profile scheduler logs backlog-scheduler | head -20
# Expect: scheduler starts, provisions .archon/.env, enters dispatch loop

# Verify scheduler runs as factory user (not root)
docker compose --profile scheduler exec backlog-scheduler whoami

# Verify /var/lib/dark-factory is writable (scheduler_state volume)
docker compose --profile scheduler exec backlog-scheduler sh -c \
  "touch /var/lib/dark-factory/.smoke-test && rm /var/lib/dark-factory/.smoke-test && echo OK"
```

### Pull rebuilt image on host stack

After CI publishes the new image (or after a manual push):
```bash
docker compose pull dark-factory
# If running the scheduler profile:
docker compose pull backlog-scheduler
```

---

## Alternatives Considered

### A. Merge to main, rely on CI cold-cache rebuild (no workflow change)
- **Pro:** zero extra steps; GitHub-hosted runners usually have cold layer caches on a fresh merge.  
- **Con:** "usually" is not guaranteed. If the ubuntu-eviction layer was cached from a prior CI run on the same runner set, the bug would survive undetected until the next --no-cache build. Given the bug hid behind warm caches for months, this risk is non-trivial.  
- **Decision:** Not chosen. The one-line `no-cache: true` addition (Option A) or a local build (Option B) costs almost nothing and guarantees correctness.

### B. Add a CI gate that verifies `whoami` in the built image
- **Pro:** Prevents regression; proves correctness in CI rather than manually.  
- **Con:** Extends the CI workflow definition and requires the smoke commands to run inside `docker/build-push-action`'s test phase, which adds complexity.  
- **Decision:** Deferred; could be a follow-up in #272. Current task is verification + publish, not CI hardening.

---

## Open Questions

- Should `ci-publish.yml` permanently include `no-cache: true` for the `build-dark-factory` step, or only for this one-time rebuild? (If left off, the ubuntu-eviction bug could recur on future Dockerfile changes that hit a cached layer boundary.) Recommend: keep `no-cache: false` (default) for speed, but add the smoke checklist to the publish workflow's test matrix as part of #272.

---

## Assumptions

- [A1] The six code changes listed under "Problem" are correctly committed on the `main` branch (or the feature branch being merged). The spec does not add or modify any source files.  
- [A2] No `user:` override is present in `docker-compose.yml` for either `dark-factory` or `backlog-scheduler` that would defeat the Dockerfile's `USER factory` directive. (Confirmed: no override exists.)  
- [A3] The `scheduler_state` named volume initializes as factory-owned on first use because `/var/lib/dark-factory` is pre-created and chowned in the image build — no host-side `chown` step is needed.
