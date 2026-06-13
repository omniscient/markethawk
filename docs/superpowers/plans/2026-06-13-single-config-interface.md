# Plan: Single Config Interface — config.yaml as Sole Source of Factory Policy

**Date:** 2026-06-13
**Issue:** #338
**Status:** Plan

---

## Goal

Consolidate all factory tunable knobs into `.claude/skills/refinement/config.yaml` as the single authoritative source. `scheduler.sh`, `entrypoint.sh`, and `code_review_payload.py` read from it at runtime. Env-var overrides remain operational but are logged when active. Deleting config.yaml breaks all consumers loudly.

## Architecture

- `yq` (mikefarah Go binary v4.44.3, pinned) is the YAML parser for all bash scripts — consistent with the existing `jq` idiom in the Dockerfile.
- Config resolution uses a two-path array: bind-mount dev path takes precedence, baked image fallback (`/opt/refinement-skills/config.yaml`) handles production. The baked copy is already present (no new `COPY` needed).
- `code_review_payload.py` receives `severity_order` as a required CLI `--severity-order` arg extracted from config.yaml by the calling shell — pure stdlib stays intact.
- `scheduler.sh` defines `resolve_config_yaml()` and `read_config()` at source time (available during `SCHEDULER_SOURCE_ONLY=1` test loads), but calls `read_config` only in the main execution path (after the `SCHEDULER_SOURCE_ONLY` guard).

## Tech Stack

Bash, Python 3.12 (stdlib only), YAML (yq), Docker, pytest

---

## File Structure

| File | Change |
|------|--------|
| `.claude/skills/refinement/config.yaml` | Add `scheduler:` block; add `severity_order` to `code_review:`; update comments |
| `dark-factory/Dockerfile` | Add yq binary install before `USER factory` |
| `dark-factory/scheduler.sh` | Add `CONFIG_YAML_PATHS`, `resolve_config_yaml()`, `read_config()`; remove 13 config-driven `${VAR:-default}` lines; call `read_config` in main exec path |
| `dark-factory/entrypoint.sh` | Add `_entrypoint_cfg_apply()` + calls post-clone for `FACTORY_WIP_LIMIT` and `CONFLICT_RESOLUTION_AI_TIER` |
| `.archon/commands/dark-factory-code-review.md` | Extract `SEVERITY_ORDER_CSV` with yq in Phase 1; pass `--severity-order` to payload script in Phase 4 |
| `dark-factory/scripts/code_review_payload.py` | Remove `SEVERITY_ORDER` constant; add `--severity-order` required arg; thread `severity_rank` dict through `build_review()` |
| `dark-factory/tests/test_code_review_payload.py` | Add `--severity-order low,medium,high,critical` to existing CLI test; add `test_missing_severity_order_exits_nonzero` |
| `dark-factory/tests/test_config_deletion.sh` | New bash test: `resolve_config_yaml` exits non-zero with absent config |

---

## Task 1: Expand config.yaml — scheduler block and severity_order

**Files:** `.claude/skills/refinement/config.yaml`

### Step 1a — Write failing test

Use `yq` (consistent with the dark-factory-ops memory pattern; avoids PyYAML transitive dependency):

```bash
yq -r '.scheduler.poll_interval // "MISSING"' .claude/skills/refinement/config.yaml
# Expected: MISSING (scheduler block not yet present)

yq -r '.code_review.severity_order // "MISSING"' .claude/skills/refinement/config.yaml
# Expected: MISSING (severity_order not yet present)
```

### Step 1b — Implement

Rewrite `.claude/skills/refinement/config.yaml` to the following. Changes: (a) add `scheduler:` block after `refine:`, (b) add `severity_order` to `code_review:`, (c) replace `# mirror of $VAR` comments with `# env: VAR`, (d) remove the `# Doc-only mirror: the scheduler reads...` multi-line comment from `dispatch_ceiling:`, (e) add `# env: REFINE_WIP_LIMIT` to `refine.wip_limit`.

