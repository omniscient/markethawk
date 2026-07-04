#!/usr/bin/env bash
# run_suite.sh — Replay benchmark suite runner
#
# Usage:
#   dark-factory/bench/run_suite.sh [OPTIONS]
#
# Options:
#   --tasks FILE      Path to suite manifest (default: dark-factory/bench/suite.json)
#   --n N             Runs per task (default: 3)
#   --k K             Exponent for pass^k formula (default: same as --n)
#   --baseline        After collecting results, generate Haiku prose summaries and
#                     write/update dark-factory/bench/baseline.md
#   --issues LIST     Comma-separated issue numbers to run (default: all tasks)
#   --dry-run         Print plan without running archon
#
# Environment:
#   BENCH_TOKEN_BUDGET  Soft budget in USD (default: 5.00) — warns on breach
#   BENCH_MODE          Set to 'stub' (default) or 'full' (real preview, no PR)
#   ANTHROPIC_API_KEY   Required for --baseline Haiku summaries
#
# Output:
#   Per-run JSON: dark-factory/bench/results/YYYY-MM-DD-HH-run.json
#   Summary table: stdout

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BENCH_DIR="$REPO_ROOT/dark-factory/bench"
RESULTS_DIR="$BENCH_DIR/results"

# Defaults
SUITE_FILE="$BENCH_DIR/suite.json"
N=3
K=""
BASELINE=false
DRY_RUN=false
ISSUE_FILTER=""

# ---- Argument parsing ----
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tasks)    SUITE_FILE="$2"; shift 2 ;;
    --n)        N="$2"; shift 2 ;;
    --k)        K="$2"; shift 2 ;;
    --baseline) BASELINE=true; shift ;;
    --issues)   ISSUE_FILTER="$2"; shift 2 ;;
    --dry-run)  DRY_RUN=true; shift ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

K="${K:-$N}"

BENCH_MODE="${BENCH_MODE:-stub}"
BENCH_TOKEN_BUDGET="${BENCH_TOKEN_BUDGET:-5.00}"

mkdir -p "$RESULTS_DIR"

# Allow git to operate on volume-mounted directories (Docker host-mount ownership)
git config --global --add safe.directory "$REPO_ROOT" 2>/dev/null || true

# Ensure we run from the repo root so archon finds the git repo
cd "$REPO_ROOT"

# ---- Helpers ----
log() { echo "[bench] $*" >&2; }
die() { echo "ERROR: $*" >&2; exit 1; }

# pass^k = (c/n)^k
compute_pass_k() {
  local c="$1" n="$2" k="$3"
  python3 -c "c,n,k=$c,$n,$k; print(round((c/n)**k, 4) if n>0 else 0.0)"
}

# Run oracle tests on the current checkout; return 0=pass, 1=fail
run_oracle() {
  local oracle_cmd="$1"
  shift
  local tests=("$@")
  local rc=0

  case "$oracle_cmd" in
    pytest)
      python3 -m pytest "${tests[@]}" -x --tb=short -q --no-header \
        -p no:cacheprovider 2>/dev/null
      rc=$?
      ;;
    bash)
      for t in "${tests[@]}"; do
        bash "$REPO_ROOT/$t" 2>/dev/null || { rc=1; break; }
      done
      ;;
    jest)
      (cd "$REPO_ROOT/frontend" && npx jest --testPathPattern="$(printf '%s|' "${tests[@]}" | sed 's/|$//')" --passWithNoTests 2>/dev/null)
      rc=$?
      ;;
    *)
      log "WARNING: unknown oracle_cmd '$oracle_cmd' — treating as fail"
      rc=1
      ;;
  esac
  return $rc
}

# ---- Load suite manifest ----
[ -f "$SUITE_FILE" ] || die "Suite file not found: $SUITE_FILE"
TASKS=$(python3 -c "import json; t=json.load(open('$SUITE_FILE'))['tasks']; print(json.dumps(t))")
TASK_COUNT=$(python3 -c "import json; print(len(json.loads('$TASKS')))")
log "Loaded $TASK_COUNT tasks from $SUITE_FILE"

if [ "$DRY_RUN" = "true" ]; then
  echo "=== DRY RUN — n=$N k=$K BENCH_MODE=$BENCH_MODE ==="
  python3 -c "
