Now I have the full picture. The `backlog-scheduler` uses the `.:/workspace/project:ro` bind-mount so that `scheduler.sh` can reference `/workspace/project/docker-compose.yml` at line 140 — this is a hard runtime dependency. Removing the bind-mount without modifying the Dockerfile or the scheduler script would break the scheduler. This is the most significant gap in the spec and needs to be surfaced clearly.

Here is the corrected spec:

---

# Docker Compose Dev/Live Split — Design Spec

## Overview

Docker Compose services currently bind-mount the host working tree directly into running containers, meaning any file edit or branch switch immediately changes what the live stack executes — with no build or deploy step in between. This makes it impossible to separate "code being developed" from "code currently serving requests or running scheduled scans," and caused a real incident where a fix only stayed live as long as the feature branch remained checked out. The fix is to bake source into images in the base compose and restore bind-mounts only in an auto-applied developer override file.

## Requirements

1. Editing any file in the local working tree, or switching git branches, must not change the behavior of a running stack started from the base `docker-compose.yml`.
2. The `docker-compose.override.yml` must restore bind-mounts and hot-reload commands for all six source-serving services so that `docker-compose up -d` in a local dev checkout behaves exactly as today.
3. The six services that lose their bind-mount in the base compose are: `backend`, `celery-worker`, `celery-beat`, `live-scanner`, `frontend`, and `backlog-scheduler`.
4. The base compose must build images from local Dockerfiles on `docker-compose up` (no registry, no mandatory pre-build step) — matching the pattern already established by `docker-compose.preview.yml`.
5. Services with no source bind-mount today (`flower`, `forecast-worker`) must not be changed.
6. Each of the six affected services in `docker-compose.yml` must carry a one-line inline comment indicating that the bind-mount is restored in `docker-compose.override.yml`.
7. `CLAUDE.md` must include a brief note in the Docker commands section explaining the dev/live split.
8. `DEVELOPMENT.md` must include a dedicated subsection explaining the override file, which services it covers, how to run without it (`docker-compose -f docker-compose.yml up -d`), and how to force a rebuild.
9. `CLAUDE.md` Dark Factory section must include a sentence clarifying that preview stacks deliberately omit the override file and always run baked images.
10. No new tooling, Makefile targets, or shell aliases are required.

## Architecture

### Approach

The base `docker-compose.yml` becomes the stable, image-baked definition: all `volumes` entries that mount `./backend:/app:ro`, `./frontend:/app`, or `.:/workspace/project:ro` are removed from the six affected services, and any hot-reload command flags (`--reload`, `watchfiles`) move to the override. Docker Compose's automatic merge behavior means that when `docker-compose.override.yml` is present in the same directory — as it always will be in a developer checkout — those volumes and commands are restored transparently. When the override is absent (CI, preview stacks, dark-factory containers), the stack runs the baked artifact with no working-tree exposure.

This approach is consistent with the existing `dark-factory/docker-compose.preview.yml`, which already demonstrates the correct pattern: `build:` stanzas with no bind-mounts. The dark-factory workflow already runs from isolated git worktrees at the Archon layer, so no additional worktree isolation is needed at the compose layer. Image sourcing stays simple — `docker-compose up -d` triggers a build from the local Dockerfile when no image exists, matching current behavior for first-time setup and CI.

### File Layout

- **`docker-compose.yml`** — modified: remove bind-mounts and hot-reload commands from the six affected services; add inline comments pointing to the override; retain all `build:` stanzas.
- **`docker-compose.override.yml`** — new file: defines only the delta for the six services — their `volumes` (bind-mounts) and any `command` overrides restoring hot-reload behavior.
- **`backend/Dockerfile`** — no changes. Already copies source into the image (`COPY . .`); the base compose will rely on the Dockerfile's CMD (`uvicorn ... --reload`) being overridden by an explicit `command:` in the base compose that drops `--reload`.
- **`frontend/Dockerfile`** — requires a change. The current Dockerfile CMD is `npm run dev -- --host`, which is a Vite dev server, not a production artifact server. The Dockerfile must gain a separate production stage or a production CMD (e.g., `npx vite preview --host --port 3333` or an nginx step serving `dist/`) so that the base compose can run the frontend without a bind-mount. The exact production serving approach must be confirmed and implemented as part of this change.
- **`dark-factory/Dockerfile`** — no changes for the base compose restructuring; however see the `backlog-scheduler` note below.
- **`CLAUDE.md`** — updated: one to two sentences added to the "Docker (recommended for full stack)" Commands section; one sentence added to the Dark Factory section.
- **`DEVELOPMENT.md`** — updated: new subsection added near the existing "Rebuild images" note covering the dev/live split.