```yaml
# .claude/skills/refinement/config.yaml
refine:
  wip_limit: 2              # env: REFINE_WIP_LIMIT
  skip_labels:
    - needs-discussion
    - epic
    - spec-pending-review
  min_issue_body_length: 20

scheduler:
  poll_interval: 60             # env: POLL_INTERVAL
  max_retries: 3                # env: MAX_RETRIES
  rate_limit_floor: 200         # env: RATE_LIMIT_FLOOR
  factory_wip_limit: 1          # env: FACTORY_WIP_LIMIT
  main_red_recheck_enabled: true # env: MAIN_RED_RECHECK_ENABLED
  main_red_recheck_minutes: 20  # env: MAIN_RED_RECHECK_MINUTES

plan:
  skip_labels:
    - needs-discussion
    - epic
    - plan-pending-review

direct_to_pr:
  label: direct-to-pr          # env: DIRECT_TO_PR_LABEL
  spec_grace_minutes: 30        # env: SPEC_GRACE_MINUTES
  plan_grace_minutes: 30        # env: PLAN_GRACE_MINUTES

conformance:
  enabled: true
  max_reconcile_cycles: 3
  block_on_material: true
  scope_enforcement: true
  excise_out_of_scope: true
  backlog_label: scope-spillover

code_review:
  enabled: true
  block_threshold: high         # env: BLOCK_THRESHOLD; findings at this severity or above block (critical|high|medium|low)
  fail_open: true               # reviewer error / unparseable output → advisory, never block
  max_findings: 50              # cap inline comments to avoid spam (log if exceeded)
  severity_order: [low, medium, high, critical]  # ascending; block_threshold must be one of these

preview:
  enabled: true
  model: haiku

conflict_resolution:
  enabled: true                # env: CONFLICT_RESOLUTION_ENABLED
  ai_tier: true                # env: CONFLICT_RESOLUTION_AI_TIER; false = only Tier 1 (mechanical) resolution

blast_radius:
  enabled: true
  hotspot_score_floor: 5.0      # files at or above this codeindex blast score trigger HUMAN_REQUIRED
  size_budget_lines: 400        # total added+deleted lines threshold (0 = disabled)
  size_budget_blocks: false     # true = size alone is blocking; false = advisory only

dispatch_ceiling:
  enabled: true                # env: DISPATCH_CEILING_ENABLED
  label: above-ceiling         # env: ABOVE_CEILING_LABEL
  keywords: "migration|migrate|performance|perf|architectur|refactor"  # env: ABOVE_CEILING_KEYWORDS
  # L tickets (and M tickets with a keyword title match) park in Blocked for human pairing;
  # M tickets lose the plan-pending-review grace-window auto-advance. S is unaffected.
  # See docs/superpowers/specs/2026-06-12-size-type-aware-dispatch-ceiling-design.md
  # Revisit: 2026-09-12
```

### Step 1c — Verify test passes

```bash
yq -r '.scheduler.poll_interval' .claude/skills/refinement/config.yaml
# Expected: 60

yq -r '.scheduler.factory_wip_limit' .claude/skills/refinement/config.yaml
# Expected: 1

yq -r '.code_review.severity_order | join(",")' .claude/skills/refinement/config.yaml
# Expected: low,medium,high,critical
```

### Step 1d — Commit

```bash
git add .claude/skills/refinement/config.yaml
git commit -m "config: add scheduler block and severity_order; update env-var comments (#338)"
```

---

## Task 2: Install yq in dark-factory Dockerfile

**Files:** `dark-factory/Dockerfile`

### Step 2a — Write failing check

```bash
grep -q 'mikefarah/yq' dark-factory/Dockerfile && echo "FAIL: already present" || echo "PASS: not yet installed"
```

Expected: `PASS: not yet installed`

### Step 2b — Implement

In `dark-factory/Dockerfile`, add the following block immediately before the `# Non-root factory user` comment (before the `RUN userdel -r ubuntu` line). Place it after the Docker CLI RUN block.

