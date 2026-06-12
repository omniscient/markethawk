#!/usr/bin/env bash
# Smoke gate: verifies origin/main is buildable before per-ticket factory work begins.
# Sourced by entrypoint.sh. Set SMOKE_GATE_SOURCE_ONLY=1 before sourcing in tests.
# On red main: exits 0 (no ERR trap, no per-ticket board/retry/breaker change).
# On green main: cleans up any prior red state and returns 0.

SMOKE_STATE_DIR="${SCHEDULER_STATE_DIR:-/var/lib/dark-factory}"
SMOKE_MARKER="<!-- df-main-red -->"

# Runs tsc + python import on origin/main. Returns 0 on full pass, non-zero on first failure.
_smoke_check_main() {
  echo "[smoke_gate] Checking frontend TypeScript (tsc)..."
  if ! (cd "${CLONE_DIR:-/workspace/markethawk}/frontend" \
        && rm -f tsconfig.app.tsbuildinfo \
        && npx tsc -p tsconfig.app.json --noEmit 2>&1); then
    echo "[smoke_gate] tsc FAILED — main is red"
    return 1
  fi
  echo "[smoke_gate] Checking backend Python import graph..."
  # Settings() is instantiated at import time and requires DATABASE_URL /
  # POLYGON_API_KEY / JWT_SECRET_KEY (>=32 chars; preview env contract, #190).
  # The gate verifies the import graph compiles, NOT that config is real —
  # without throwaway values the check is red in every factory container, so
  # every fix/continue/deconflict run false-latches the sentinel (#365). Same
  # pattern as docker-compose.preview.yml and ci.yml.
  if ! (cd "${CLONE_DIR:-/workspace/markethawk}/backend" \
        && DATABASE_URL="postgresql://smoke:smoke@localhost:5432/smoke" \
           POLYGON_API_KEY="smoke-gate-only-not-a-real-key" \
           JWT_SECRET_KEY="smoke-gate-only-not-secret-0123456789abcdef" \
           python -c "import app.main" 2>&1); then
    echo "[smoke_gate] python import FAILED — main is red"
    return 1
  fi
  return 0
}

# Writes sentinel, files or updates the regression ticket, then exits 0 (clean halt).
_smoke_on_red() {
  echo "[smoke_gate] main is RED — halting factory run cleanly (exit 0, no per-ticket failure)"
  mkdir -p "${SMOKE_STATE_DIR}"
  touch "${SMOKE_STATE_DIR}/main-is-red"
  # Stamp the recheck throttle: red was just confirmed, so the scheduler's first
  # "Recheck main" dispatch (#365) should wait a full MAIN_RED_RECHECK_MINUTES.
  touch "${SMOKE_STATE_DIR}/main-red-last-recheck"

  local ISSUE_FILE="${SMOKE_STATE_DIR}/main-is-red-issue"
  if [ -f "$ISSUE_FILE" ]; then
    local REGR_NUM
    REGR_NUM=$(cat "$ISSUE_FILE")
    gh issue comment "$REGR_NUM" \
      --repo "${OWNER:-omniscient}/markethawk" \
      --body "main still red at $(date -u +%FT%TZ) — factory implementation runs remain paused." \
      2>/dev/null || true
  else
    local REGR_URL
    REGR_URL=$(gh issue create \
      --repo "${OWNER:-omniscient}/markethawk" \
      --label regression \
      --title "main is red: tsc/python import failure" \
      --body "${SMOKE_MARKER}

**main smoke check failed at $(date -u +%FT%TZ).**

The dark factory is pausing all implementation dispatches (Priority 1.5/2/3) until \`origin/main\` compiles cleanly.

This ticket closes automatically on the next green gate pass." \
      2>/dev/null || true)
    local REGR_NUM
    REGR_NUM=$(echo "$REGR_URL" | grep -oE '[0-9]+$' || true)
    [ -n "$REGR_NUM" ] && echo "$REGR_NUM" > "$ISSUE_FILE"
  fi

  exit 0
}

# On green: removes sentinel (if present) and closes regression ticket (if open).
_smoke_on_green() {
  if [ ! -f "${SMOKE_STATE_DIR}/main-is-red" ]; then
    return 0
  fi
  echo "[smoke_gate] main is GREEN — removing red sentinel and closing regression ticket"
  rm -f "${SMOKE_STATE_DIR}/main-is-red" "${SMOKE_STATE_DIR}/main-red-last-recheck"

  local ISSUE_FILE="${SMOKE_STATE_DIR}/main-is-red-issue"
  if [ -f "$ISSUE_FILE" ]; then
    local REGR_NUM
    REGR_NUM=$(cat "$ISSUE_FILE")
    gh issue close "$REGR_NUM" \
      --repo "${OWNER:-omniscient}/markethawk" \
      --comment "main smoke gate passed — closing regression ticket." \
      2>/dev/null || true
    rm -f "$ISSUE_FILE"
  fi
}

# Main entry point called by entrypoint.sh.
# Returns 0 on green (proceed); exits 0 on red (clean halt, no per-ticket failure).
run_smoke_gate() {
  if _smoke_check_main; then
    _smoke_on_green
    return 0
  else
    _smoke_on_red
    # _smoke_on_red calls exit 0; unreachable
  fi
}

# Source-only guard: when set, functions above are defined but no auto-exec code runs.
# Mirrors scheduler.sh's SCHEDULER_SOURCE_ONLY pattern for unit testing.
if [ "${SMOKE_GATE_SOURCE_ONLY:-0}" = "1" ]; then
  return 0
fi
