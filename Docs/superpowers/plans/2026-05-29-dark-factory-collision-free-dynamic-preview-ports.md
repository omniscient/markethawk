# Dark Factory: Collision-Free Dynamic Preview Port Allocation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the collision-prone `ISSUE % 100` modulo slot formula in `archon-dark-factory.yaml` with a Docker-label-based free-slot pool algorithm, eliminating port collisions between concurrent or high-numbered issue preview stacks.

**Architecture:** All changes are confined to `.archon/workflows/archon-dark-factory.yaml`. The `preview-up` node becomes the single source of truth for the assigned slot: it scans live Docker port bindings to allocate the lowest free 2-digit slot in `00–99` (or recovers an existing one for `Continue` runs), then emits `PREVIEW_SLOT`, `PREVIEW_FRONTEND`, and `PREVIEW_BACKEND` on stdout. The `push-and-pr` and `report` nodes parse these from `$preview-up.output` rather than independently recomputing `PADDED`. The dead `PADDED` computation in `close-preview` is removed.

**Tech Stack:** Bash, Docker (`docker ps`, `docker compose`)

**Spec:** [`Docs/superpowers/specs/2026-05-29-dark-factory-collision-free-dynamic-preview-ports-design.md`](../specs/2026-05-29-dark-factory-collision-free-dynamic-preview-ports-design.md)
**Issue:** [#124](https://github.com/omniscient/markethawk/issues/124)

---

### File Structure

| File | Change |
|------|--------|
| `.archon/workflows/archon-dark-factory.yaml` | 4 targeted edits across `close-preview`, `preview-up`, `push-and-pr`, and `report` nodes |
| `dark-factory/docker-compose.preview.yml` | No change — continues consuming `ISSUE_NUM_PADDED` env var |
| `dark-factory/entrypoint.sh` | No change — does not compute slot values |

---

### Task 1: Remove dead `PADDED` computation from `close-preview`

**Files:** `.archon/workflows/archon-dark-factory.yaml` (line 171)

- [ ] **Step 1: Verify current state**

```bash
grep -n "PADDED" .archon/workflows/archon-dark-factory.yaml
```

Expected: Line ~171 shows `PADDED=$(printf "%02d" $((ISSUE % 100)))` inside the `close-preview` node, followed by three more occurrences in `preview-up`, `push-and-pr`, and `report`.

- [ ] **Step 2: Remove the dead PADDED line from `close-preview`**

In `.archon/workflows/archon-dark-factory.yaml`, remove the `PADDED` assignment and its comment from the `close-preview` bash block:

Before:
```yaml
  - id: close-preview
    bash: |
      ISSUE=$(echo $fetch-issue.output | jq -r '.resolved_number')
      EPIC_NUM=$(echo $fetch-issue.output | jq -r '.epic_number // empty')
      PADDED=$(printf "%02d" $((ISSUE % 100)))  # slot 00-99 keeps preview ports <= 65535 (3-digit issues would overflow, e.g. #100 -> 110033)

      echo "Tearing down mh-preview-${ISSUE}..."
```

After:
```yaml
  - id: close-preview
    bash: |
      ISSUE=$(echo $fetch-issue.output | jq -r '.resolved_number')
      EPIC_NUM=$(echo $fetch-issue.output | jq -r '.epic_number // empty')

      echo "Tearing down mh-preview-${ISSUE}..."
```

- [ ] **Step 3: Verify YAML is valid**

```bash
python3 -c "import yaml; yaml.safe_load(open('.archon/workflows/archon-dark-factory.yaml'))" && echo "YAML OK"
```

Expected output: `YAML OK`

- [ ] **Step 4: Verify `close-preview` no longer references PADDED**

```bash
awk '/id: close-preview/,/^  - id:/' .archon/workflows/archon-dark-factory.yaml | grep -c "PADDED"
```

Expected output: `0`

- [ ] **Step 5: Commit**

```bash
git add .archon/workflows/archon-dark-factory.yaml
git commit -m "refactor(dark-factory): remove dead PADDED from close-preview (#124)"
```

---

### Task 2: Replace PADDED computation in `preview-up` with free-slot allocator

**Files:** `.archon/workflows/archon-dark-factory.yaml` (lines 293–298, 339–341)

This is the core change. The slot allocator first checks if a preview for this issue is already running (Continue scenario) and recovers the slot from Docker's port bindings; otherwise it scans all bound `1XX33` host ports to find the lowest free 2-digit slot. `INFO:` diagnostics go to stderr to avoid polluting `$preview-up.output` for downstream parsers. `PREVIEW_SLOT` is added to the existing stdout emissions so downstream nodes can build postgres and redis port strings.

- [ ] **Step 1: Verify current state**

```bash
awk '/id: preview-up/,/export ISSUE_NUM_PADDED/' .archon/workflows/archon-dark-factory.yaml | tail -5
```

Expected: Shows the old comment block and `PADDED=$(printf "%02d" $((ISSUE % 100)))` followed by `export ISSUE_NUM_PADDED="$PADDED"`.

- [ ] **Step 2: Replace the modulo formula block with the free-slot allocator**

In `.archon/workflows/archon-dark-factory.yaml`, in the `preview-up` bash block, replace the comment-plus-PADDED block (lines ~293–298):

Before:
```bash
      # Preview ports follow 1{SLOT}{suffix} (e.g. slot 03 -> frontend 10333, backend 10380).
      # SLOT must stay 2 digits or the port exceeds 65535 (issue #100 produced 110033 -> "invalid hostPort").
      # Map the issue number into a 2-digit slot via modulo. Caveat: two previews whose issue numbers are
      # congruent mod 100 collide on ports; acceptable given the single-factory guard + teardown on close.
      PADDED=$(printf "%02d" $((ISSUE % 100)))  # slot 00-99 keeps preview ports <= 65535 (3-digit issues would overflow, e.g. #100 -> 110033)
      export ISSUE_NUM_PADDED="$PADDED"
```

After:
```bash
      # Resolve slot: recover from running preview if it exists, else allocate the lowest free slot in 00-99.
      # Scanning live Docker port bindings guarantees no collision even when two issue numbers are congruent mod 100.
      EXISTING_PORTS=$(docker ps --filter "label=com.docker.compose.project=mh-preview-${ISSUE}" --format '{{.Ports}}' 2>/dev/null | head -1)
      if [ -n "$EXISTING_PORTS" ]; then
        PADDED=$(echo "$EXISTING_PORTS" | grep -oP '(?<=:1)\d{2}(?=33->)' | head -1)
        if [ -z "$PADDED" ]; then
          echo "ERROR: Could not parse slot from existing preview ports: $EXISTING_PORTS" >&2
          exit 1
        fi
        echo "INFO: Recovered existing slot $PADDED for issue #${ISSUE}" >&2
      else
        USED_SLOTS=$(docker ps --format '{{.Ports}}' 2>/dev/null \
          | grep -oP '(?<=:1)\d{2}(?=33->)' \
          | sort -u)
        PADDED=""
        for i in $(seq -w 0 99); do
          SLOT=$(printf "%02d" $i)
          if ! echo "$USED_SLOTS" | grep -qx "$SLOT"; then
            PADDED="$SLOT"
            break
          fi
        done
        if [ -z "$PADDED" ]; then
          echo "ERROR: No free preview slot in range 00-99. Run 'Close issue #N' on a stale preview to free a slot." >&2
          exit 1
        fi
        echo "INFO: Allocated slot $PADDED for issue #${ISSUE}" >&2
      fi
      export ISSUE_NUM_PADDED="$PADDED"
```

- [ ] **Step 3: Add PREVIEW_SLOT to the stdout emissions on successful backend health**

In the `preview-up` bash block, find the echo lines inside the health-check success path:

Before:
```bash
          echo "PREVIEW_FRONTEND=http://localhost:1${PADDED}33"
          echo "PREVIEW_BACKEND=http://localhost:1${PADDED}80"
          echo "PREVIEW_MOUNT_SECS=${PREVIEW_SECS}"
```

After:
```bash
          echo "PREVIEW_SLOT=${PADDED}"
          echo "PREVIEW_FRONTEND=http://localhost:1${PADDED}33"
          echo "PREVIEW_BACKEND=http://localhost:1${PADDED}80"
          echo "PREVIEW_MOUNT_SECS=${PREVIEW_SECS}"
```

- [ ] **Step 4: Verify the modulo formula is gone from `preview-up`**

```bash
awk '/id: preview-up/,/^  - id:/' .archon/workflows/archon-dark-factory.yaml | grep "ISSUE % 100"
```

Expected output: (empty — no match)

- [ ] **Step 5: Verify the slot allocator is present**

```bash
grep -c "No free preview slot in range 00-99" .archon/workflows/archon-dark-factory.yaml
```

Expected output: `1`

- [ ] **Step 6: Verify PREVIEW_SLOT is emitted**

```bash
grep -c "echo \"PREVIEW_SLOT=" .archon/workflows/archon-dark-factory.yaml
```

Expected output: `1`

- [ ] **Step 7: Verify YAML is valid**

```bash
python3 -c "import yaml; yaml.safe_load(open('.archon/workflows/archon-dark-factory.yaml'))" && echo "YAML OK"
```

Expected output: `YAML OK`

- [ ] **Step 8: Commit**

```bash
git add .archon/workflows/archon-dark-factory.yaml
git commit -m "feat(dark-factory): replace modulo slot with free-slot pool allocator in preview-up (#124)"
```

---

### Task 3: Update `push-and-pr` to parse URLs from `$preview-up.output`

**Files:** `.archon/workflows/archon-dark-factory.yaml` (line ~365, lines ~398–399)

- [ ] **Step 1: Verify current state**

```bash
awk '/id: push-and-pr/,/^  - id:/' .archon/workflows/archon-dark-factory.yaml | grep -n "PADDED\|PREVIEW_"
```

Expected: One `PADDED=$(printf ...)` line and two inline `1${PADDED}33` / `1${PADDED}80` references in the PR body template.

- [ ] **Step 2: Replace PADDED recomputation with URL parsing**

In the `push-and-pr` bash block, replace:

Before:
```bash
      ISSUE=$(echo $fetch-issue.output | jq -r '.resolved_number')
      EPIC_NUM=$(echo $fetch-issue.output | jq -r '.epic_number // empty')
      PADDED=$(printf "%02d" $((ISSUE % 100)))  # slot 00-99 keeps preview ports <= 65535 (3-digit issues would overflow, e.g. #100 -> 110033)
      BRANCH=$(git branch --show-current)
```

After:
```bash
      ISSUE=$(echo $fetch-issue.output | jq -r '.resolved_number')
      EPIC_NUM=$(echo $fetch-issue.output | jq -r '.epic_number // empty')
      PREVIEW_FRONTEND=$(echo "$preview-up.output" | grep '^PREVIEW_FRONTEND=' | cut -d= -f2-)
      PREVIEW_BACKEND=$(echo "$preview-up.output" | grep '^PREVIEW_BACKEND=' | cut -d= -f2-)
      BRANCH=$(git branch --show-current)
```

- [ ] **Step 3: Replace inline port strings in the PR body template**

In the `push-and-pr` bash block, replace the two PR body lines:

Before:
```bash
      - Frontend: http://localhost:1${PADDED}33
      - Backend API: http://localhost:1${PADDED}80/docs
```

After:
```bash
      - Frontend: ${PREVIEW_FRONTEND}
      - Backend API: ${PREVIEW_BACKEND}/docs
```

- [ ] **Step 4: Verify `push-and-pr` no longer references PADDED**

```bash
awk '/id: push-and-pr/,/^  - id:/' .archon/workflows/archon-dark-factory.yaml | grep "PADDED"
```

Expected output: (empty)

- [ ] **Step 5: Verify PREVIEW_FRONTEND and PREVIEW_BACKEND are assigned and used**

```bash
awk '/id: push-and-pr/,/^  - id:/' .archon/workflows/archon-dark-factory.yaml | grep -c "PREVIEW_"
```

Expected output: `4` (two assignments + two usages in PR body)

- [ ] **Step 6: Verify YAML is valid**

```bash
python3 -c "import yaml; yaml.safe_load(open('.archon/workflows/archon-dark-factory.yaml'))" && echo "YAML OK"
```

Expected output: `YAML OK`

- [ ] **Step 7: Commit**

```bash
git add .archon/workflows/archon-dark-factory.yaml
git commit -m "refactor(dark-factory): consume preview URLs from preview-up output in push-and-pr (#124)"
```

---

### Task 4: Update `report` to parse URLs from `$preview-up.output`

**Files:** `.archon/workflows/archon-dark-factory.yaml` (line ~449, lines ~483–487)

The `report` node renders all five service URLs: frontend, backend, api docs, postgres (port suffix `54`), and redis (port suffix `63`). `PREVIEW_SLOT` provides the 2-digit slot for constructing the postgres and redis host strings; `PREVIEW_FRONTEND` and `PREVIEW_BACKEND` replace the frontend/backend/api-docs rows directly.

- [ ] **Step 1: Verify current state**

```bash
awk '/id: report/,/depends_on: \[status-in-review\]/' .archon/workflows/archon-dark-factory.yaml | grep -n "PADDED\|PREVIEW_"
```

Expected: One `PADDED=$(printf ...)` line and five `1${PADDED}` port references in the issue comment table.

- [ ] **Step 2: Replace PADDED recomputation with URL parsing**

In the `report` bash block, replace:

Before:
```bash
      ISSUE=$(echo $fetch-issue.output | jq -r '.resolved_number')
      EPIC_NUM=$(echo $fetch-issue.output | jq -r '.epic_number // empty')
      PADDED=$(printf "%02d" $((ISSUE % 100)))  # slot 00-99 keeps preview ports <= 65535 (3-digit issues would overflow, e.g. #100 -> 110033)
      INTENT=$parse-intent.output.intent
```

After:
```bash
      ISSUE=$(echo $fetch-issue.output | jq -r '.resolved_number')
      EPIC_NUM=$(echo $fetch-issue.output | jq -r '.epic_number // empty')
      PREVIEW_SLOT=$(echo "$preview-up.output" | grep '^PREVIEW_SLOT=' | cut -d= -f2-)
      PREVIEW_FRONTEND=$(echo "$preview-up.output" | grep '^PREVIEW_FRONTEND=' | cut -d= -f2-)
      PREVIEW_BACKEND=$(echo "$preview-up.output" | grep '^PREVIEW_BACKEND=' | cut -d= -f2-)
      INTENT=$parse-intent.output.intent
```

- [ ] **Step 3: Replace inline port strings in the issue comment table**

In the `report` bash block, replace the five table rows:

Before:
```bash
      | Frontend | http://localhost:1${PADDED}33 |
      | Backend API | http://localhost:1${PADDED}80 |
      | API Docs | http://localhost:1${PADDED}80/docs |
      | PostgreSQL | \`localhost:1${PADDED}54\` |
      | Redis | \`localhost:1${PADDED}63\` |
```

After:
```bash
      | Frontend | ${PREVIEW_FRONTEND} |
      | Backend API | ${PREVIEW_BACKEND} |
      | API Docs | ${PREVIEW_BACKEND}/docs |
      | PostgreSQL | \`localhost:1${PREVIEW_SLOT}54\` |
      | Redis | \`localhost:1${PREVIEW_SLOT}63\` |
```

- [ ] **Step 4: Verify `report` no longer references PADDED**

```bash
awk '/id: report/,/depends_on: \[status-in-review\]/' .archon/workflows/archon-dark-factory.yaml | grep "PADDED"
```

Expected output: (empty)

- [ ] **Step 5: Verify YAML is valid**

```bash
python3 -c "import yaml; yaml.safe_load(open('.archon/workflows/archon-dark-factory.yaml'))" && echo "YAML OK"
```

Expected output: `YAML OK`

- [ ] **Step 6: Confirm only the intentional `export ISSUE_NUM_PADDED` remains in the file**

```bash
grep -n "PADDED" .archon/workflows/archon-dark-factory.yaml
```

Expected: Exactly one occurrence — `export ISSUE_NUM_PADDED="$PADDED"` in `preview-up` (intentional export for `docker-compose.preview.yml`).

- [ ] **Step 7: Commit**

```bash
git add .archon/workflows/archon-dark-factory.yaml
git commit -m "refactor(dark-factory): consume preview URLs from preview-up output in report (#124)"
```

---

### Task 5: Verify `docker-compose.preview.yml` and `entrypoint.sh` require no changes

**Files:** `dark-factory/docker-compose.preview.yml`, `dark-factory/entrypoint.sh`

- [ ] **Step 1: Confirm `docker-compose.preview.yml` consumes `ISSUE_NUM_PADDED` with a safe default**

```bash
grep "ISSUE_NUM_PADDED" dark-factory/docker-compose.preview.yml
```

Expected: Shows `${ISSUE_NUM_PADDED:-00}` or similar. Since `preview-up` still exports `ISSUE_NUM_PADDED` (now set to the dynamically allocated slot), this file needs no changes.

- [ ] **Step 2: Confirm `entrypoint.sh` has no PADDED references**

```bash
grep -c "PADDED\|ISSUE_NUM_PADDED" dark-factory/entrypoint.sh
```

Expected output: `0`

- [ ] **Step 3: Confirm only the intended PADDED reference remains across the whole repo**

```bash
grep -rn "PADDED" .archon/ dark-factory/
```

Expected: Exactly two lines in `.archon/workflows/archon-dark-factory.yaml` — `PADDED=""` (loop variable) and `export ISSUE_NUM_PADDED="$PADDED"`. No occurrences in `dark-factory/`.

---

### Task 6: Integration smoke test

**Files:** (none — manual end-to-end verification)

- [ ] **Step 1: Run `Fix issue #100` — slot allocated, not determined by modulo**

```bash
docker compose --profile factory run --rm dark-factory "Fix issue #100"
```

Expected:
- `preview-up` logs `INFO: Allocated slot XX for issue #100` to stderr (e.g., slot `00` if free, or the lowest available)
- `preview-up` stdout contains `PREVIEW_SLOT=XX`, `PREVIEW_FRONTEND=http://localhost:1XX33`, `PREVIEW_BACKEND=http://localhost:1XX80`
- PR body shows `http://localhost:1XX33` and `http://localhost:1XX80/docs` (matching the allocated slot)
- Issue comment table rows match the same URLs

- [ ] **Step 2: Run `Fix issue #200` while `#100` preview is running — different slot, no port conflict**

```bash
docker compose --profile factory run --rm dark-factory "Fix issue #200"
```

Expected:
- `preview-up` allocates a different slot than the one held by `#100`
- Both stacks run simultaneously without a "port is already allocated" Docker error

- [ ] **Step 3: Run `Continue issue #100` — recovers original slot, not re-allocated**

```bash
docker compose --profile factory run --rm dark-factory "Continue issue #100"
```

Expected:
- `preview-up` logs `INFO: Recovered existing slot XX for issue #100` to stderr
- Same slot (and same URLs) from Step 1 are re-emitted and appear in the updated issue comment

- [ ] **Step 4: Tear down both previews cleanly**

```bash
docker compose --profile factory run --rm dark-factory "Close issue #100"
docker compose --profile factory run --rm dark-factory "Close issue #200"
```

Expected: Both stacks torn down without errors. `close-preview` works correctly using only the project name `mh-preview-${ISSUE}` — no PADDED reference is executed.