### Service Breakdown

| Service | Change in base `docker-compose.yml` | Restored in `docker-compose.override.yml` | Image source |
|---|---|---|---|
| `backend` | Remove `./backend:/app:ro` volume; add explicit `command:` that runs uvicorn without `--reload` | Add `./backend:/app:ro` volume; override `command:` to restore uvicorn with `--reload` | Built from `./backend/Dockerfile` |
| `celery-worker` | Remove `./backend:/app:ro` volume; remove watchfiles wrapper from `command:`, use plain celery command | Add `./backend:/app:ro` volume; restore watchfiles-wrapped `command:` | Built from `./backend/Dockerfile` |
| `celery-beat` | Remove `./backend:/app:ro` volume | Add `./backend:/app:ro` volume | Built from `./backend/Dockerfile` |
| `live-scanner` | Remove `./backend:/app:ro` volume | Add `./backend:/app:ro` volume | Built from `./backend/Dockerfile` |
| `frontend` | Remove `./frontend:/app` and `/app/node_modules` volumes; add explicit `command:` to serve the built production output (see Dockerfile note above) | Add `./frontend:/app` and `/app/node_modules` volumes; restore Vite dev server `command:` | Built from `./frontend/Dockerfile` (production stage required — see Dockerfile note) |
| `backlog-scheduler` | Remove `.:/workspace/project:ro` volume; `scheduler.sh` must be updated to reference a baked-in copy of `docker-compose.yml` rather than the host-mounted path `/workspace/project/docker-compose.yml` (see implementation note below) | Add `.:/workspace/project:ro` volume | Built from `dark-factory/Dockerfile` |
| `flower` | No change | Not present | Built from `./backend/Dockerfile` (no bind-mount; unchanged) |
| `forecast-worker` | No change | Not present | Built from `./backend/Dockerfile.forecast` (no bind-mount; unchanged) |

**Note on `flower`:** `flower` has a `build:` stanza in the current compose (built from `./backend/Dockerfile`) but no source bind-mount. It is correctly excluded from the six affected services. The service table column "Image source" reflects the actual build source from the current compose file.

**Note on `backlog-scheduler`:** `scheduler.sh` (line 140) invokes `docker compose -f /workspace/project/docker-compose.yml ...`, which hard-codes the bind-mount path. Removing the `.:/workspace/project:ro` volume from the base compose will break the scheduler when the override is absent unless either: (a) `dark-factory/Dockerfile` copies `docker-compose.yml` into the image at build time and `scheduler.sh` is updated to use that baked path, or (b) the scheduler is excluded from this change and its bind-mount is treated as infrastructure rather than source. Option (a) is preferred for consistency with the design goal. The implementer must resolve this before removing the bind-mount.

Each of the six rows in the base compose gets a comment on the service block, e.g.:

```yaml
# Source bind-mount restored in docker-compose.override.yml for local dev (hot-reload).
```

### Developer Workflow

**Dev mode (local checkout, hot-reload active):**

1. Clone the repo — `docker-compose.override.yml` is present in the working tree.
2. Run `docker-compose up -d`. Docker Compose auto-merges the override; bind-mounts and hot-reload commands are active. Behavior is identical to today.
3. Edit source files — changes are picked up immediately by `--reload`/Vite as today.
4. Switch branches — the working tree changes, the running containers reflect it (this is intentional and expected in dev mode with the override present).

**Live/stable mode (CI, preview stacks, dark-factory, any non-dev context):**