```dockerfile
# yq — YAML parser for dark-factory shell scripts (scheduler.sh, entrypoint.sh)
RUN curl -fsSL \
    https://github.com/mikefarah/yq/releases/download/v4.44.3/yq_linux_$(dpkg --print-architecture) \
    -o /usr/local/bin/yq && chmod +x /usr/local/bin/yq
```

### Step 2c — Verify

```bash
grep -q 'mikefarah/yq' dark-factory/Dockerfile && echo "PASS" || echo "FAIL"
grep 'v4.44.3' dark-factory/Dockerfile
```

Expected:
```
PASS
    https://github.com/mikefarah/yq/releases/download/v4.44.3/yq_linux_$(dpkg --print-architecture) \
```

### Step 2d — Commit

```bash
git add dark-factory/Dockerfile
git commit -m "docker: install yq v4.44.3 for YAML config parsing in shell scripts (#338)"
```

---

## Task 3: Add read_config() to scheduler.sh

**Files:** `dark-factory/scheduler.sh`, `dark-factory/tests/test_scheduler.sh`

### Step 3a — Write failing check (confirm functions not yet defined)

```bash
(export GH_TOKEN=stub CLAUDE_CODE_OAUTH_TOKEN=stub SCHEDULER_STATE_DIR=$(mktemp -d) \
  STATE_FILE=$(mktemp) SCHEDULER_SOURCE_ONLY=1; source dark-factory/scheduler.sh \
  && type resolve_config_yaml 2>/dev/null && echo "FAIL: already defined" || echo "PASS: not yet defined")
```

Expected: `PASS: not yet defined`

### Step 3b — Implement: remove config-driven defaults

Remove the following lines from `dark-factory/scheduler.sh` (treat each as "remove if present" — the exact wording may vary; grep for the variable name and remove any line that sets a `${VAR:-default}` for a config-driven var):

From the `# --- Configuration ---` block:

```bash
POLL_INTERVAL="${POLL_INTERVAL:-60}"
MAX_RETRIES="${MAX_RETRIES:-3}"
RATE_LIMIT_FLOOR="${RATE_LIMIT_FLOOR:-200}"
FACTORY_WIP_LIMIT="${FACTORY_WIP_LIMIT:-1}"
MAIN_RED_RECHECK_ENABLED="${MAIN_RED_RECHECK_ENABLED:-true}"
MAIN_RED_RECHECK_MINUTES="${MAIN_RED_RECHECK_MINUTES:-20}"
DISPATCH_CEILING_ENABLED="${DISPATCH_CEILING_ENABLED:-true}"
ABOVE_CEILING_LABEL="${ABOVE_CEILING_LABEL:-above-ceiling}"
ABOVE_CEILING_KEYWORDS="${ABOVE_CEILING_KEYWORDS:-migration|migrate|performance|perf|architectur|refactor}"
```

From the Refinement pipeline configuration section:

```bash
REFINE_WIP_LIMIT="${REFINE_WIP_LIMIT:-2}"
SPEC_GRACE_MINUTES="${SPEC_GRACE_MINUTES:-30}"
PLAN_GRACE_MINUTES="${PLAN_GRACE_MINUTES:-30}"
CONFLICT_RESOLUTION_ENABLED="${CONFLICT_RESOLUTION_ENABLED:-true}"
```

Lines to **keep** (env-only or hardcoded system invariants):

```bash
SKIP_LABELS="needs-discussion,epic"
SCHEDULER_STATE_DIR="${SCHEDULER_STATE_DIR:-/var/lib/dark-factory}"
STATE_FILE="${SCHEDULER_STATE_DIR}/scheduler-state.json"
DIRECT_TO_PR_LABEL="${DIRECT_TO_PR_LABEL:-direct-to-pr}"
RECHECK_STAMP_FILE="${SCHEDULER_STATE_DIR}/main-red-last-recheck"
REFINE_SKIP_LABELS="needs-discussion,epic,spec-pending-review,plan-pending-review"
REFINE_MAX_RETRIES="${REFINE_MAX_RETRIES:-3}"
```

### Step 3c — Implement: add config resolution helpers

Immediately **after** the `# --- Configuration ---` block (and its remaining kept lines), **before** the `# Board constants` section, add:

```bash
# --- Config resolution ---
# Two-path resolution: dev bind-mount takes precedence; baked image is the fallback.
# Both scheduler.sh and entrypoint.sh share this image — no new COPY needed.
CONFIG_YAML_PATHS=(
  "/workspace/project/.claude/skills/refinement/config.yaml"
  "/opt/refinement-skills/config.yaml"
)

resolve_config_yaml() {
  for p in "${CONFIG_YAML_PATHS[@]}"; do
    [ -f "$p" ] && { echo "$p"; return 0; }
  done
  echo "ERROR: config.yaml not found at any known path" >&2
  exit 1
}

read_config() {
  local cfg
  cfg=$(resolve_config_yaml)
  echo "[$(date -u +%FT%TZ)] config=loaded path=${cfg}"

  _cfg_val()  { yq -r "$1" "$cfg"; }
  _cfg_apply() {
    local varname="$1" yaml_path="$2" cfg_val
    cfg_val=$(_cfg_val "$yaml_path")
    if [ -n "${!varname+x}" ]; then
      echo "[$(date -u +%FT%TZ)] config_override=${varname} env=${!varname} default=${cfg_val}"
    else
      printf -v "$varname" '%s' "$cfg_val"
    fi
  }

  _cfg_apply POLL_INTERVAL              '.scheduler.poll_interval'
  _cfg_apply MAX_RETRIES                '.scheduler.max_retries'
  _cfg_apply RATE_LIMIT_FLOOR           '.scheduler.rate_limit_floor'
  _cfg_apply FACTORY_WIP_LIMIT          '.scheduler.factory_wip_limit'
  _cfg_apply MAIN_RED_RECHECK_ENABLED   '.scheduler.main_red_recheck_enabled'
  _cfg_apply MAIN_RED_RECHECK_MINUTES   '.scheduler.main_red_recheck_minutes'
  _cfg_apply REFINE_WIP_LIMIT           '.refine.wip_limit'
  _cfg_apply SPEC_GRACE_MINUTES         '.direct_to_pr.spec_grace_minutes'
  _cfg_apply PLAN_GRACE_MINUTES         '.direct_to_pr.plan_grace_minutes'
  _cfg_apply CONFLICT_RESOLUTION_ENABLED '.conflict_resolution.enabled'
  _cfg_apply DISPATCH_CEILING_ENABLED   '.dispatch_ceiling.enabled'
  _cfg_apply ABOVE_CEILING_LABEL        '.dispatch_ceiling.label'
  _cfg_apply ABOVE_CEILING_KEYWORDS     '.dispatch_ceiling.keywords'
}
```

### Step 3d — Implement: call read_config in main execution path

Immediately **after** the `SCHEDULER_SOURCE_ONLY` guard (the `return 0` block) and **before** the `# --- ERR trap` section, add:

```bash
read_config
```

The guard block in `scheduler.sh` currently reads:

```bash
if [ "${SCHEDULER_SOURCE_ONLY:-0}" = "1" ]; then
  return 0
fi

# --- ERR trap: log unhandled exits for post-mortem diagnosis ---
```

After the change:

```bash
if [ "${SCHEDULER_SOURCE_ONLY:-0}" = "1" ]; then
  return 0
fi

read_config

# --- ERR trap: log unhandled exits for post-mortem diagnosis ---
```

### Step 3e — Update test_scheduler.sh

In `dark-factory/tests/test_scheduler.sh`, after the `SCHEDULER_SOURCE_ONLY=1 source "$SCHED"` line and the re-stub of `set_board_status`, add explicit assignments for the config-driven vars that helper functions under test may reference:

```bash
SCHEDULER_SOURCE_ONLY=1 source "$SCHED"

# Re-stub set_board_status — scheduler.sh defines its own, overriding the export above
set_board_status() { echo "set_board_status $*" >> "$STUB_LOG"; return 0; }

# Config-driven vars — normally set by read_config(); set explicitly here since
# read_config() is not called under SCHEDULER_SOURCE_ONLY=1.
# Note: REFINE_MAX_RETRIES is NOT set here — it is a kept env-only var defined by
# the scheduler's own "${REFINE_MAX_RETRIES:-3}" default (not config-driven).
MAX_RETRIES=3
REFINE_WIP_LIMIT=2
POLL_INTERVAL=60
FACTORY_WIP_LIMIT=1
DISPATCH_CEILING_ENABLED=true
ABOVE_CEILING_LABEL=above-ceiling
ABOVE_CEILING_KEYWORDS="migration|migrate|performance|perf|architectur|refactor"
CONFLICT_RESOLUTION_ENABLED=true
SPEC_GRACE_MINUTES=30
PLAN_GRACE_MINUTES=30
```

### Step 3f — Verify

```bash
bash dark-factory/tests/test_scheduler.sh
```

Expected: all tests PASS, no failures.

Also verify functions are defined:

```bash
(export GH_TOKEN=stub CLAUDE_CODE_OAUTH_TOKEN=stub \
  SCHEDULER_STATE_DIR=$(mktemp -d) STATE_FILE=$(mktemp) SCHEDULER_SOURCE_ONLY=1; \
  source dark-factory/scheduler.sh && \
  type resolve_config_yaml >/dev/null && echo "resolve_config_yaml: PASS" && \
  type read_config >/dev/null && echo "read_config: PASS")
```

Expected:
```
resolve_config_yaml: PASS
read_config: PASS
```

### Step 3g — Commit

```bash
git add dark-factory/scheduler.sh dark-factory/tests/test_scheduler.sh
git commit -m "scheduler: add read_config(); remove 13 config-driven env defaults; call at startup (#338)"
```

---

## Task 4: Add read_config() to entrypoint.sh (post-clone)

**Files:** `dark-factory/entrypoint.sh`

### Step 4a — Write failing check

```bash
grep -q '_entrypoint_cfg_apply' dark-factory/entrypoint.sh && echo "FAIL: already present" || echo "PASS: not yet"
```

Expected: `PASS: not yet`

### Step 4b — Implement

In `dark-factory/entrypoint.sh`, after the `cd "$CLONE_DIR"` line that appears immediately after `git clone` (around line 593), and **before** the `# --- Copy preview template and seed data into clone ---` comment, add:

```bash
# --- Read config from cloned repo (post-clone) ---
# Overrides the bootstrap defaults set above (FACTORY_WIP_LIMIT, CONFLICT_RESOLUTION_AI_TIER)
# with values from the cloned config.yaml. Env vars already set act as overrides and are logged.
_entrypoint_cfg_apply() {
  local varname="$1" yaml_path="$2" cfg_val
  cfg_val=$(yq -r "$yaml_path" ".claude/skills/refinement/config.yaml")
  if [ -n "${!varname+x}" ]; then
    echo "[$(date -u +%FT%TZ)] config_override=${varname} env=${!varname} default=${cfg_val}"
  else
    printf -v "$varname" '%s' "$cfg_val"
  fi
}

_entrypoint_cfg_apply FACTORY_WIP_LIMIT          '.scheduler.factory_wip_limit'
_entrypoint_cfg_apply CONFLICT_RESOLUTION_AI_TIER '.conflict_resolution.ai_tier'

echo "[$(date -u +%FT%TZ)] config=loaded path=${CLONE_DIR}/.claude/skills/refinement/config.yaml FACTORY_WIP_LIMIT=${FACTORY_WIP_LIMIT} CONFLICT_RESOLUTION_AI_TIER=${CONFLICT_RESOLUTION_AI_TIER}"
```

The bootstrap defaults at the top of entrypoint.sh (`FACTORY_WIP_LIMIT="${FACTORY_WIP_LIMIT:-1}"` at line ~70 and `CONFLICT_RESOLUTION_AI_TIER="${CONFLICT_RESOLUTION_AI_TIER:-true}"` at line ~36) are **kept** — they guard the pre-clone concurrency check.

### Step 4c — Verify

