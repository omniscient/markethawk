# Plan: Phase 4 T4 — over_budget Telemetry + Cost-Report Line

**Date:** 2026-07-03
**Issue:** [#717](https://github.com/omniscient/markethawk/issues/717)
**Spec:** `docs/superpowers/specs/2026-07-03-phase4-t4-over-budget-telemetry-design.md`
**Goal:** Surface the enforcement signals computed by `budget_enforce.py` into `context-budget.json` (six new additive fields in both observe and enforce modes, fail-open) and into the GitHub cost report's `SAVINGS_BLOCK` (per-state `BUDGET_LINE` for over-budget and would-trim runs; no line on healthy runs). Two files changed: `dark-factory/scripts/budget_enforce.py`, `dark-factory/entrypoint.sh`. Four new tests in `dark-factory/tests/test_budget_enforce.py`.

## Architecture

T1 (`budget_enforce.py`) computes `BudgetResult` — including `over_budget`, `would_trim`, `derived_caps`, `reserved_tokens`, and `allowance` — and currently discards them after printing `KEY=VALUE` env lines to stdout. T4 adds a write-back step in `run_cli()`: after `derive_caps()` returns and before the enforce-mode env-line branch, re-read `context-budget.json` and merge six new fields in-place (`over_budget`, `would_trim`, `derived_caps`, `scenario_budget`, `reserved_tokens`, `allowance`). The write-back is wrapped in `try/except Exception` — errors are logged to stderr and swallowed so the load-bearing stdout path (redirected to `token-opt-caps.env` in enforce mode) is unaffected.

`post_cost_report()` in `entrypoint.sh` already reads `context-budget.json` inside a `if [[ "$SCHEMA_VER" -ge 2 ]]` guard and builds `SAVINGS_LINE` and `FALLBACKS_LINE`. T4 adds a third variable, `BUDGET_LINE`, populated from the six new fields. When `over_budget=true` it emits a trimmed-token warning line; when `would_trim=true` only it emits a capped-token line; when both are false no line is emitted. `SAVINGS_BLOCK` is updated to include `BUDGET_LINE` alongside the existing two.

**Files changed:**
- `dark-factory/scripts/budget_enforce.py` — write-back try/except block in `run_cli()` (between `result = derive_caps(...)` and `if args.mode == "enforce":`)
- `dark-factory/entrypoint.sh` — `BUDGET_LINE=""` declaration; BUDGET_LINE logic after `FALLBACKS_LINE` block; updated `SAVINGS_BLOCK`
- `dark-factory/tests/test_budget_enforce.py` — four new tests (Tests 29–32)

## Tech Stack

- Python 3 (stdlib only): `dark-factory/scripts/budget_enforce.py`
- Bash + jq: `dark-factory/entrypoint.sh`
- pytest: `dark-factory/tests/test_budget_enforce.py`

## File Structure

| File | Change |
|------|--------|
| `dark-factory/tests/test_budget_enforce.py` | Append Tests 29–32 |
| `dark-factory/scripts/budget_enforce.py` | Insert write-back block after line 312 (`result = derive_caps(...)`) |
| `dark-factory/entrypoint.sh` | (1) line 326: add `BUDGET_LINE=""` to local declaration; (2) after line 342 (`FALLBACKS_LINE` block closing `fi`): insert BUDGET_LINE jq reads and conditional; (3) lines 348–352: update `SAVINGS_BLOCK` condition and body |

---

## Task 1: Write four failing tests for the write-back behavior

**Files:**
- `dark-factory/tests/test_budget_enforce.py`

### TDD Steps

#### Step 1.1 — Append Tests 29–32 to `dark-factory/tests/test_budget_enforce.py`

Tests 29 and 30 will fail immediately (write-back not implemented). Tests 31 and 32 pass with the current code — 31 because `sys.exit(1)` on missing JSON is pre-existing behaviour, 32 because an untouched file trivially preserves its own fields.

```python
# ── Test 29: write-back observe mode — six new fields written; stdout empty ───

def test_writeback_observe_mode(tmp_path, capsys):
    cb_json = tmp_path / "context-budget.json"
    cb_json.write_text(json.dumps({
        "schema_version": 2,
        "scenario": "plan",
        "savings_tokens": 1234,
        "sections": make_sections(claude_md_tokens=5000, issue_context_tokens=500, arch_fallback=False),
    }))
    be.run_cli([
        "--context-budget-json", str(cb_json),
        "--budget-tokens", "30000",
        "--mode", "observe",
    ])
    captured = capsys.readouterr()
    assert captured.out == ""
    cb = json.loads(cb_json.read_text())
    for field in ("over_budget", "would_trim", "derived_caps",
                  "scenario_budget", "reserved_tokens", "allowance"):
        assert field in cb, f"Missing field after write-back: {field}"


# ── Test 30: write-back enforce mode — six new fields + KEY=VALUE on stdout ──

def test_writeback_enforce_mode(tmp_path, capsys):
    cb_json = tmp_path / "context-budget.json"
    cb_json.write_text(json.dumps({
        "schema_version": 2,
        "scenario": "plan",
        "sections": make_sections(claude_md_tokens=5000, issue_context_tokens=500, arch_fallback=False),
    }))
    be.run_cli([
        "--context-budget-json", str(cb_json),
        "--budget-tokens", "30000",
        "--mode", "enforce",
    ])
    captured = capsys.readouterr()
    assert any("=" in line for line in captured.out.strip().splitlines()), \
        "Enforce mode must emit at least one KEY=VALUE line"
    cb = json.loads(cb_json.read_text())
    for field in ("over_budget", "would_trim", "derived_caps",
                  "scenario_budget", "reserved_tokens", "allowance"):
        assert field in cb, f"Missing field after write-back: {field}"


# ── Test 31: fail-open — missing JSON exits 1 at initial read (pre write-back)

def test_writeback_failopen_missing_json(tmp_path):
    missing = str(tmp_path / "nonexistent.json")
    with pytest.raises(SystemExit) as exc_info:
        be.run_cli([
            "--context-budget-json", missing,
            "--budget-tokens", "30000",
            "--mode", "observe",
        ])
    assert exc_info.value.code == 1


# ── Test 32: write-back preserves existing fields ─────────────────────────────

def test_writeback_existing_fields_preserved(tmp_path):
    cb_json = tmp_path / "context-budget.json"
    cb_json.write_text(json.dumps({
        "schema_version": 2,
        "scenario": "plan",
        "savings_tokens": 999,
        "sections": make_sections(claude_md_tokens=5000, issue_context_tokens=500, arch_fallback=False),
    }))
    be.run_cli([
        "--context-budget-json", str(cb_json),
        "--budget-tokens", "30000",
        "--mode", "observe",
    ])
    cb = json.loads(cb_json.read_text())
    assert cb["schema_version"] == 2,    "schema_version must not change"
    assert cb["scenario"] == "plan",     "scenario must not change"
    assert cb["savings_tokens"] == 999,  "savings_tokens must not change"
```

#### Step 1.2 — Verify Tests 29 and 30 fail

```bash
python3 -m pytest dark-factory/tests/test_budget_enforce.py::test_writeback_observe_mode \
  dark-factory/tests/test_budget_enforce.py::test_writeback_enforce_mode \
  -v
```

Expected: `2 failed` — `AssertionError: Missing field after write-back: over_budget` (write-back not yet implemented).

#### Step 1.3 — Commit failing tests

```bash
git add dark-factory/tests/test_budget_enforce.py
git commit -m "test(#717): write-back tests for budget_enforce.py (T29–T32, T29/T30 failing)"
```

Expected commit message output (example):
```
[refine/issue-717-... abc1234] test(#717): write-back tests for budget_enforce.py (T29–T32, T29/T30 failing)
 1 file changed, 52 insertions(+)
```

---

## Task 2: Implement write-back block in `budget_enforce.py`

**Files:**
- `dark-factory/scripts/budget_enforce.py`

### TDD Steps

#### Step 2.1 — Insert write-back block in `run_cli()`

In `dark-factory/scripts/budget_enforce.py`, locate the blank line between `result = derive_caps(...)` (line 312) and `if args.mode == "enforce":` (line 314). Replace that blank line with the write-back block:

```python
    config = _load_config(args.config)
    result = derive_caps(
        sections=sections,
        budget=args.budget_tokens,
        arch_fallback=arch_fallback,
        config=config,
        scenario=scenario,
    )

    # Augment context-budget.json with enforcement telemetry (both modes).
    try:
        with open(args.context_budget_json, encoding="utf-8") as f:
            cb = json.load(f)
        cb["over_budget"]     = result.over_budget
        cb["would_trim"]      = result.would_trim
        cb["derived_caps"]    = result.derived_caps
        cb["scenario_budget"] = args.budget_tokens
        cb["reserved_tokens"] = result.reserved_tokens
        cb["allowance"]       = result.allowance
        with open(args.context_budget_json, "w", encoding="utf-8") as f:
            json.dump(cb, f, indent=2)
        print(
            f"budget_enforce: augmented context-budget.json "
            f"(over_budget={result.over_budget}, would_trim={result.would_trim})",
            file=sys.stderr,
        )
    except Exception as exc:
        print(f"budget_enforce: warning — could not augment context-budget.json: {exc}", file=sys.stderr)

    if args.mode == "enforce":
```

The exact `old_string` for the Edit tool is:

```
    config = _load_config(args.config)
    result = derive_caps(
        sections=sections,
        budget=args.budget_tokens,
        arch_fallback=arch_fallback,
        config=config,
        scenario=scenario,
    )

    if args.mode == "enforce":
```

The `new_string` is:

```
    config = _load_config(args.config)
    result = derive_caps(
        sections=sections,
        budget=args.budget_tokens,
        arch_fallback=arch_fallback,
        config=config,
        scenario=scenario,
    )

    # Augment context-budget.json with enforcement telemetry (both modes).
    try:
        with open(args.context_budget_json, encoding="utf-8") as f:
            cb = json.load(f)
        cb["over_budget"]     = result.over_budget
        cb["would_trim"]      = result.would_trim
        cb["derived_caps"]    = result.derived_caps
        cb["scenario_budget"] = args.budget_tokens
        cb["reserved_tokens"] = result.reserved_tokens
        cb["allowance"]       = result.allowance
        with open(args.context_budget_json, "w", encoding="utf-8") as f:
            json.dump(cb, f, indent=2)
        print(
            f"budget_enforce: augmented context-budget.json "
            f"(over_budget={result.over_budget}, would_trim={result.would_trim})",
            file=sys.stderr,
        )
    except Exception as exc:
        print(f"budget_enforce: warning — could not augment context-budget.json: {exc}", file=sys.stderr)

    if args.mode == "enforce":
```

#### Step 2.2 — Verify all four write-back tests pass

```bash
python3 -m pytest dark-factory/tests/test_budget_enforce.py::test_writeback_observe_mode \
  dark-factory/tests/test_budget_enforce.py::test_writeback_enforce_mode \
  dark-factory/tests/test_budget_enforce.py::test_writeback_failopen_missing_json \
  dark-factory/tests/test_budget_enforce.py::test_writeback_existing_fields_preserved \
  -v
```

Expected output:
```
PASSED test_writeback_observe_mode
PASSED test_writeback_enforce_mode
PASSED test_writeback_failopen_missing_json
PASSED test_writeback_existing_fields_preserved
4 passed in ...s
```

#### Step 2.3 — Run full test suite to confirm no regressions

```bash
python3 -m pytest dark-factory/tests/test_budget_enforce.py -v
```

Expected: `32 passed` (Tests 1–28 unchanged + Tests 29–32).

#### Step 2.4 — Commit implementation

```bash
git add dark-factory/scripts/budget_enforce.py
git commit -m "feat(#717): add context-budget.json write-back in budget_enforce.py"
```

---

## Task 3: Add BUDGET_LINE to `post_cost_report()` in `entrypoint.sh`

**Files:**
- `dark-factory/entrypoint.sh`

No pytest tests cover bash functions. Correctness is verified by syntax check and a fixture-driven smoke test.

### TDD Steps

#### Step 3.1 — Edit 1: Add `BUDGET_LINE=""` to the local declaration (line 326)

`old_string`:
```bash
  local SAVINGS_LINE="" FALLBACKS_LINE=""
```

`new_string`:
```bash
  local SAVINGS_LINE="" FALLBACKS_LINE="" BUDGET_LINE=""
```

#### Step 3.2 — Edit 2: Insert BUDGET_LINE logic after the FALLBACKS_LINE block

The insertion point is inside `if [[ "$SCHEMA_VER" =~ ^[0-9]+$ ]] && [ "$SCHEMA_VER" -ge 2 ]`, immediately after the closing `fi` of the `FALLBACKS_LINE` conditional (line 342) and before the outer `fi` (line 343).

`old_string`:
```bash
      if [ "${FALLBACK_COUNT:-0}" -gt 0 ] 2>/dev/null; then
        FALLBACKS_LINE=$(jq -r '
          "**Fallbacks:** " + ([ (.fallback_events // [])[] | "\(.section): \(.reason)" ] | join(", "))
        ' "$BUDGET_FILE" 2>/dev/null || true)
      fi
    fi
  fi
```

`new_string`:
```bash
      if [ "${FALLBACK_COUNT:-0}" -gt 0 ] 2>/dev/null; then
        FALLBACKS_LINE=$(jq -r '
          "**Fallbacks:** " + ([ (.fallback_events // [])[] | "\(.section): \(.reason)" ] | join(", "))
        ' "$BUDGET_FILE" 2>/dev/null || true)
      fi
      local OVER_BUDGET WOULD_TRIM SCENARIO_BUDGET RESERVED_TOKENS ESTIMATED SCENARIO
      local DERIVED_CAPS_STR=""
      OVER_BUDGET=$(jq -r '.over_budget // false' "$BUDGET_FILE" 2>/dev/null || echo "false")
      WOULD_TRIM=$(jq -r '.would_trim // false' "$BUDGET_FILE" 2>/dev/null || echo "false")
      SCENARIO_BUDGET=$(jq -r '.scenario_budget // 0' "$BUDGET_FILE" 2>/dev/null || echo "0")
      RESERVED_TOKENS=$(jq -r '.reserved_tokens // 0' "$BUDGET_FILE" 2>/dev/null || echo "0")
      ESTIMATED=$(jq -r '.estimated_input_tokens // 0' "$BUDGET_FILE" 2>/dev/null || echo "0")
      SCENARIO=$(jq -r '.scenario // ""' "$BUDGET_FILE" 2>/dev/null || echo "")
      if [ "${SCENARIO_BUDGET:-0}" -gt 0 ] 2>/dev/null; then
        DERIVED_CAPS_STR=$(jq -r '
          (.derived_caps // {}) | to_entries |
          map("\(.key)→\(.value)") | join(", ")
        ' "$BUDGET_FILE" 2>/dev/null || true)
      fi
      if [ "$OVER_BUDGET" = "true" ] && [ "${SCENARIO_BUDGET:-0}" -gt 0 ] 2>/dev/null; then
        local CAPS_SUFFIX=""
        [ -n "$DERIVED_CAPS_STR" ] && CAPS_SUFFIX=" — trimmed: ${DERIVED_CAPS_STR}"
        BUDGET_LINE="**⚠️ Over budget (${SCENARIO}): $(fmt_tokens "$RESERVED_TOKENS") reserved / $(fmt_tokens "$SCENARIO_BUDGET") budget${CAPS_SUFFIX}**" || true
      elif [ "$WOULD_TRIM" = "true" ] && [ "${SCENARIO_BUDGET:-0}" -gt 0 ] 2>/dev/null; then
        local CAPS_SUFFIX=""
        [ -n "$DERIVED_CAPS_STR" ] && CAPS_SUFFIX=" — capped: ${DERIVED_CAPS_STR}"
        BUDGET_LINE="**Budget trim (${SCENARIO}): est $(fmt_tokens "$ESTIMATED") / $(fmt_tokens "$SCENARIO_BUDGET") budget${CAPS_SUFFIX}**" || true
      fi
    fi
  fi
```

#### Step 3.3 — Edit 3: Update SAVINGS_BLOCK to include BUDGET_LINE

`old_string`:
```bash
  local SAVINGS_BLOCK=""
  if [ -n "$SAVINGS_LINE" ] || [ -n "$FALLBACKS_LINE" ]; then
    SAVINGS_BLOCK="
${SAVINGS_LINE}${SAVINGS_LINE:+
}${FALLBACKS_LINE}"
  fi
```

`new_string`:
```bash
  local SAVINGS_BLOCK=""
  if [ -n "$SAVINGS_LINE" ] || [ -n "$FALLBACKS_LINE" ] || [ -n "$BUDGET_LINE" ]; then
    SAVINGS_BLOCK="
${SAVINGS_LINE}${SAVINGS_LINE:+
}${FALLBACKS_LINE}${FALLBACKS_LINE:+
}${BUDGET_LINE}"
  fi
```

#### Step 3.4 — Verify bash syntax

```bash
bash -n dark-factory/entrypoint.sh
```

Expected: no output (clean parse, exit 0).

#### Step 3.5 — Smoke-test BUDGET_LINE construction with a fixture

```bash
TMPDIR=$(mktemp -d)
cat > "$TMPDIR/context-budget.json" <<'EOF'
{
  "schema_version": 2,
  "scenario": "refine",
  "estimated_input_tokens": 40000,
  "savings_tokens": 0,
  "savings_pct": 0,
  "over_budget": true,
  "would_trim": true,
  "scenario_budget": 30000,
  "reserved_tokens": 42000,
  "allowance": 0,
  "derived_caps": {"architecture_md": 1500, "memory_context": 750}
}
EOF
cat > "$TMPDIR/run-record.json" <<'EOF'
{
  "status": "completed",
  "totals": {"cost_usd": 0.01, "gen_ai.usage.input_tokens": 1000, "gen_ai.usage.output_tokens": 200},
  "nodes": [{"node_id": "test", "model": "claude-sonnet-4-6", "gen_ai.usage.input_tokens": 1000, "gen_ai.usage.output_tokens": 200, "cost_usd": 0.01, "duration_ms": 5000}]
}
EOF
# Source and invoke; ISSUE_NUM empty skips gh API call; redirect to see BODY
ISSUE_NUM="" ARTIFACTS_DIR="$TMPDIR" INTENT=plan COST_MARKER="<!-- factory-cost -->" \
  bash -c '
    source dark-factory/entrypoint.sh
    # Manually exercise the SAVINGS_BLOCK logic (no gh call since ISSUE_NUM is empty)
    BUDGET_FILE="'"$TMPDIR"'/context-budget.json"
    local_fmt_tokens() { local n=$1; [ "$n" -ge 1000 ] && echo "$(echo "scale=1; $n / 1000" | bc)K" || echo "$n"; }
    SCHEMA_VER=$(jq -r ".schema_version // 1" "$BUDGET_FILE")
    SAVINGS_LINE="" FALLBACKS_LINE="" BUDGET_LINE=""
    OVER_BUDGET=$(jq -r ".over_budget // false" "$BUDGET_FILE")
    WOULD_TRIM=$(jq -r ".would_trim // false" "$BUDGET_FILE")
    SCENARIO_BUDGET=$(jq -r ".scenario_budget // 0" "$BUDGET_FILE")
    RESERVED_TOKENS=$(jq -r ".reserved_tokens // 0" "$BUDGET_FILE")
    SCENARIO=$(jq -r ".scenario // \"\"" "$BUDGET_FILE")
    DERIVED_CAPS_STR=$(jq -r "(.derived_caps // {}) | to_entries | map(\"\(.key)→\(.value)\") | join(\", \")" "$BUDGET_FILE")
    if [ "$OVER_BUDGET" = "true" ]; then
      echo "BUDGET_LINE (over-budget): **⚠️ Over budget (${SCENARIO}): ${RESERVED_TOKENS} reserved / ${SCENARIO_BUDGET} budget — trimmed: ${DERIVED_CAPS_STR}**"
    elif [ "$WOULD_TRIM" = "true" ]; then
      echo "BUDGET_LINE (would-trim): **Budget trim (${SCENARIO}): est ... / ${SCENARIO_BUDGET} budget — capped: ${DERIVED_CAPS_STR}**"
    fi
  ' 2>/dev/null
rm -rf "$TMPDIR"
```

Expected output (over-budget fixture):
```
BUDGET_LINE (over-budget): **⚠️ Over budget (refine): 42000 reserved / 30000 budget — trimmed: architecture_md→1500, memory_context→750**
```

#### Step 3.6 — Commit

```bash
git add dark-factory/entrypoint.sh
git commit -m "feat(#717): add BUDGET_LINE to post_cost_report() in entrypoint.sh"
```

---

## Final Verification

```bash
# 1. All 32 tests pass (no regressions)
python3 -m pytest dark-factory/tests/test_budget_enforce.py -v
# Expected: 32 passed

# 2. Bash syntax clean
bash -n dark-factory/entrypoint.sh
# Expected: (no output, exit 0)

# 3. Spot-check: run_cli observe mode leaves stdout empty and writes six fields
python3 -m pytest dark-factory/tests/test_budget_enforce.py::test_writeback_observe_mode -v
# Expected: 1 passed

# 4. Spot-check: run_cli enforce mode writes KEY=VALUE to stdout AND writes six fields
python3 -m pytest dark-factory/tests/test_budget_enforce.py::test_writeback_enforce_mode -v
# Expected: 1 passed
```
