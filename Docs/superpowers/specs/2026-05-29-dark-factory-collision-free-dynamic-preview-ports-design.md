# Dark Factory: Collision-Free Dynamic Preview Port Allocation

## Overview

Dark-factory preview stacks bind host ports using the scheme `1{SLOT}{suffix}`, where `SLOT` is a 2-digit string and the suffix encodes the service (`33`=frontend, `80`=backend, `54`=postgres, `63`=redis). The current implementation computes `SLOT` via `PADDED=$(printf "%02d" $((ISSUE % 100)))` in four separate bash nodes inside `.archon/workflows/archon-dark-factory.yaml` (`close-preview`, `preview-up`, `push-and-pr`, `report`).

This modulo heuristic was itself a fix for a prior overflow bug (issue numbers >=100 produced ports like `110033` which Docker rejected). The modulo approach keeps all ports in the range `10033`–`19980` and is backward-compatible for issues <=99, but introduces a **slot collision risk**: any two issue numbers that are congruent mod 100 (e.g., #100 and #200, or #93 and #193) would attempt to bind identical host ports. The second `docker compose up` would fail with "port is already allocated".

Additionally, `PADDED` is computed redundantly and independently in all four workflow nodes, making it error-prone to change. The `close-preview` node computes `PADDED` but never uses it — teardown already works correctly using only the Docker Compose project name `mh-preview-${ISSUE}`.

## Requirements

- Two simultaneous preview stacks must never collide on host ports, regardless of issue number or its relationship to any other active issue number.
- Issue numbers of any magnitude (3+ digits) must be supported without port overflow (all assigned ports must be <=65535).
- The slot must be stable for the lifetime of a preview: a `Continue` run must discover the same slot (and thus the same URLs) that `preview-up` originally assigned.
- Preview URLs posted to the PR body and issue comment must match the actually-bound host ports.
- `Close issue #N` must continue to tear down the correct stack; it must not rely on PADDED for teardown (it already does not — this requirement is maintained).
- If no free slot exists in range 00–99, the factory must fail loudly with a non-zero exit and a human-readable error message, allowing the scheduler's existing `MAX_RETRIES` / Blocked retry path to handle it.
- Every live preview stack holds its slot until an explicit `Close issue #N` command is issued; stale previews are not auto-reclaimed.
- The dead code `PADDED=$(printf "%02d" $((ISSUE % 100)))` in `close-preview` must be removed.
- No backward-compatibility requirement for previews already running under the old scheme; existing previews run to their natural `Close` lifecycle.

## Approach

### Option A: Free-Slot Pool with Docker-Label-Based Slot Recovery (No State File)

On a `Fix` run (fresh `preview-up`), scan all currently bound host ports that match the `1XX{suffix}` pattern via `docker ps --format '{{.Ports}}'`. Derive all occupied 2-digit slots, then pick the lowest free slot in 00–99. Start the preview stack with that slot. On a `Continue` run (preview already up), recover the slot by inspecting the already-running containers for that issue's project via `docker ps --filter "label=com.docker.compose.project=mh-preview-${ISSUE}" --format '{{.Ports}}'` and parsing the bound host port.

In both cases, `preview-up` emits `PREVIEW_FRONTEND=http://localhost:1${SLOT}33` and `PREVIEW_BACKEND=http://localhost:1${SLOT}80` on stdout. Downstream nodes (`push-and-pr`, `report`) parse these lines from `$preview-up.output` instead of recomputing PADDED independently.

**Pros:**
- No state file or external storage needed; Docker's own metadata is the source of truth.
- Collision-free by construction: the free-slot scan sees all currently bound ports before assigning.
- Slot recovery for `Continue` runs is reliable: the running container's port bindings are unambiguous.
- Aligns with the existing pattern of parsing `$node-id.output` in downstream nodes (already used for `$fetch-issue.output`).
- Removes redundant PADDED computation from 4 nodes, centralizing it in `preview-up`.

**Cons:**
- The port scanning bash snippet is slightly complex (requires parsing Docker port output format, e.g., `0.0.0.0:18833->3333/tcp`).
- Requires a race-condition caveat: if two factory runs somehow start simultaneously (the scheduler's concurrency guard prevents this, but as a theoretical concern), both could read the same free slot before either binds it. In practice this is not a concern given the single-factory-at-a-time enforcement.

### Option B: Ephemeral Ports (`-p 0:port`)

Bind all four services with `-p 0:port`, letting Docker assign arbitrary available host ports. After `docker compose up`, inspect the assigned ports via `docker port` or `docker ps`, then embed those URLs in the PR body and issue comment.

**Pros:**
- Guaranteed collision-free; Docker handles allocation.
- No slot arithmetic at all.

**Cons:**
- Ports change on every `Continue` run (the preview stack is restarted), invalidating bookmarked URLs and making the PR body comment immediately stale.
- The PR body and issue comment embed static URLs — a core UX expectation of the existing design. Ephemeral ports break this contract.
- The `docker-compose.preview.yml` parameterization by `ISSUE_NUM_PADDED` would need to be replaced with a different mechanism to surface the actual ports after startup.
- Significantly more disruptive to the existing workflow structure.

### Recommended Approach

**Option A: Free-Slot Pool with Docker-Label-Based Slot Recovery.**

The Q&A established that stable, bookmarkable URLs are a first-class design goal (A1). Option B breaks that goal fundamentally. Option A is minimally invasive — it replaces the single `PADDED=$(printf "%02d" $((ISSUE % 100)))` line in `preview-up` with a free-slot scan, centralizes the slot computation, and uses the already-established `$node-id.output` parsing pattern for downstream nodes. No new infrastructure, no state files, no schema changes.

## Implementation Plan

### Step 1 — Replace PADDED computation in `preview-up` with free-slot allocation

File: `.archon/workflows/archon-dark-factory.yaml`, `preview-up` node (around lines 297–298).

Replace:
```bash
PADDED=$(printf "%02d" $((ISSUE % 100)))
export ISSUE_NUM_PADDED="$PADDED"
```

With the following slot allocator. The allocator first checks if a preview for this issue is already running (Continue scenario), recovers the slot from the live container's ports, and only runs the free-slot scan for fresh Fix runs:

```bash
# Resolve slot: recover from running preview if it exists, else allocate free slot
EXISTING_PORTS=$(docker ps --filter "label=com.docker.compose.project=mh-preview-${ISSUE}" --format '{{.Ports}}' 2>/dev/null | head -1)
if [ -n "$EXISTING_PORTS" ]; then
  # Extract slot from the frontend port binding (pattern: 0.0.0.0:1XX33->3333/tcp)
  PADDED=$(echo "$EXISTING_PORTS" | grep -oP '(?<=:1)\d{2}(?=33->)' | head -1)
  if [ -z "$PADDED" ]; then
    echo "ERROR: Could not parse slot from existing preview ports: $EXISTING_PORTS" >&2
    exit 1
  fi
  echo "INFO: Recovered existing slot $PADDED for issue #${ISSUE}"
else
  # Scan all bound 1XX33 ports (frontend suffix) to find occupied slots
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
  echo "INFO: Allocated slot $PADDED for issue #${ISSUE}"
fi

export ISSUE_NUM_PADDED="$PADDED"
```

Then ensure `preview-up` emits the resolved URLs on stdout (these lines likely already exist but must use the newly computed `$PADDED`):
```bash
echo "PREVIEW_FRONTEND=http://localhost:1${PADDED}33"
echo "PREVIEW_BACKEND=http://localhost:1${PADDED}80"
```

### Step 2 — Update `push-and-pr` to parse URLs from `$preview-up.output`

File: `.archon/workflows/archon-dark-factory.yaml`, `push-and-pr` node (around line 365).

Replace:
```bash
PADDED=$(printf "%02d" $((ISSUE % 100)))
# ... uses 1${PADDED}33 and 1${PADDED}80 inline
```

With:
```bash
PREVIEW_FRONTEND=$(echo "$preview-up.output" | grep '^PREVIEW_FRONTEND=' | cut -d= -f2-)
PREVIEW_BACKEND=$(echo "$preview-up.output" | grep '^PREVIEW_BACKEND=' | cut -d= -f2-)
```

Then replace all inline `http://localhost:1${PADDED}33` and `http://localhost:1${PADDED}80` references in the PR body template with `$PREVIEW_FRONTEND` and `$PREVIEW_BACKEND`.

### Step 3 — Update `report` to parse URLs from `$preview-up.output`

File: `.archon/workflows/archon-dark-factory.yaml`, `report` node (around line 449).

Apply the same substitution as Step 2 — remove the standalone PADDED computation and parse `$preview-up.output` instead:
```bash
PREVIEW_FRONTEND=$(echo "$preview-up.output" | grep '^PREVIEW_FRONTEND=' | cut -d= -f2-)
PREVIEW_BACKEND=$(echo "$preview-up.output" | grep '^PREVIEW_BACKEND=' | cut -d= -f2-)
```

Replace inline port string construction with `$PREVIEW_FRONTEND` and `$PREVIEW_BACKEND`.

### Step 4 — Remove dead code from `close-preview`

File: `.archon/workflows/archon-dark-factory.yaml`, `close-preview` node (around line 171).

Remove the unused line:
```bash
PADDED=$(printf "%02d" $((ISSUE % 100)))
```

The teardown command `docker compose -p "mh-preview-${ISSUE}" down -v` already works correctly by project name and requires no change.

### Step 5 — Verify `dark-factory/docker-compose.preview.yml` requires no changes

File: `dark-factory/docker-compose.preview.yml`.

The file already consumes `ISSUE_NUM_PADDED` as an env var with a safe default (`${ISSUE_NUM_PADDED:-00}`). Since `preview-up` continues to export `ISSUE_NUM_PADDED` (now set to the dynamically allocated slot rather than the modulo result), this file needs no changes.

### Step 6 — Verify `dark-factory/entrypoint.sh` requires no changes

File: `dark-factory/entrypoint.sh`.

The entrypoint does not compute `PADDED` or `ISSUE_NUM_PADDED`; that responsibility belongs entirely to the workflow nodes. No changes needed.

### Step 7 — Manual smoke test

After deploying the change:

1. Run `Fix issue #100` — confirm a slot is allocated (e.g., `01` if slot 01 is free), and that preview URLs in the PR body and issue comment reflect the correct ports (e.g., `http://localhost:10133`, `http://localhost:10180`).
2. While #100's preview is still up, run `Fix issue #200` — confirm it is allocated a different slot (not `00`, which would be `200 % 100 = 00`, the old behavior), and that both stacks run simultaneously without port conflict.
3. Run `Continue issue #100` — confirm the same slot (and same URLs) from step 1 are recovered and re-emitted, not re-allocated.
4. Run `Close issue #100` then `Close issue #200` — confirm both stacks are torn down cleanly.

## Open Questions (non-blocking)

- Whether the `INFO:` log lines emitted by the slot allocator (e.g., "Allocated slot 03 for issue #150") should be written to stderr instead of stdout to avoid polluting `$preview-up.output` for downstream parsers. The downstream grep for `^PREVIEW_FRONTEND=` is robust to extra stdout lines, but directing diagnostics to stderr is cleaner practice.
- Whether a future enhancement should add a `list-previews` workflow node or scheduler command that displays all active preview stacks with their issue numbers, slots, and URLs — useful for operators deciding which stale preview to `Close` when approaching the 100-slot limit.
- Whether the slot scan should prefer the slot equal to `ISSUE % 100` when it is free (preserving the old behavior for issues <=99 that have no conflict), or always pick the lowest free slot. The lowest-free-slot approach is simpler and avoids any coupling to the old heuristic.

## Assumptions

- The Docker Compose port output format (`0.0.0.0:1XX33->3333/tcp`) is stable and parseable with the regex `(?<=:1)\d{2}(?=33->)`. This format has been stable across Docker Engine versions in use.
- The scheduler's single-factory-at-a-time guard (`count_factory_running`) is reliable enough that the race condition between two factories reading the same free slot simultaneously is not a practical concern.
- `$preview-up.output` in Archon bash nodes contains the complete stdout of the `preview-up` bash node, consistent with how `$fetch-issue.output` is consumed by all downstream nodes in the existing workflow.
- The grep pattern using the frontend suffix (`33`) as the anchor for slot detection is unambiguous — no other dark-factory port bindings use the `1XX33` pattern on the host.
- The `seq -w 0 99` approach for iterating slots produces zero-padded output (`00`, `01`, ..., `99`) on the Linux environment used inside the dark-factory container.

## Out of Scope

- Changes to `dark-factory/Dockerfile`, `dark-factory/scheduler.sh`, `dark-factory/entrypoint.sh`, or any backend/frontend application code.
- Auto-reclaiming stale preview slots; stale previews hold their slot until an explicit `Close issue #N` command.
- Expanding the slot range beyond 00–99 or changing the `1{SLOT}{suffix}` port scheme.
- Backward compatibility for previews currently running under the old `ISSUE % 100` scheme; those previews are left to run to their natural `Close` lifecycle.
- Changes to the `close-preview` issue comment content (the comment text is correct; only the dead PADDED computation is removed).
- Adding monitoring, alerting, or dashboards for slot utilization.
- Changing the `dark-factory/docker-compose.preview.yml` port suffix scheme (`33`, `80`, `54`, `63`).