```bash
grep -q '_entrypoint_cfg_apply FACTORY_WIP_LIMIT' dark-factory/entrypoint.sh && echo "PASS" || echo "FAIL"
grep -q '_entrypoint_cfg_apply CONFLICT_RESOLUTION_AI_TIER' dark-factory/entrypoint.sh && echo "PASS" || echo "FAIL"
```

Expected:
```
PASS
PASS
```

### Step 4d — Commit

```bash
git add dark-factory/entrypoint.sh
git commit -m "entrypoint: read FACTORY_WIP_LIMIT and CONFLICT_RESOLUTION_AI_TIER from config.yaml post-clone (#338)"
```

---

## Task 5: Update dark-factory-code-review.md — extract severity_order with yq

**Files:** `.archon/commands/dark-factory-code-review.md`

### Step 5a — Write failing check

```bash
grep -q 'SEVERITY_ORDER_CSV' .archon/commands/dark-factory-code-review.md && echo "FAIL: already present" || echo "PASS: not yet"
```

Expected: `PASS: not yet`

### Step 5b — Implement Phase 1 addition

In `.archon/commands/dark-factory-code-review.md`, in the **Phase 1: LOAD** section, after step 5 ("Extract `MAX_FINDINGS`"), insert new step 5a:

```markdown
5a. Extract `SEVERITY_ORDER_CSV` from `code_review.severity_order`:
    ```bash
    SEVERITY_ORDER_CSV=$(yq -r '.code_review.severity_order | join(",")' \
      ".claude/skills/refinement/config.yaml")
    SEVERITY_ORDER_CSV="${SEVERITY_ORDER_CSV:-low,medium,high,critical}"
    ```
```

### Step 5c — Implement Phase 4 change

In `.archon/commands/dark-factory-code-review.md`, in the **Phase 4: BUILD PAYLOAD** section, replace the existing payload script invocation:

**Before:**
```bash
python3 dark-factory/scripts/code_review_payload.py \
  --review "$ARTIFACTS_DIR/review_findings.md" \
  --diff "$ARTIFACTS_DIR/review_diff.txt" \
  --block-threshold "$BLOCK_THRESHOLD" \
  --max-findings "$MAX_FINDINGS" \
  > "$ARTIFACTS_DIR/review_result.json"
```

**After:**
```bash
python3 dark-factory/scripts/code_review_payload.py \
  --review "$ARTIFACTS_DIR/review_findings.md" \
  --diff   "$ARTIFACTS_DIR/review_diff.txt" \
  --block-threshold "$BLOCK_THRESHOLD" \
  --max-findings   "$MAX_FINDINGS" \
  --severity-order "$SEVERITY_ORDER_CSV" \
  > "$ARTIFACTS_DIR/review_result.json"
```

### Step 5d — Verify

```bash
grep -q 'SEVERITY_ORDER_CSV' .archon/commands/dark-factory-code-review.md && echo "PASS" || echo "FAIL"
grep -q '\-\-severity-order.*SEVERITY_ORDER_CSV' .archon/commands/dark-factory-code-review.md && echo "PASS" || echo "FAIL"
```

Expected:
```
PASS
PASS
```

### Step 5e — Commit

```bash
git add .archon/commands/dark-factory-code-review.md
git commit -m "code-review: extract severity_order from config.yaml; pass --severity-order to payload script (#338)"
```

---

## Task 6: Update code_review_payload.py — require --severity-order

**Files:** `dark-factory/scripts/code_review_payload.py`, `dark-factory/tests/test_code_review_payload.py`

### Step 6a — Write failing tests

In `dark-factory/tests/test_code_review_payload.py`, append the new test. The file already imports `subprocess`, `sys`, and has `SCRIPT = Path(...) / "scripts" / "code_review_payload.py"`. Add at the end of the file:

```python
def test_missing_severity_order_exits_nonzero(tmp_path):
    review = tmp_path / "r.md"
    review.write_text("- [high] cat | f.py:1 | desc")
    diff = tmp_path / "d.diff"
    diff.write_text("")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--review", str(review), "--diff", str(diff),
         "--block-threshold", "high"],  # --severity-order intentionally omitted
        capture_output=True
    )
    assert result.returncode != 0
```