1. Ensure `docker-compose.override.yml` is absent or explicitly excluded with `-f docker-compose.yml`. It is never present in the dark-factory container clone, in CI runners, or in preview stacks.
2. Run `docker-compose -f docker-compose.yml up -d` (or add `--build` to force a rebuild from current source). Images are built from Dockerfiles and run as baked artifacts.
3. Editing files or switching branches has no effect on the running stack.
4. To deploy a new version: `docker-compose -f docker-compose.yml up -d --build` — rebuilds images from the current working tree and replaces containers.

**No new commands to learn.** Developers with the override present use the same `docker-compose up -d` as today. The `-f docker-compose.yml` flag is only needed in contexts where the override file is present but must be intentionally bypassed.

## Alternatives Considered

### Option A: `docker-compose.override.yml` (auto-applied)

Chosen approach. Docker Compose automatically merges `docker-compose.override.yml` when present, which is the canonical mechanism for this exact split. Preserves existing `docker-compose up -d` muscle memory with zero friction and matches the acceptance criterion that hot-reload is preserved as an opt-in dev convenience.

### Option B: Named `docker-compose.dev.yml` (explicit `-f` flag)

Rejected. Requires developers to run `docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d`, breaking existing muscle memory. The added friction is not justified for a single-developer or small-team context, and no Makefile or alias target was deemed necessary to paper over it.

### Option C: Git worktree isolation

Rejected. Running the long-running stack from a separate worktree checkout would duplicate isolation the dark-factory workflow already provides at the Archon layer, and it would not fix the base `docker-compose up` workflow for developers who are not using Archon. It also adds conceptual overhead without solving the underlying compose-layer problem.

## Implementation Plan

1. Read the current `docker-compose.yml` in full to record the exact volume and command definitions for all six affected services.
2. Resolve the frontend production serving command: inspect `frontend/Dockerfile` and determine the correct production CMD (e.g., `npx vite preview --host --port 3333`). If the Dockerfile has no production stage, add one or add a production CMD before proceeding. Document the chosen command explicitly.
3. Resolve the `backlog-scheduler` bind-mount dependency: update `scheduler.sh` to use a path that is baked into the image (e.g., `/opt/dark-factory/docker-compose.yml`) and update `dark-factory/Dockerfile` to `COPY docker-compose.yml /opt/dark-factory/docker-compose.yml` at build time. Verify the baked copy is sufficient for the scheduler's runtime needs.
4. Edit `docker-compose.yml`:
   a. Remove `./backend:/app:ro` volumes from `backend`, `celery-worker`, `celery-beat`, and `live-scanner`.
   b. Add an explicit `command:` to `backend` that runs uvicorn without `--reload` (since the Dockerfile CMD includes `--reload` and the base compose must override it).
   c. Update `celery-worker` `command:` to remove the watchfiles wrapper, using the plain celery worker invocation.
   d. Remove `./frontend:/app` and `/app/node_modules` volumes from `frontend`; add or update the `command:` to use the production serving command determined in step 2.
   e. Remove `.:/workspace/project:ro` volume from `backlog-scheduler`.
   f. Add one-line inline comment to each of the six service blocks.
5. Create `docker-compose.override.yml` defining only the six service overrides: their `volumes` entries and the `command` overrides that restore hot-reload behavior.
6. Verify that `docker-compose config` (with override present) produces a merged config equivalent to the pre-change `docker-compose.yml`.
7. Verify that `docker-compose -f docker-compose.yml config` (override excluded) produces a config with no source bind-mounts.
8. Update `CLAUDE.md`: add one to two sentences to the "Docker (recommended for full stack)" Commands section; add one sentence to the Dark Factory section clarifying that preview stacks omit the override file.
9. Update `DEVELOPMENT.md`: add a "Dev vs. live stack isolation" subsection near the existing rebuild note, covering the six services, the override file, running without it (`docker-compose -f docker-compose.yml up -d`), and forcing a rebuild.
10. Commit all changes together in a single PR so the override file and base compose changes are always in sync.

## Documentation Updates

