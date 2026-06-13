# Single Config Interface: config.yaml as Sole Source of Factory Policy

**Date:** 2026-06-13
**Issue:** #338
**Status:** Spec

---

## Problem

The factory's configuration surface is scattered across three independent locations with no override hierarchy:

- `.claude/skills/refinement/config.yaml` — read by archon commands (refine, plan, conformance, code-review), but **not** by the scheduler or entrypoint
- `dark-factory/scheduler.sh` — 15+ env-var defaults (`POLL_INTERVAL`, `MAX_RETRIES`, `REFINE_WIP_LIMIT`, `SPEC_GRACE_MINUTES`, etc.) defined independently, even though several have doc-only mirror comments in config.yaml
- `dark-factory/entrypoint.sh` — `FACTORY_WIP_LIMIT`, `CONFLICT_RESOLUTION_AI_TIER` defaulted independently
- `dark-factory/scripts/code_review_payload.py` — `SEVERITY_ORDER` dict hardcoded at module level, can diverge from `code_review.block_threshold`'s valid values in config.yaml

Editing any one source silently diverges from the others. There is no single answer to "what is the factory's current policy?"

---

## Requirements

1. Every tunable knob has a single canonical default in `config.yaml`, with a comment showing the env-var override name.
2. `scheduler.sh` reads config.yaml at startup; env overrides are logged when active.
3. `entrypoint.sh` reads config.yaml post-clone; env overrides are logged when active.
4. `SEVERITY_ORDER` is sourced from config, not hardcoded in `code_review_payload.py`.
5. A deletion test exists that verifies removing config.yaml breaks all consumers loudly.

---

## Architecture / Approach

### 1. `config.yaml` — new knobs and `severity_order`

Add a `scheduler:` block for knobs not already present, and add `severity_order` to the `code_review:` block. Remove the `# Doc-only mirror` comments from existing mirrored keys — they become authoritative.

```yaml
scheduler:
  poll_interval: 60             # env: POLL_INTERVAL
  max_retries: 3                # env: MAX_RETRIES (implement circuit-breaker)
  rate_limit_floor: 200         # env: RATE_LIMIT_FLOOR
  factory_wip_limit: 1          # env: FACTORY_WIP_LIMIT
  main_red_recheck_enabled: true # env: MAIN_RED_RECHECK_ENABLED
  main_red_recheck_minutes: 20  # env: MAIN_RED_RECHECK_MINUTES

code_review:
  enabled: true
  block_threshold: high
  fail_open: true
  max_findings: 50
  severity_order: [low, medium, high, critical]  # ascending; block_threshold must be one of these
```

Existing keys that become authoritative (remove `# Doc-only mirror` comment):
- `refine.wip_limit` → `REFINE_WIP_LIMIT`
- `direct_to_pr.spec_grace_minutes` → `SPEC_GRACE_MINUTES`
- `direct_to_pr.plan_grace_minutes` → `PLAN_GRACE_MINUTES`
- `conflict_resolution.enabled` → `CONFLICT_RESOLUTION_ENABLED`
- `conflict_resolution.ai_tier` → `CONFLICT_RESOLUTION_AI_TIER`
- `dispatch_ceiling.enabled` → `DISPATCH_CEILING_ENABLED`
- `dispatch_ceiling.label` → `ABOVE_CEILING_LABEL`
- `dispatch_ceiling.keywords` → `ABOVE_CEILING_KEYWORDS`

### 2. `dark-factory/Dockerfile` — install `yq`

Add the `mikefarah/yq` Go binary **before** the `USER factory` switch (same placement pattern as `jq` and `gh`):

```dockerfile
RUN curl -fsSL \
    https://github.com/mikefarah/yq/releases/download/v4.44.3/yq_linux_$(dpkg --print-architecture) \
    -o /usr/local/bin/yq && chmod +x /usr/local/bin/yq
```

Pin the version for reproducibility. Both `entrypoint.sh` and `scheduler.sh` share this single image.