Run to confirm failure (expected — `--severity-order` is not yet required):

```bash
cd dark-factory && python -m pytest tests/test_code_review_payload.py::test_missing_severity_order_exits_nonzero -v
```

Expected: FAIL (script exits 0 currently without the arg)

### Step 6b — Implement: remove SEVERITY_ORDER constant

In `dark-factory/scripts/code_review_payload.py`, **remove** the module-level constant:

```python
SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
```

### Step 6c — Implement: update build_review() signature

Replace the `build_review` function signature and all `SEVERITY_ORDER` references with `severity_rank`:

```python
def build_review(findings, changed, block_threshold="high", max_findings=50,
                 severity_rank=None, header="🏭 Dark Factory Code Review"):
    if severity_rank is None:
        severity_rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    thr = severity_rank[block_threshold.lower()]
    blockers = [f for f in findings if severity_rank[f.severity] >= thr]
    advisory = [f for f in findings if severity_rank[f.severity] < thr]

    def anchorable(f):
        return f.path is not None and f.line is not None and f.line in changed.get(f.path, set())

    anchored = sorted(
        (f for f in findings if anchorable(f)),
        key=lambda f: (-severity_rank[f.severity], f.path, f.line),
    )
    offdiff = [f for f in findings if not anchorable(f)]
    kept = anchored[:max_findings]
    dropped = anchored[max_findings:]
    offdiff_for_body = offdiff + dropped

    comments = [{"path": f.path, "line": f.line, "side": "RIGHT", "body": _comment_body(f)} for f in kept]
    event = "REQUEST_CHANGES" if blockers else "COMMENT"
    body = _review_body(header, blockers, advisory, offdiff_for_body, len(dropped))
    status = "BLOCKED" if blockers else "PASS"
    return {
        "status": status,
        "event": event,
        "payload": {"event": event, "body": body, "comments": comments},
        "blockers": [f.__dict__ for f in blockers],
        "advisory": [f.__dict__ for f in advisory],
        "inline_count": len(comments),
        "offdiff_count": len(offdiff_for_body),
    }
```

### Step 6d — Implement: update main() to add required --severity-order

Replace the `main()` function:

```python
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build a GitHub PR review payload from reviewer findings.")
    ap.add_argument("--review", required=True, help="path to the reviewer subagent's markdown output")
    ap.add_argument("--diff", required=True, help="path to the unified diff that was reviewed")
    ap.add_argument("--block-threshold", default="high")
    ap.add_argument("--max-findings", type=int, default=50)
    ap.add_argument("--severity-order", required=True,
                    help="comma-separated severity levels in ascending order (e.g. low,medium,high,critical)")
    args = ap.parse_args(argv)

    severity_rank = {sev: rank for rank, sev in enumerate(args.severity_order.split(','))}
    if args.block_threshold.lower() not in severity_rank:
        ap.error(
            f"--block-threshold '{args.block_threshold}' is not in --severity-order '{args.severity_order}'"
        )

    findings = parse_findings(_read(args.review))
    changed = changed_lines(_read(args.diff))
    result = build_review(findings, changed, args.block_threshold, args.max_findings, severity_rank)
    print(json.dumps(result))
    return 0
```

### Step 6e — Update existing CLI test in test_code_review_payload.py

The existing `test_cli_emits_json` test at line 167 calls the script without `--severity-order`. Add the flag to its `subprocess.check_output` call:

**Before:**
```python
    out = subprocess.check_output(
        [sys.executable, str(SCRIPT), "--review", str(review), "--diff", str(diff),
         "--block-threshold", "high", "--max-findings", "50"],
        text=True,
    )
```

**After:**
```python
    out = subprocess.check_output(
        [sys.executable, str(SCRIPT), "--review", str(review), "--diff", str(diff),
         "--block-threshold", "high", "--max-findings", "50",
         "--severity-order", "low,medium,high,critical"],
        text=True,
    )
```

### Step 6f — Verify all tests pass