**`CLAUDE.md` — Commands section:** Add after the existing Docker block — a note that `docker-compose up -d` auto-applies `docker-compose.override.yml` in local dev checkouts (restoring bind-mounts and hot-reload), and that running without the override (CI, preview stacks) uses only baked images (`docker-compose -f docker-compose.yml up -d`).

**`CLAUDE.md` — Dark Factory section:** Add one sentence clarifying that the dark-factory workflow and preview stacks deliberately omit `docker-compose.override.yml` and always run baked images, so agents authoring dark-factory workflows must not rely on bind-mount behavior.

**`DEVELOPMENT.md` — new "Dev vs. live stack isolation" subsection:** Slot near the existing "Rebuild images after Dockerfile or dependency changes" note. Contents: what the override file does, which six services it covers, how to run the stable/baked stack (`docker-compose -f docker-compose.yml up -d`), and how to force a rebuild after source changes (`docker-compose -f docker-compose.yml up -d --build`).

**`docker-compose.yml` — inline comments:** One comment per affected service block indicating the bind-mount is restored in the override file for local dev hot-reload.

## Resolved Items

- **`.gitignore` hygiene:** `docker-compose.override.yml` is not listed in the repo's `.gitignore`. It must be committed to the repository so all developers receive it automatically on clone. No `.gitignore` changes are needed.
- **`flower` image source:** `flower` is built from `./backend/Dockerfile` (not a pulled image). It has no source bind-mount and requires no changes. The service table reflects this accurately.
- **`forecast-worker`:** Confirmed no source bind-mount in the current compose. No changes required.

## Open Questions

- **Frontend production serving command:** The `frontend/Dockerfile` CMD is `npm run dev -- --host` (Vite dev server). There is no existing production/nginx serving layer. The implementer must decide and implement a production serving approach before removing the bind-mount from the base compose. Options include: adding a multi-stage Dockerfile with an nginx or static server stage; or serving the Vite build output with `npx vite preview --host --port 3333`. The chosen approach must be confirmed and the Dockerfile updated accordingly.
- **`backlog-scheduler` baked path:** Confirm that copying `docker-compose.yml` into the dark-factory image at `/opt/dark-factory/docker-compose.yml` and updating `scheduler.sh` line 140 is sufficient — i.e., that the scheduler does not need the full working tree for any other purpose at runtime.
- **CI configuration:** Confirm that CI pipelines (if any) do not have `docker-compose.override.yml` present in their working directory. If CI runs from the repo root with the committed override file present, a step to explicitly invoke `docker-compose -f docker-compose.yml up -d` (bypassing the override) will be needed.

## Assumptions

- `docker-compose.override.yml` will be committed to the repository (not gitignored), so all developers get it automatically on clone. Confirmed: `docker-compose.override.yml` does not appear in `.gitignore`.
- The `backend/Dockerfile` already produces a fully functional image when run without a bind-mount (`COPY . .` is present). Confirmed.
- The `frontend/Dockerfile` requires an additional production serving stage or CMD before the base compose bind-mount can be removed. This is a prerequisite implementation task, not an assumption.
- The dark-factory container entrypoint clones the repo fresh into `/workspace` and the `docker-compose.override.yml` is not copied into the container. Confirmed: `dark-factory/Dockerfile` copies only `entrypoint.sh`, `scheduler.sh`, `docker-compose.preview.yml`, seed data, and refinement skills — not the override file.
- `flower` and `forecast-worker` have no source bind-mounts today and require no changes. Confirmed by inspection of `docker-compose.yml`.
- No container registry exists yet; image sourcing remains local Dockerfile builds for the scope of this issue.

## Relation to Other Issues

This issue is a direct prerequisite for **#104** (container registry and CI/CD deployment pipeline). #104's Option 3 — running registry-pulled or CI-built images — requires that the base compose not bind-mount source over the image layer. Completing #146 first establishes the correct compose structure (baked images in base, bind-mounts in dev override) so that #104 can simply substitute `image: registry/markethawk-backend:sha` in the base compose without any further structural changes. The two issues are intentionally tracked separately so #146 can land as a standalone fix before the broader #104 epic.