import json, sys
tasks = json.loads(sys.argv[1])
for t in tasks:
    print(f\"  #{t['issue']} [{t['size']}] {t['title'][:60]}\")
    print(f\"    pre_pr_sha: {t['pre_pr_sha']}\")
    print(f\"    oracle: {t['oracle_cmd']} {t['oracle_tests']}\")
" "$TASKS"
  exit 0
fi

# ---- Token cost tracking ----
TOTAL_COST_CENTS=0
BUDGET_CENTS=$(python3 -c "print(int(float('$BENCH_TOKEN_BUDGET') * 100))")

check_budget() {
  local task_cost_cents="${1:-0}"
  TOTAL_COST_CENTS=$((TOTAL_COST_CENTS + task_cost_cents))
  local total_dollars
  total_dollars=$(python3 -c "print(f'{$TOTAL_COST_CENTS/100:.2f}')")
  if [ "$TOTAL_COST_CENTS" -ge "$BUDGET_CENTS" ]; then
    log "WARNING: token budget exceeded (\$$total_dollars >= \$$BENCH_TOKEN_BUDGET)"
  fi
}

get_last_run_cost_cents() {
  # Try archon workflow cost --last --json first; fall back to 0
  local cost_json
  cost_json=$(archon workflow cost --last --json 2>/dev/null || echo '{}')
  python3 -c "
import json, sys
try:
    d = json.loads('$cost_json')
    # cost field may be float USD or dict; try common shapes
    cost = d.get('total_cost', d.get('cost', 0))
    print(int(float(cost) * 100))
except Exception:
    print(0)
"
}

# ---- Main run loop ----
RUN_TS=$(date -u +%Y-%m-%dT%H-%M)
RESULTS_FILE="$RESULTS_DIR/${RUN_TS}-run.json"

RESULTS_TMPFILE=$(mktemp /tmp/bench_results_XXXXXX.ndjson)
export RESULTS_TMPFILE

# Iterate tasks
python3 -c "
import json, sys
tasks = json.loads(sys.argv[1])
issues = [s.strip() for s in ('$ISSUE_FILTER'.split(','))] if '$ISSUE_FILTER' else []
for t in tasks:
    if issues and str(t['issue']) not in issues:
        continue
    print(json.dumps(t))
" "$TASKS" | while IFS= read -r TASK_JSON; do
  ISSUE=$(echo "$TASK_JSON" | python3 -c "import json,sys; print(json.loads(sys.stdin.read())['issue'])")
  TITLE=$(echo "$TASK_JSON" | python3 -c "import json,sys; print(json.loads(sys.stdin.read())['title'][:60])")
  SIZE=$(echo "$TASK_JSON" | python3 -c "import json,sys; print(json.loads(sys.stdin.read())['size'])")
  PRE_SHA=$(echo "$TASK_JSON" | python3 -c "import json,sys; print(json.loads(sys.stdin.read())['pre_pr_sha'])")
  ORACLE_CMD=$(echo "$TASK_JSON" | python3 -c "import json,sys; print(json.loads(sys.stdin.read())['oracle_cmd'])")
  ORACLE_TESTS_JSON=$(echo "$TASK_JSON" | python3 -c "import json,sys; t=json.loads(sys.stdin.read()); print(json.dumps(t['oracle_tests']))")

  log "=== Task: issue #$ISSUE [$SIZE] $TITLE ==="
  log "    pre_pr_sha=$PRE_SHA"

  PASSES=0
  TASK_RUNS_JSON="[]"

  for RUN_IDX in $(seq 1 "$N"); do
    log "  Run $RUN_IDX/$N for issue #$ISSUE..."

    # Clean up any existing local branch for this issue from prior bench runs
    EXISTING_BRANCH=$(git -C "$REPO_ROOT" branch --list "feat/issue-${ISSUE}-*" | head -1 | xargs 2>/dev/null || true)
    if [ -n "$EXISTING_BRANCH" ]; then
      git -C "$REPO_ROOT" branch -D "$EXISTING_BRANCH" 2>/dev/null || true
      log "    Cleaned up prior branch: $EXISTING_BRANCH"
    fi

    # Pin to pre-PR commit so oracle tests fail before the fix
    # Use -f to discard any local modifications (e.g. the bench script itself)
    git -C "$REPO_ROOT" checkout -f "$PRE_SHA" 2>/dev/null || {
      log "    ERROR: could not checkout pre_pr_sha $PRE_SHA — skipping run"
      continue
    }

    # Invoke archon with BENCH_MODE
    RUN_START=$(date +%s)
    ARCHON_RC=0
    BENCH_MODE="$BENCH_MODE" archon workflow run archon-dark-factory "Fix issue #${ISSUE}" 2>&1 | \
      tee /tmp/bench_archon_${ISSUE}_${RUN_IDX}.log || ARCHON_RC=$?
    RUN_END=$(date +%s)
    DURATION=$(( RUN_END - RUN_START ))

    COST_CENTS=$(get_last_run_cost_cents)
    check_budget "$COST_CENTS"

    # Find and checkout the result branch
    RESULT_BRANCH=$(git -C "$REPO_ROOT" branch --list "feat/issue-${ISSUE}-*" | head -1 | xargs 2>/dev/null || true)
    PASSED=0
    if [ -n "$RESULT_BRANCH" ]; then
      git -C "$REPO_ROOT" checkout "$RESULT_BRANCH" 2>/dev/null || true
      # Run oracle tests
      ORACLE_TESTS=$(echo "$ORACLE_TESTS_JSON" | python3 -c "import json,sys; print(' '.join(json.loads(sys.stdin.read())))")
      read -ra ORACLE_ARRAY <<< "$ORACLE_TESTS"
      if run_oracle "$ORACLE_CMD" "${ORACLE_ARRAY[@]}" 2>/dev/null; then
        PASSED=1
        PASSES=$((PASSES + 1))
        log "    Run $RUN_IDX: PASS (oracle tests passed)"
      else
        log "    Run $RUN_IDX: FAIL (oracle tests failed)"
      fi
    else
      log "    Run $RUN_IDX: FAIL (no result branch found after archon run)"
    fi

    # Collect run result
    RUN_RESULT=$(python3 -c "
import json
print(json.dumps({
    'run': $RUN_IDX,
    'passed': bool($PASSED),
    'archon_exit': $ARCHON_RC,
    'duration_secs': $DURATION,
    'cost_cents': $COST_CENTS,
    'result_branch': '${RESULT_BRANCH:-}',
}))
")
    TASK_RUNS_JSON=$(python3 -c "
import json, sys
runs = json.loads('$TASK_RUNS_JSON')
runs.append(json.loads('$RUN_RESULT'))
print(json.dumps(runs))
")
  done

  # Compute pass^k
  PASS_K=$(compute_pass_k "$PASSES" "$N" "$K")

  TASK_RESULT=$(python3 -c "
import json
print(json.dumps({
    'issue': $ISSUE,
    'title': '$TITLE',
    'size': '$SIZE',
    'n': $N,
    'k': $K,
    'passes': $PASSES,
    'pass_k': $PASS_K,
    'runs': json.loads('$TASK_RUNS_JSON'),
}))
")
  echo "$TASK_RESULT" >> "$RESULTS_TMPFILE"
  log "  Task #$ISSUE: $PASSES/$N passed, pass^k=$PASS_K"

done

# ---- Aggregate results ----
# Build final JSON report
RESULTS_JSON=$(python3 -c "
import json, sys, os, datetime

tmpfile = os.environ.get('RESULTS_TMPFILE', '')
if tmpfile and os.path.exists(tmpfile):
    results = [json.loads(l) for l in open(tmpfile).readlines() if l.strip()]
else:
    results = []

# Aggregate by size bucket
by_size = {}
for r in results:
    size = r['size']
    if size not in by_size:
        by_size[size] = {'passes': 0, 'n_total': 0, 'tasks': []}
    by_size[size]['passes'] += r['passes']
    by_size[size]['n_total'] += r['n']
    by_size[size]['tasks'].append(r['issue'])

pass_k_by_size = {}
for size, agg in by_size.items():
    c = agg['passes']
    n = agg['n_total']
    k = int(os.environ.get('K', '3'))
    pass_k_by_size[size] = round((c/n)**k, 4) if n > 0 else 0.0

summary = {
    'timestamp': datetime.datetime.utcnow().isoformat() + 'Z',
    'suite_file': os.environ.get('SUITE_FILE', 'suite.json'),
    'n': int(os.environ.get('N', '3')),
    'k': int(os.environ.get('K', '3')),
    'bench_mode': os.environ.get('BENCH_MODE', 'stub'),
    'pass_k_by_size': pass_k_by_size,
    'tasks': results,
}
print(json.dumps(summary, indent=2))
" 2>/dev/null) || RESULTS_JSON="{\"error\": \"failed to aggregate results\"}"

echo "$RESULTS_JSON" > "$RESULTS_FILE"
log "Results written to $RESULTS_FILE"

# ---- Print summary table ----
python3 - "$RESULTS_FILE" <<'PYEOF'
import json, sys

data = json.load(open(sys.argv[1]))
pass_k = data.get("pass_k_by_size", {})
tasks = data.get("tasks", [])
n = data.get("n", 3)
k = data.get("k", 3)

print(f"\n=== Replay Benchmark Results ===")
print(f"n={n} runs/task  k={k}  mode={data.get('bench_mode','stub')}")
print()

print(f"{'Issue':<8} {'Size':<6} {'Pass':<6} {'pass^k':<8} Title")
print("-" * 70)
for t in tasks:
    marker = "✓" if t['passes'] == n else ("~" if t['passes'] > 0 else "✗")
    print(f"#{t['issue']:<7} {t['size']:<6} {t['passes']}/{n}   {t['pass_k']:<8.4f} {t['title'][:45]}")
print()

print(f"{'Size':<6} {'pass^k':>8}")
print("-" * 16)
for size in sorted(pass_k):
    print(f"{size:<6} {pass_k[size]:>8.4f}")
PYEOF

echo ""
echo "Results file: $RESULTS_FILE"

# ---- Baseline prose generation (--baseline only) ----
if [ "$BASELINE" = "true" ]; then
  log "=== Generating Haiku prose summaries for baseline.md ==="
  BASELINE_MD="$BENCH_DIR/baseline.md"

  # Verify ANTHROPIC_API_KEY is available
  if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    log "WARNING: ANTHROPIC_API_KEY not set — skipping Haiku prose summaries"
    log "Re-run with ANTHROPIC_API_KEY set to generate baseline prose."
  else
    # Append a timestamp header for this baseline run
    {
      echo ""
      echo "## Baseline Run — $(date -u +%Y-%m-%d)"
      echo ""
    } >> "$BASELINE_MD"

    # For each task in the results file, call Haiku inline to generate prose
    python3 - "$RESULTS_FILE" "$REPO_ROOT" "$BASELINE_MD" << 'BASELINE_PY'
import json, subprocess, sys, os
from pathlib import Path

results_file = sys.argv[1]
repo_root = sys.argv[2]
baseline_md = sys.argv[3]

data = json.load(open(results_file))
tasks = data.get("tasks", [])

suite = json.load(open(Path(repo_root) / "dark-factory/bench/suite.json"))
suite_by_issue = {t["issue"]: t for t in suite["tasks"]}

for task in tasks:
    issue = task["issue"]
    title = task["title"]
    golden_pr = suite_by_issue.get(issue, {}).get("golden_pr", "unknown")
    passes = task["passes"]
    n = task["n"]
    pass_k = task["pass_k"]

    # Get golden PR diff
    golden_diff = ""
    rc = subprocess.run(
        ["gh", "pr", "diff", str(golden_pr), "--repo", "omniscient/markethawk"],
        capture_output=True, text=True, cwd=repo_root
    )
    if rc.returncode == 0:
        golden_diff = rc.stdout[:4000]  # truncate to avoid prompt overflow

    # Get the last replay run's diff (most recent result branch)
    replay_diff = ""
    result_branches = subprocess.run(
        ["git", "branch", "--list", f"feat/issue-{issue}-*"],
        capture_output=True, text=True, cwd=repo_root
    ).stdout.strip().splitlines()
    if result_branches:
        last_branch = result_branches[-1].strip()
        rc = subprocess.run(
            ["git", "diff", f"main...{last_branch}", "--stat", "--diff-filter=AM"],
            capture_output=True, text=True, cwd=repo_root
        )
        if rc.returncode == 0:
            replay_diff = rc.stdout[:2000]

    # Build Haiku prompt
    prompt = f"""You are a code reviewer evaluating a replay benchmark run. Summarize in 3-5 sentences:
1. Whether the replay implementation appears correct and complete relative to the golden PR
2. Any notable divergences from the golden solution
3. Confidence in the oracle test result ({passes}/{n} runs passed, pass^k={pass_k})

Issue: #{issue} — {title}
Golden PR: #{golden_pr} ({passes}/{n} runs passed, pass^k={pass_k})

Golden PR changed files:
{golden_diff[:2000] if golden_diff else '(unavailable)'}

Replay diff summary:
{replay_diff if replay_diff else '(unavailable — no result branch found)'}

Write only the prose summary, no headers or bullet points."""

    print(f"[bench] Generating Haiku summary for issue #{issue}...", file=sys.stderr)
    rc = subprocess.run(
        ["claude", "-p", prompt, "--model", "claude-haiku-4-5-20251001", "--max-tokens", "500"],
        capture_output=True, text=True, cwd=repo_root,
        env={**os.environ, "ANTHROPIC_API_KEY": os.environ["ANTHROPIC_API_KEY"]}
    )
    if rc.returncode != 0:
        # Fallback: note that generation failed
        prose = f"(Haiku summary generation failed: {rc.stderr[:200]})"
        print(f"[bench] WARNING: Haiku call failed for #{issue}", file=sys.stderr)
    else:
        prose = rc.stdout.strip()

    # Append to baseline.md
    with open(baseline_md, "a") as f:
        f.write(f"### Issue #{issue} — {title}\n")
        f.write(f"**Oracle result**: {passes}/{n} runs passed (pass^k={pass_k})\n\n")
        f.write(prose + "\n\n")
    print(f"[bench] Written prose for #{issue}", file=sys.stderr)

print(f"[bench] Baseline prose written to {baseline_md}", file=sys.stderr)
BASELINE_PY

    log "Baseline prose generation complete: $BASELINE_MD"
    echo "Baseline: $BASELINE_MD"
  fi
fi