```bash
cd dark-factory && python -m pytest tests/test_code_review_payload.py -v
```

Expected: ALL tests PASS, including `test_missing_severity_order_exits_nonzero` and the updated `test_cli_emits_json`.

### Step 6g — Commit

```bash
git add dark-factory/scripts/code_review_payload.py dark-factory/tests/test_code_review_payload.py
git commit -m "code-review-payload: require --severity-order arg; remove hardcoded SEVERITY_ORDER constant (#338)"
```

---

## Task 7: Add scheduler deletion test

**Files:** `dark-factory/tests/test_config_deletion.sh`

### Step 7a — Verify test does not yet exist

```bash
[ -f dark-factory/tests/test_config_deletion.sh ] && echo "FAIL: already exists" || echo "PASS: not yet"
```

Expected: `PASS: not yet`

### Step 7b — Implement

Create `dark-factory/tests/test_config_deletion.sh`:

```bash
#!/usr/bin/env bash
# Verify scheduler.sh fails loudly when config.yaml is absent.
set -euo pipefail
REPO_ROOT=$(git rev-parse --show-toplevel)
SCHED="${REPO_ROOT}/dark-factory/scheduler.sh"
FAKE_CONFIG="/tmp/nonexistent-config-${RANDOM}.yaml"

# Stub out external dependencies (same pattern as test_scheduler.sh)
gh()     { :; }
docker() { :; }
export -f gh docker

# Stub credentials to satisfy the validation block (runs before SCHEDULER_SOURCE_ONLY guard)
export GH_TOKEN="${GH_TOKEN:-stub-token}"
export CLAUDE_CODE_OAUTH_TOKEN="${CLAUDE_CODE_OAUTH_TOKEN:-stub-token}"

# Stub SCHEDULER_STATE_DIR so the mkdir at source time uses a temp location
export SCHEDULER_STATE_DIR
SCHEDULER_STATE_DIR=$(mktemp -d /tmp/sched-deletion-test-XXXXXX)

# Override config path to nonexistent file; source defines helpers only
CONFIG_YAML_PATHS=("$FAKE_CONFIG")
export CONFIG_YAML_PATHS

SCHEDULER_SOURCE_ONLY=1 source "$SCHED"

# resolve_config_yaml must exit non-zero when no path exists
if resolve_config_yaml 2>/dev/null; then
  echo "FAIL: resolve_config_yaml should have exited non-zero with absent config" >&2
  exit 1
fi
echo "PASS: scheduler deletion test"
```

Make executable:

```bash
chmod +x dark-factory/tests/test_config_deletion.sh
```

### Step 7c — Run the test

```bash
bash dark-factory/tests/test_config_deletion.sh
```

Expected output:
```
PASS: scheduler deletion test
```

### Step 7d — Commit

```bash
git add dark-factory/tests/test_config_deletion.sh
git commit -m "test: scheduler deletion test — resolve_config_yaml exits non-zero on missing config (#338)"
```

---

## Summary

7 tasks, 32 steps total. Execute Tasks 1–2 first (config.yaml and Dockerfile are prerequisites for everything else), then Tasks 3–4 (scheduler and entrypoint), then Task 6 (payload script) **before** Task 5 (code-review command) — if Task 5 ships without Task 6, the live code-review invocation will break because `--severity-order` is a required arg. Task 7 (deletion test) can be done any time after Task 3.

| Task | Key deliverable | Commit message tag |
|------|----------------|--------------------|
| 1 | `scheduler:` block + `severity_order` in config.yaml | `config:` |
| 2 | yq binary in Dockerfile | `docker:` |
| 3 | `read_config()` in scheduler.sh; 13 defaults removed | `scheduler:` |
| 4 | `_entrypoint_cfg_apply()` post-clone in entrypoint.sh | `entrypoint:` |
| 5 | `SEVERITY_ORDER_CSV` extraction + `--severity-order` flag in code-review command | `code-review:` |
| 6 | `--severity-order` required arg in payload script | `code-review-payload:` |
| 7 | Deletion test for scheduler config | `test:` |