### 3. `dark-factory/scheduler.sh` — read config at startup

Add a `read_config()` helper immediately after the configuration block. It resolves the config file path (bind-mounted dev path → baked image fallback) and reads each knob, yielding to env-var overrides and logging when active:

```bash
CONFIG_YAML_PATHS=(
  "/workspace/project/.claude/skills/refinement/config.yaml"  # local dev bind-mount
  "/opt/refinement-skills/config.yaml"                        # baked image fallback
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

  _cfg_apply POLL_INTERVAL           '.scheduler.poll_interval'
  _cfg_apply MAX_RETRIES             '.scheduler.max_retries'
  _cfg_apply RATE_LIMIT_FLOOR        '.scheduler.rate_limit_floor'
  _cfg_apply FACTORY_WIP_LIMIT       '.scheduler.factory_wip_limit'
  _cfg_apply MAIN_RED_RECHECK_ENABLED '.scheduler.main_red_recheck_enabled'
  _cfg_apply MAIN_RED_RECHECK_MINUTES '.scheduler.main_red_recheck_minutes'
  _cfg_apply REFINE_WIP_LIMIT        '.refine.wip_limit'
  _cfg_apply SPEC_GRACE_MINUTES      '.direct_to_pr.spec_grace_minutes'
  _cfg_apply PLAN_GRACE_MINUTES      '.direct_to_pr.plan_grace_minutes'
  _cfg_apply CONFLICT_RESOLUTION_ENABLED '.conflict_resolution.enabled'
  _cfg_apply DISPATCH_CEILING_ENABLED    '.dispatch_ceiling.enabled'
  _cfg_apply ABOVE_CEILING_LABEL         '.dispatch_ceiling.label'
  _cfg_apply ABOVE_CEILING_KEYWORDS      '.dispatch_ceiling.keywords'
}

read_config
```

The existing env-var default lines (`POLL_INTERVAL="${POLL_INTERVAL:-60}"`) are **removed** — config.yaml becomes the canonical default source. Env vars set before `read_config` is called act as overrides and are logged.

Path resolution: the baked image copy at `/opt/refinement-skills/config.yaml` is the production fallback (already present; no new `COPY` needed). The bind-mount path at `/workspace/project/...` takes precedence when present (local dev). This matches the existing `.archon/.env` provisioning pattern at line 68.

### 4. `dark-factory/entrypoint.sh` — read config post-clone

After `cd "$CLONE_DIR"` (post-clone), call a similar `read_config` block that reads from the cloned path. Variables read here: `FACTORY_WIP_LIMIT`, `CONFLICT_RESOLUTION_AI_TIER`. The concurrency guard at the top of entrypoint.sh still uses `FACTORY_WIP_LIMIT="${FACTORY_WIP_LIMIT:-1}"` as a bootstrap default (it runs before the clone), but the post-clone `read_config` corrects it from config.yaml for any subsequent use.

### 5. `dark-factory-code-review.md` — extract `severity_order` with yq

In Phase 1 after reading other config keys:

```bash
SEVERITY_ORDER_CSV=$(yq -r '.code_review.severity_order | join(",")' \
  ".claude/skills/refinement/config.yaml")
```

Pass it to Phase 4 invocation:

```bash
python3 dark-factory/scripts/code_review_payload.py \
  --review "$ARTIFACTS_DIR/review_findings.md" \
  --diff   "$ARTIFACTS_DIR/review_diff.txt" \
  --block-threshold "$BLOCK_THRESHOLD" \
  --max-findings   "$MAX_FINDINGS" \
  --severity-order "$SEVERITY_ORDER_CSV" \
  > "$ARTIFACTS_DIR/review_result.json"
```

### 6. `dark-factory/scripts/code_review_payload.py` — `--severity-order` required arg

- Remove the module-level `SEVERITY_ORDER` constant.
- Add `--severity-order` as a **required** argument (no default — absence is a hard `argparse` error, satisfying the loud-failure requirement).
- Parse it to a rank dict: `{sev: rank for rank, sev in enumerate(args.severity_order.split(','))}`.
- Thread the rank dict through `main()` → `build_review()` as a parameter (replaces the global).
- Change `--block-threshold choices` from `choices=list(SEVERITY_ORDER)` to `choices=None` with explicit post-parse validation against the parsed severity-order dict.
- Update `test_code_review_payload.py`:
  - Add `--severity-order low,medium,high,critical` to all CLI test invocations.
  - Add a test asserting the script exits non-zero when `--severity-order` is omitted.

### 7. Deletion test

Two complementary pieces:

**`dark-factory/tests/test_code_review_payload.py`** — add:

```python
def test_missing_severity_order_exits_nonzero(tmp_path):
    review = tmp_path / "r.md"; review.write_text("- [high] cat | f.py:1 | desc")
    diff   = tmp_path / "d.diff"; diff.write_text("")
    result = subprocess.run(
        [sys.executable, str(PAYLOAD_SCRIPT), "--review", str(review), "--diff", str(diff),
         "--block-threshold", "high"],  # --severity-order intentionally omitted
        capture_output=True
    )
    assert result.returncode != 0
```

**`dark-factory/tests/test_config_deletion.sh`** — new bash test following the `test_scheduler.sh` harness pattern (`SCHEDULER_SOURCE_ONLY=1 source`):

```bash
#!/usr/bin/env bash
# Verify scheduler.sh fails loudly when config.yaml is absent.
set -euo pipefail
REPO_ROOT=$(git rev-parse --show-toplevel)
SCHED="${REPO_ROOT}/dark-factory/scheduler.sh"
FAKE_CONFIG="/tmp/nonexistent-config-${RANDOM}.yaml"

# Stub out external dependencies (same pattern as test_scheduler.sh)
gh()   { :; }; docker() { :; }; export -f gh docker

# Override config path to nonexistent file, source helper functions only
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

---

## Alternatives Considered

### A. PyYAML in `code_review_payload.py`

Rejected: PyYAML is not an explicit dark-factory dependency (no `requirements.txt`), making it fragile across dependency bumps. Adding it would require a new Dockerfile pip install — at which point yq (option B) is cleaner and consistent with the existing jq idiom.

### B. `grep`/`sed` YAML parsing in bash

Rejected: config.yaml has nested keys (e.g. `code_review.block_threshold`, the severity list) that require a real parser. Silent grep misses also violate the "break loudly on deletion" criterion.

### C. Keep `SEVERITY_ORDER` hardcoded, doc-only `severity_order` in config.yaml

Rejected by acceptance criterion: "sourced from config, not hardcoded." The Python script keeping its own authoritative dict means deleting config.yaml doesn't break it — directly violating the single-source requirement.

---

## Open Questions

- **`REFINE_MAX_RETRIES`** — currently set to 3 in `scheduler.sh` alongside `MAX_RETRIES`. Should they unify to one `max_retries` key or remain separate? Current proposal keeps them separate under `scheduler.max_retries` (implement retries) and a new `scheduler.refine_max_retries` if needed. Non-blocking — can be treated as unified for now.
- **`SKIP_LABELS` and `REFINE_SKIP_LABELS`** — these are hard-coded system invariants whose values must match GitHub label names. They are left out of config.yaml in this spec. If they should be configurable, that is a follow-on.

---

## Assumptions

- `/opt/refinement-skills/config.yaml` exists in the baked dark-factory image (the image already COPYs `.claude/skills/refinement/` to `/opt/refinement-skills/` — confirmed by `dark-factory-ops.md` memory). No new COPY line is needed for the scheduler's production fallback.
- `yq v4.44.3` syntax (`yq -r '.key'`) is used throughout; the script should fail visibly if a different version is installed (the version is pinned in the Dockerfile).
- The deletion test runs in the local dev environment (bind-mount present). Production-without-bind-mount uses the baked fallback and is a separate operational concern.
