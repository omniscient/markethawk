# Dark Factory Token Optimization — Rollout Guardrails

**Date:** 2026-07-02  
**Issue:** #673  
**Spec:** [docs/superpowers/specs/2026-07-02-dark-factory-token-optimization-rollout-design.md](../specs/2026-07-02-dark-factory-token-optimization-rollout-design.md)

## Goal

Implement the three remaining gaps in the Dark Factory token optimization rollout:
1. Per-feature independent `enabled: true/false` flags in `config.yaml` with env overrides and fail-safe bypass branches in each script.
2. Baseline token tracking in `context-budget.json` (schema v2) so savings are computable.
3. Savings row + fallbacks line in the per-run cost report comment; operator runbook.

## Architecture

Four optimization scripts gain bypass branches:
- `architecture_slice.py` — reads `_load_config()` (already wired); forces `_full_doc_result(fallback_reason="feature_disabled")` when `architecture.enabled: false`.
- `diff_rank.py` — `load_config()` already reads YAML; returns raw diff when `diff.enabled: false`; adds `raw_diff_tokens` to `diff-ranking.json`.
- `memory_retrieve.py` — gains minimal config read + `--config` CLI arg; bypasses top-k cap in `format_index_output()` when `memory.enabled: false`; emits `uncapped_tokens` in trace.
- `archon-dark-factory.yaml` — gates the `digest-comments` step on `TOKEN_OPTIMIZATION_COMMENTS_ENABLED`.

`context_budget.py` gains `baseline_tokens` per optimized section, reads sidecar artifacts for diff/memory baselines, bumps `schema_version` to 2, and adds `savings_tokens`/`savings_pct`.

`entrypoint.sh` `post_cost_report()` reads `context-budget.json` after the run and renders a savings row and fallbacks callout.

`scheduler.sh` wires the four new env vars via `_set_cfg`.

## Tech Stack

Python 3.11, PyYAML, bash, YAML (config + Archon workflow)

## File Structure

| File | Change |
|------|--------|
| `.claude/skills/refinement/config.yaml` | Add `enabled: true` under architecture/memory/comments/diff sub-sections |
| `dark-factory/scheduler.sh` | Add 4 `_set_cfg` entries at line ~99 |
| `dark-factory/scripts/architecture_slice.py` | Read `token_optimization.architecture.enabled`; force `_full_doc_result` when false |
| `dark-factory/scripts/diff_rank.py` | `load_config()` returns `enabled` flag; bypass in `build_ranked_diff()`; `raw_diff_tokens` in JSON |
| `dark-factory/scripts/memory_retrieve.py` | Add `--config` arg + config read; bypass top-k in `format_index_output()`; `uncapped_tokens` in trace |
| `.archon/workflows/archon-dark-factory.yaml` | Gate `digest-comments` step on `TOKEN_OPTIMIZATION_COMMENTS_ENABLED` |
| `dark-factory/scripts/context_budget.py` | `baseline_tokens` per section, schema_version 2, savings top-level fields |
| `dark-factory/entrypoint.sh` | Extend `post_cost_report()` with savings row and fallbacks line |
| `docs/agents/dark-factory-token-optimization.md` | New operator runbook |
| `dark-factory/tests/test_token_optimization_flags.py` | New: config flag + scheduler + workflow YAML content tests |

---

## Task 1 — Config flags: add `enabled: true` to each feature sub-section

**Files:** `.claude/skills/refinement/config.yaml`, `dark-factory/tests/test_token_optimization_flags.py`

### TDD

**1. Write failing test** — create `dark-factory/tests/test_token_optimization_flags.py`:
```python
"""Tests for per-feature token optimization flags (R1)."""
import pathlib
import yaml

CONFIG = pathlib.Path(__file__).resolve().parents[2] / ".claude/skills/refinement/config.yaml"


def _tok_opt():
    return yaml.safe_load(CONFIG.read_text()).get("token_optimization", {})


def test_architecture_enabled_flag_exists():
    assert "enabled" in _tok_opt().get("architecture", {}), \
        "architecture sub-section must have an 'enabled' key"


def test_memory_enabled_flag_exists():
    assert "enabled" in _tok_opt().get("memory", {}), \
        "memory sub-section must have an 'enabled' key"


def test_comments_enabled_flag_exists():
    assert "enabled" in _tok_opt().get("comments", {}), \
        "comments sub-section must have an 'enabled' key"


def test_diff_enabled_flag_exists():
    assert "enabled" in _tok_opt().get("diff", {}), \
        "diff sub-section must have an 'enabled' key"
```

**2. Verify failures:**
```bash
cd /workspace/markethawk && python -m pytest dark-factory/tests/test_token_optimization_flags.py -v
# Expected: 4 FAILED (KeyError or assertion)
```

**3. Implement** — edit `.claude/skills/refinement/config.yaml`, adding `enabled: true` as the first key under each feature block:

```yaml
token_optimization:
  enabled: true
  enforce_budgets: false
  default_budget_tokens: 24000
  architecture:
    enabled: true                            # NEW — env: TOKEN_OPTIMIZATION_ARCHITECTURE_ENABLED
    mode: slice
    max_tokens: 3000
  memory:
    enabled: true                            # NEW — env: TOKEN_OPTIMIZATION_MEMORY_ENABLED
    mode: top_k
    max_entries: 8
    max_tokens: 1500
  comments:
    enabled: true                            # NEW — env: TOKEN_OPTIMIZATION_COMMENTS_ENABLED
    digest_after_factory_marker: true
    max_tokens: 2000
  diff:
    enabled: true                            # NEW — env: TOKEN_OPTIMIZATION_DIFF_ENABLED
    max_review_tokens: 6000
```

**4. Verify passes:**
```bash
python -m pytest dark-factory/tests/test_token_optimization_flags.py::test_architecture_enabled_flag_exists \
  dark-factory/tests/test_token_optimization_flags.py::test_memory_enabled_flag_exists \
  dark-factory/tests/test_token_optimization_flags.py::test_comments_enabled_flag_exists \
  dark-factory/tests/test_token_optimization_flags.py::test_diff_enabled_flag_exists -v
# Expected: 4 passed
```

**5. Commit:**
```bash
git add .claude/skills/refinement/config.yaml dark-factory/tests/test_token_optimization_flags.py
git commit -m "feat(#673): add per-feature enabled flags to token_optimization config"
```

---

## Task 2 — Scheduler: wire `_set_cfg` entries for four new env vars

**Files:** `dark-factory/scheduler.sh`, `dark-factory/tests/test_token_optimization_flags.py`

### TDD

**1. Add failing tests** to `test_token_optimization_flags.py`:
```python
def test_scheduler_wires_architecture_enabled():
    content = (pathlib.Path(__file__).resolve().parents[1] / "scheduler.sh").read_text()
    assert "TOKEN_OPTIMIZATION_ARCHITECTURE_ENABLED" in content
    assert ".token_optimization.architecture.enabled" in content


def test_scheduler_wires_memory_enabled():
    content = (pathlib.Path(__file__).resolve().parents[1] / "scheduler.sh").read_text()
    assert "TOKEN_OPTIMIZATION_MEMORY_ENABLED" in content
    assert ".token_optimization.memory.enabled" in content


def test_scheduler_wires_comments_enabled():
    content = (pathlib.Path(__file__).resolve().parents[1] / "scheduler.sh").read_text()
    assert "TOKEN_OPTIMIZATION_COMMENTS_ENABLED" in content
    assert ".token_optimization.comments.enabled" in content


def test_scheduler_wires_diff_enabled():
    content = (pathlib.Path(__file__).resolve().parents[1] / "scheduler.sh").read_text()
    assert "TOKEN_OPTIMIZATION_DIFF_ENABLED" in content
    assert ".token_optimization.diff.enabled" in content
```

**2. Verify failures:**
```bash
python -m pytest dark-factory/tests/test_token_optimization_flags.py -k "scheduler" -v
# Expected: 4 FAILED
```

**3. Implement** — in `dark-factory/scheduler.sh`, after the `MAIN_RED_AUTOFIX_THROTTLE_MIN` line (~line 98), insert:
```bash
  _set_cfg TOKEN_OPTIMIZATION_ARCHITECTURE_ENABLED '.token_optimization.architecture.enabled'
  _set_cfg TOKEN_OPTIMIZATION_MEMORY_ENABLED       '.token_optimization.memory.enabled'
  _set_cfg TOKEN_OPTIMIZATION_COMMENTS_ENABLED     '.token_optimization.comments.enabled'
  _set_cfg TOKEN_OPTIMIZATION_DIFF_ENABLED         '.token_optimization.diff.enabled'
```

**4. Verify passes:**
```bash
python -m pytest dark-factory/tests/test_token_optimization_flags.py -k "scheduler" -v
# Expected: 4 passed
```

**5. Commit:**
```bash
git add dark-factory/scheduler.sh dark-factory/tests/test_token_optimization_flags.py
git commit -m "feat(#673): wire TOKEN_OPTIMIZATION_<FEATURE>_ENABLED env vars in scheduler _set_cfg"
```

---

## Task 3 — Architecture slice bypass when `architecture.enabled: false`

**Files:** `dark-factory/scripts/architecture_slice.py`, `dark-factory/tests/test_architecture_slice.py`

### TDD

**1. Add failing test** to `dark-factory/tests/test_architecture_slice.py`:
```python
import textwrap

def test_slice_bypasses_when_feature_disabled(arch_file, tmp_path):
    """slice_architecture() must return full-doc fallback when architecture.enabled is false."""
    cfg_dir = tmp_path / ".claude" / "skills" / "refinement"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text(textwrap.dedent("""\
        token_optimization:
          architecture:
            enabled: false
    """))
    result = aslice.slice_architecture(
        arch_path=str(arch_file),
        scenario="implement",
        spec_file="backend/app/services/scanner.py",
        clone_dir=str(tmp_path),
    )
    assert result.fallback is True
    assert result.fallback_reason == "feature_disabled"
```

**2. Verify failure:**
```bash
python -m pytest dark-factory/tests/test_architecture_slice.py::test_slice_bypasses_when_feature_disabled -v
# Expected: FAILED (fallback is False)
```

**3. Implement** — in `dark-factory/scripts/architecture_slice.py`, in `slice_architecture()`, insert a config check immediately after `cfg = _load_config(clone_dir)` (line ~320):

```python
def slice_architecture(
    arch_path: str,
    scenario: str,
    spec_component: str | None = None,
    spec_file: str | None = None,
    changed_files: list[str] | None = None,
    labels: list[str] | None = None,
    clone_dir: str | None = None,
) -> SliceResult:
    """Return a SliceResult with a component-scoped or full-doc ARCHITECTURE.md slice."""
    changed_files = changed_files or []
    labels = labels or []

    cfg = _load_config(clone_dir)
    all_sections = _parse_sections(arch_path)
    all_section_names = list(all_sections.keys())

    # 0. Feature-disabled bypass (R1/R4 — fail-safe: widen to full doc)
    arch_enabled = (
        cfg.get("token_optimization", {})
        .get("architecture", {})
        .get("enabled", True)
    )
    if not arch_enabled:
        return _full_doc_result(arch_path, all_sections, all_section_names,
                                scenario, None, "feature_disabled")

    # 1. Resolve component
    ...
```

The insertion point is between `all_section_names = list(all_sections.keys())` and `# 1. Resolve component`. The remaining lines are unchanged.

**4. Verify passes:**
```bash
python -m pytest dark-factory/tests/test_architecture_slice.py -v
# Expected: all pass including new test
```

**5. Commit:**
```bash
git add dark-factory/scripts/architecture_slice.py dark-factory/tests/test_architecture_slice.py
git commit -m "feat(#673): architecture_slice bypasses slicing when architecture.enabled is false"
```

---

## Task 4 — Diff rank bypass when `diff.enabled: false`; add `raw_diff_tokens` to sidecar

**Files:** `dark-factory/scripts/diff_rank.py`, `dark-factory/tests/test_diff_rank.py`

### TDD

**1. Add failing tests** to `dark-factory/tests/test_diff_rank.py`:
```python
def test_load_config_returns_enabled_true_by_default():
    """load_config() must return diff_enabled=True when key absent."""
    token_cap, score_floor, diff_enabled = dr.load_config.__wrapped__("/nonexistent/path.yaml") \
        if hasattr(dr.load_config, "__wrapped__") else dr.load_config("/nonexistent/path.yaml")
    assert diff_enabled is True


def test_load_config_reads_enabled_false(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("token_optimization:\n  diff:\n    enabled: false\n    max_review_tokens: 6000\n")
    token_cap, score_floor, diff_enabled = dr.load_config(str(cfg))
    assert diff_enabled is False


def make_raw_diff():
    return (
        "diff --git a/backend/app/routers/scanner.py b/backend/app/routers/scanner.py\n"
        "index aaa..bbb 100644\n"
        "--- a/backend/app/routers/scanner.py\n"
        "+++ b/backend/app/routers/scanner.py\n"
        "@@ -1,3 +1,4 @@\n"
        " import os\n"
        "+import sys\n"
        " def foo(): pass\n"
        " def bar(): pass\n"
    )


def test_build_ranked_diff_bypasses_when_disabled():
    """When diff_enabled=False, build_ranked_diff returns the raw diff unchanged and
    sets ranking_info['feature_disabled'] = True."""
    raw = make_raw_diff()
    ranked, info = dr.build_ranked_diff(
        diff_text=raw,
        token_cap=6000,
        hotspot_paths=set(),
        hotspot_scores={},
        spec_names=set(),
        score_floor=5.0,
        diff_enabled=False,
    )
    assert ranked == raw
    assert info.get("feature_disabled") is True


def test_build_ranked_diff_includes_raw_diff_tokens():
    """ranking_info must include raw_diff_tokens (baseline for savings computation)."""
    raw = make_raw_diff()
    _, info = dr.build_ranked_diff(
        diff_text=raw,
        token_cap=6000,
        hotspot_paths=set(),
        hotspot_scores={},
        spec_names=set(),
        score_floor=5.0,
    )
    assert "raw_diff_tokens" in info
    assert info["raw_diff_tokens"] >= 0
```

**2. Verify failures:**
```bash
python -m pytest dark-factory/tests/test_diff_rank.py -k "enabled or raw_diff" -v
# Expected: FAILED (load_config returns 2-tuple; build_ranked_diff missing diff_enabled param)
```

**3. Implement** — in `dark-factory/scripts/diff_rank.py`:

Update `load_config()` to return a 3-tuple `(token_cap, score_floor, diff_enabled)`:
```python
def load_config(path: str) -> tuple:
    """Return (token_cap: int, score_floor: float, diff_enabled: bool) from config yaml."""
    try:
        import yaml  # type: ignore
        with open(path) as f:
            data = yaml.safe_load(f)
        token_cap = int(
            data.get("token_optimization", {})
            .get("diff", {})
            .get("max_review_tokens", 6000)
        )
        score_floor = float(
            data.get("blast_radius", {}).get("hotspot_score_floor", 5.0)
        )
        diff_enabled = bool(
            data.get("token_optimization", {})
            .get("diff", {})
            .get("enabled", True)
        )
        return token_cap, score_floor, diff_enabled
    except Exception:
        return 6000, 5.0, True
```

Update `build_ranked_diff()` signature to accept `diff_enabled=True` and add `raw_diff_tokens` to output:
```python
def build_ranked_diff(
    diff_text: str,
    token_cap: int,
    hotspot_paths: set,
    hotspot_scores: dict,
    spec_names: set,
    score_floor: float,
    diff_enabled: bool = True,
) -> tuple:
    """Return (ranked_diff_str, ranking_info_dict).

    ranked_diff_str is empty when diff_text is empty.
    """
    import token_estimate as te  # already imported at module level if available

    try:
        from token_estimate import estimate_tokens
    except ImportError:
        estimate_tokens = lambda t: len(t) // 4

    raw_diff_tokens = estimate_tokens(diff_text)

    ranking_base = {
        "token_cap": token_cap,
        "raw_diff_tokens": raw_diff_tokens,
        "estimated_tokens_emitted": 0,
        "critical_tokens": 0,
        "residual_tokens": 0,
        "files": [],
    }

    # Feature-disabled bypass: return raw diff unchanged (R1/R4 — fail-safe)
    if not diff_enabled:
        ranking_base["feature_disabled"] = True
        ranking_base["estimated_tokens_emitted"] = raw_diff_tokens
        return diff_text, ranking_base

    files = parse_diff_files(diff_text)
    if not files:
        return "", ranking_base
    ...  # remainder of function unchanged
```

Also update the three callers in the CLI `main()` function where `load_config()` is called:
```python
# In parse_args()-driven main():
token_cap, score_floor, diff_enabled = load_config(args.config) if args.config else (6000, 5.0, True)
...
ranked_diff, ranking_info = build_ranked_diff(
    diff_text=...,
    token_cap=token_cap,
    hotspot_paths=hotspot_paths,
    hotspot_scores=hotspot_scores,
    spec_names=spec_names,
    score_floor=score_floor,
    diff_enabled=diff_enabled,
)
```

Note: `estimate_tokens` is already imported at the top of `diff_rank.py` as `from gate_blast_radius import parse_hotspots`. Check the actual import; `token_estimate` may need to be added to `sys.path` or use the local helper. Looking at the existing code, `build_ranked_diff` already calls `estimate_tokens(text)` on lines 395 and 416 without a local import — this function is already in scope. So `raw_diff_tokens = estimate_tokens(diff_text)` can be added at the top of `build_ranked_diff()` without any new imports.

**4. Verify passes:**
```bash
python -m pytest dark-factory/tests/test_diff_rank.py -v
# Expected: all pass
```

**5. Commit:**
```bash
git add dark-factory/scripts/diff_rank.py dark-factory/tests/test_diff_rank.py
git commit -m "feat(#673): diff_rank bypasses truncation when diff.enabled is false; add raw_diff_tokens to sidecar"
```

---

## Task 5 — Memory retrieve bypass when `memory.enabled: false`; emit `uncapped_tokens` in trace

**Files:** `dark-factory/scripts/memory_retrieve.py`, `dark-factory/tests/test_memory_retrieve.py`

### TDD

**1. Add failing tests** to `dark-factory/tests/test_memory_retrieve.py`:
```python
import textwrap

def test_format_index_output_emits_uncapped_tokens():
    """format_index_output() must populate cap_out['uncapped_tokens'] with the
    total token cost of all ranked candidates before the k/budget cap is applied."""
    candidates = [
        {
            "id": "aabb", "kind": "PATTERN", "text": "- [PATTERN] Alpha entry <!-- -->",
            "source_file": "codebase-patterns.md", "specificity": 0, "created_at": "",
        },
        {
            "id": "ccdd", "kind": "PATTERN", "text": "- [PATTERN] Beta entry <!-- -->",
            "source_file": "codebase-patterns.md", "specificity": 0, "created_at": "",
        },
    ]
    cap_out = {}
    mr.format_index_output(candidates, _cap_out=cap_out)
    assert "uncapped_tokens" in cap_out
    assert cap_out["uncapped_tokens"] > 0


def test_format_index_output_bypasses_cap_when_disabled(monkeypatch, tmp_path):
    """When memory.enabled is false in config, ALL candidates must be returned
    (no top-k cap) and cap_out['feature_disabled'] must be True."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text("token_optimization:\n  memory:\n    enabled: false\n")
    monkeypatch.setenv("DARK_FACTORY_CONFIG", str(cfg))

    # Build 12 candidates (exceeds TOP_K_DEFAULT=8)
    candidates = [
        {
            "id": f"id{i:02d}", "kind": "PATTERN",
            "text": f"- [PATTERN] Entry {i} <!-- -->",
            "source_file": "codebase-patterns.md", "specificity": 0, "created_at": "",
        }
        for i in range(12)
    ]
    cap_out = {}
    output = mr.format_index_output(candidates, _cap_out=cap_out)
    # All 12 entries must appear when feature is disabled
    assert cap_out["entries_selected"] == 12
    assert cap_out.get("feature_disabled") is True
```

**2. Verify failures:**
```bash
python -m pytest dark-factory/tests/test_memory_retrieve.py -k "uncapped or bypasses_cap" -v
# Expected: 2 FAILED
```

**3. Implement** — in `dark-factory/scripts/memory_retrieve.py`:

Add config-reading helper (after the existing constants block, around line 90):
```python
_MEMORY_CONFIG_PATHS = [
    "/workspace/project/.claude/skills/refinement/config.yaml",
    "/opt/refinement-skills/config.yaml",
]


def _load_memory_config(config_path: str | None = None) -> dict:
    """Load token_optimization.memory section from config.yaml. Returns {} on failure."""
    candidates = []
    if config_path:
        candidates.append(config_path)
    env_path = os.environ.get("DARK_FACTORY_CONFIG", "")
    if env_path:
        candidates.append(env_path)
    candidates.extend(_MEMORY_CONFIG_PATHS)
    for path in candidates:
        if not path or not os.path.exists(path):
            continue
        try:
            import yaml  # type: ignore
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                return data.get("token_optimization", {}).get("memory", {})
        except Exception:
            pass
    return {}
```

Note: `os` is already imported in `memory_retrieve.py` as needed (it uses `sys` but not `os`). Add `import os` at the top if not present.

Update `format_index_output()` to accept `config_path=None` and implement bypass + uncapped tracking:
```python
def format_index_output(candidates, labels=None, _cap_out=None, config_path=None):
    """Return a formatted markdown string of the top-k candidates.

    R1/R4: when memory.enabled is false, all candidates are returned (no cap).
    cap_out gains 'uncapped_tokens' (total tokens before cap).
    """
    mem_cfg = _load_memory_config(config_path)
    mem_enabled = mem_cfg.get("enabled", True)

    ranked = sorted(
        candidates,
        key=lambda c: (
            c["specificity"] + compute_label_boost(c["source_file"], labels),
            c.get("created_at") or "",
        ),
        reverse=True,
    )

    # Compute uncapped total for baseline tracking (always, regardless of enabled flag)
    uncapped_tokens = sum(te.estimate_tokens(c["text"]) for c in ranked)
    if _cap_out is not None:
        _cap_out["uncapped_tokens"] = uncapped_tokens

    # Feature-disabled bypass: emit all entries, no top-k or budget cap
    if not mem_enabled:
        if _cap_out is not None:
            _cap_out["feature_disabled"] = True
            _cap_out["entries_selected"] = len(ranked)
            _cap_out["entries_dropped_by_cap"] = 0
            _cap_out["per_file_selected"] = {}
            _cap_out["per_file_dropped"] = {}
        selected = ranked
    else:
        selected = []
        dropped = []
        token_total = 0
        for c in ranked:
            token_cost = te.estimate_tokens(c["text"])
            if len(selected) >= TOP_K_DEFAULT or (selected and token_total + token_cost > TOKEN_BUDGET_DEFAULT):
                if selected and token_total + token_cost > TOKEN_BUDGET_DEFAULT and len(selected) < TOP_K_DEFAULT:
                    sys.stderr.write(
                        f"memory-cap: dropped oversized entry ({token_cost} tokens) from {c['source_file']}\n"
                    )
                dropped.append(c)
            else:
                selected.append(c)
                token_total += token_cost

        if _cap_out is not None:
            per_file_selected: dict = {}
            per_file_dropped: dict = {}
            for c in selected:
                per_file_selected[c["source_file"]] = per_file_selected.get(c["source_file"], 0) + 1
            for c in dropped:
                per_file_dropped[c["source_file"]] = per_file_dropped.get(c["source_file"], 0) + 1
            _cap_out["entries_selected"] = len(selected)
            _cap_out["entries_dropped_by_cap"] = len(dropped)
            _cap_out["per_file_selected"] = per_file_selected
            _cap_out["per_file_dropped"] = per_file_dropped

    grouped: dict = {}
    for c in selected:
        grouped.setdefault(c["source_file"], []).append(c)

    parts = []
    for fname in ALL_MEMORY_FILES:
        if fname not in grouped:
            continue
        parts.append(f"### Memory: {fname}")
        for e in grouped[fname]:
            parts.append(e["text"])
        parts.append("")

    return "\n".join(parts).rstrip()
```

Also update `emit_memory_trace()` to include `uncapped_tokens` from `cap_counts`:
```python
# In emit_memory_trace(), after the existing cap_counts block (~line 487):
if cap_counts and not cap_counts.get("fallback_used"):
    trace["entries_selected_total"] = cap_counts.get("entries_selected", 0)
    trace["entries_dropped_by_cap_total"] = cap_counts.get("entries_dropped_by_cap", 0)
    if "uncapped_tokens" in cap_counts:
        trace["uncapped_tokens"] = cap_counts["uncapped_tokens"]
    if cap_counts.get("feature_disabled"):
        trace["feature_disabled"] = True
```

**4. Verify passes:**
```bash
python -m pytest dark-factory/tests/test_memory_retrieve.py -v
# Expected: all pass including 2 new tests
```

**5. Commit:**
```bash
git add dark-factory/scripts/memory_retrieve.py dark-factory/tests/test_memory_retrieve.py
git commit -m "feat(#673): memory_retrieve bypasses top-k when memory.enabled is false; emit uncapped_tokens in trace"
```

---

## Task 6 — Comment digest workflow gate on `TOKEN_OPTIMIZATION_COMMENTS_ENABLED`

**Files:** `.archon/workflows/archon-dark-factory.yaml`, `dark-factory/tests/test_token_optimization_flags.py`

### TDD

**1. Add failing test** to `test_token_optimization_flags.py`:
```python
def test_workflow_gates_comment_digest_on_env_var():
    """The digest-comments step in archon-dark-factory.yaml must have a when condition
    that checks TOKEN_OPTIMIZATION_COMMENTS_ENABLED, so setting it to 'false' skips
    the step (R1/R4 fail-safe: raw comments from issue.json are used instead)."""
    content = (
        pathlib.Path(__file__).resolve().parents[2]
        / ".archon/workflows/archon-dark-factory.yaml"
    ).read_text()
    # The when clause must reference the env var, whether as a shell expression or YAML
    assert "TOKEN_OPTIMIZATION_COMMENTS_ENABLED" in content
```

**2. Verify failure:**
```bash
python -m pytest dark-factory/tests/test_token_optimization_flags.py::test_workflow_gates_comment_digest_on_env_var -v
# Expected: FAILED
```

**3. Implement** — in `.archon/workflows/archon-dark-factory.yaml`, the `digest-comments` step currently has:
```yaml
  - id: digest-comments
    bash: |
      _CLONE="${CLONE_DIR:-.}"
      python3 "$_CLONE/dark-factory/scripts/comment_digest.py" \
        --issue-json "$ARTIFACTS_DIR/issue.json" \
        --out "$ARTIFACTS_DIR/comment-digest.md"
      cat "$ARTIFACTS_DIR/comment-digest.md"
    depends_on: [fetch-issue]
    when: "$parse-intent.output.intent == 'continue'"
    timeout: 15000
```

Update to add the `TOKEN_OPTIMIZATION_COMMENTS_ENABLED` guard. The gate is added inside the bash block as a shell conditional — this keeps the existing `when:` (intent check) intact while adding the feature flag guard:

```yaml
  - id: digest-comments
    bash: |
      _CLONE="${CLONE_DIR:-.}"
      _COMMENTS_ENABLED="${TOKEN_OPTIMIZATION_COMMENTS_ENABLED:-true}"
      if [ "$_COMMENTS_ENABLED" = "false" ]; then
        echo "[token-opt] comment digest skipped (TOKEN_OPTIMIZATION_COMMENTS_ENABLED=false)" >&2
        exit 0
      fi
      python3 "$_CLONE/dark-factory/scripts/comment_digest.py" \
        --issue-json "$ARTIFACTS_DIR/issue.json" \
        --out "$ARTIFACTS_DIR/comment-digest.md"
      cat "$ARTIFACTS_DIR/comment-digest.md"
    depends_on: [fetch-issue]
    when: "$parse-intent.output.intent == 'continue'"
    timeout: 15000
```

When `TOKEN_OPTIMIZATION_COMMENTS_ENABLED=false`, the step exits 0 without producing `comment-digest.md`; the downstream `continue` flow already falls back to raw `comments` from `issue.json` (the pre-digest path), satisfying R4.

**4. Verify passes:**
```bash
python -m pytest dark-factory/tests/test_token_optimization_flags.py -v
# Expected: all pass
```

**5. Commit:**
```bash
git add .archon/workflows/archon-dark-factory.yaml dark-factory/tests/test_token_optimization_flags.py
git commit -m "feat(#673): gate comment_digest.py on TOKEN_OPTIMIZATION_COMMENTS_ENABLED in workflow YAML"
```

---

## Task 7 — Context budget schema v2: baseline tokens and savings fields

**Files:** `dark-factory/scripts/context_budget.py`, `dark-factory/tests/test_context_budget.py`

### TDD

**1. Add failing tests** to `dark-factory/tests/test_context_budget.py`:
```python
import textwrap, yaml

def test_schema_version_is_2(tmp_path):
    """context-budget.json must be schema_version 2."""
    issue_json = make_issue_json(tmp_path)
    out = tmp_path / "budget.json"
    cb.build_budget(
        scenario="refine",
        issue_num=673,
        run_id="test-run",
        clone_dir=str(tmp_path),
        out=str(out),
        issue_json=issue_json,
    )
    data = json.loads(out.read_text())
    assert data["schema_version"] == 2


def test_architecture_md_has_baseline_tokens(tmp_path):
    """architecture_md section must have baseline_tokens when slice is active."""
    arch = tmp_path / "ARCHITECTURE.md"
    arch.write_text("# Architecture\n\n## Backend Module Map\n\ncontent here.\n")
    issue_json = make_issue_json(tmp_path)
    out = tmp_path / "budget.json"
    cb.build_budget(
        scenario="refine",
        issue_num=673,
        run_id="test-run",
        clone_dir=str(tmp_path),
        out=str(out),
        issue_json=issue_json,
    )
    data = json.loads(out.read_text())
    arch_sec = data["sections"].get("architecture_md", {})
    assert "baseline_tokens" in arch_sec
    assert arch_sec["baseline_tokens"] >= arch_sec.get("tokens", 0)


def test_top_level_savings_fields_present(tmp_path):
    """Artifact must have savings_tokens and savings_pct at top level when
    baseline_input_tokens is computable."""
    arch = tmp_path / "ARCHITECTURE.md"
    arch.write_text("# Architecture\n\n## Backend Module Map\n\ncontent here.\n" * 10)
    issue_json = make_issue_json(tmp_path)
    out = tmp_path / "budget.json"
    cb.build_budget(
        scenario="refine",
        issue_num=673,
        run_id="test-run",
        clone_dir=str(tmp_path),
        out=str(out),
        issue_json=issue_json,
    )
    data = json.loads(out.read_text())
    assert "baseline_input_tokens" in data
    assert "savings_tokens" in data
    assert "savings_pct" in data
```

**2. Verify failures:**
```bash
python -m pytest dark-factory/tests/test_context_budget.py -k "schema_version or baseline or savings" -v
# Expected: 3 FAILED
```

**3. Implement** — in `dark-factory/scripts/context_budget.py`:

**3a.** In the `architecture_md` section of `build_budget()`, add `baseline_tokens` by reading the full ARCHITECTURE.md:
```python
elif sec == "architecture_md":
    arch_path = os.path.join(clone_dir, "ARCHITECTURE.md")
    result = aslice.slice_architecture(
        arch_path=arch_path,
        scenario=scenario,
        spec_component=spec_component,
        spec_file=spec_file,
        changed_files=changed_files,
        labels=labels,
        clone_dir=clone_dir,
    )
    status = "included" if result.fallback else "included_slice"
    tokens = te.estimate_tokens(result.text)
    # baseline_tokens: full ARCHITECTURE.md without slicing
    full_arch_text = _read_text(arch_path)
    baseline_tokens = te.estimate_tokens(full_arch_text) if full_arch_text else tokens
    sections[sec] = {
        "status": status,
        "tokens": tokens,
        "baseline_tokens": baseline_tokens,
        "component": result.component,
        "included_sections": result.included_sections,
        "omitted_sections": result.omitted_sections,
        "section_hashes": result.section_hashes,
        "fallback": result.fallback,
        "fallback_reason": result.fallback_reason,
    }
    h = te.hash_file(arch_path)
    if h:
        source_hashes["ARCHITECTURE.md"] = h
```

**3b.** In the `memory_context` section, read `uncapped_tokens` from `memory-trace.json`:
```python
elif sec == "memory_context":
    sections[sec] = _included(_read_text(memory_file), memory_file)
    if memory_file and sections[sec]["status"] == "included":
        h = te.hash_file(memory_file)
        if h:
            source_hashes["memory-context.md"] = h
    # Best-effort: surface cap counts and baseline from memory-trace.json
    if artifacts_dir and sections[sec]["status"] != "dropped":
        trace_path = os.path.join(artifacts_dir, "memory-trace.json")
        trace = _read_json(trace_path)
        if trace:
            sections[sec]["entries_selected"] = trace.get("entries_selected_total", 0)
            sections[sec]["entries_dropped"] = trace.get("entries_dropped_by_cap_total", 0)
            if "uncapped_tokens" in trace:
                sections[sec]["baseline_tokens"] = trace["uncapped_tokens"]
```

**3c.** In the `comment_digest` section, add `baseline_tokens` from raw comments in `issue_json`:
```python
elif sec == "comment_digest":
    sections[sec] = _probe_comment_digest(comment_digest_file)
    # baseline_tokens: raw comments before digest
    if issue_json:
        issue_data = _read_json(issue_json)
        if issue_data:
            raw_comments = issue_data.get("comments", [])
            raw_text = "\n".join(c.get("body", "") for c in raw_comments if isinstance(c, dict))
            sections[sec]["baseline_tokens"] = te.estimate_tokens(raw_text)
```

**3d.** In the `diff` section, add `baseline_tokens` from `diff-ranking.json`:
```python
elif sec == "diff":
    sections[sec] = _probe_diff(diff_file)
    if diff_file and sections[sec]["status"] in ("included", "included_partial"):
        h = te.hash_file(diff_file)
        if h:
            source_hashes["diff"] = h
    # baseline_tokens: raw un-ranked diff token count from diff-ranking.json sidecar
    if artifacts_dir:
        ranking_path = os.path.join(artifacts_dir, "diff-ranking.json")
        ranking_data = _read_json(ranking_path)
        if ranking_data and "raw_diff_tokens" in ranking_data:
            sections[sec]["baseline_tokens"] = ranking_data["raw_diff_tokens"]
```

Add a helper `_read_json()` if not already present:
```python
def _read_json(path: str | None) -> dict | None:
    """Read and parse a JSON file; return None on any error."""
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
```

**3e.** In the artifact assembly block, bump schema_version and add savings fields:
```python
    estimated = sum(v.get("tokens", 0) for v in sections.values())
    baseline = sum(v.get("baseline_tokens", v.get("tokens", 0)) for v in sections.values())
    utilization = round(estimated / BUDGET_TOKENS * 100, 1)
    savings_tokens = baseline - estimated
    savings_pct = round(savings_tokens / baseline * 100, 1) if baseline > 0 else 0.0

    included_sections = [k for k, v in sections.items() if v.get("status") in ("included", "included_partial", "included_slice")]
    dropped_sections = [k for k, v in sections.items() if v.get("status") == "dropped"]

    artifact = {
        "schema_version": 2,
        "scenario": scenario,
        "run_id": run_id,
        "issue_number": issue_num,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "budget_tokens": BUDGET_TOKENS,
        "baseline_input_tokens": baseline,
        "estimated_input_tokens": estimated,
        "savings_tokens": savings_tokens,
        "savings_pct": savings_pct,
        "utilization_pct": utilization,
        "sections": sections,
        "included_sections": included_sections,
        "dropped_sections": dropped_sections,
        "source_file_hashes": source_hashes,
    }
```

Also add `import json` at the top if not present (it's already imported in most scripts — confirm).

**4. Verify passes:**
```bash
python -m pytest dark-factory/tests/test_context_budget.py -v
# Expected: all pass including 3 new tests
```

**5. Commit:**
```bash
git add dark-factory/scripts/context_budget.py dark-factory/tests/test_context_budget.py
git commit -m "feat(#673): context_budget schema v2 — baseline_tokens per section, savings_tokens/savings_pct top-level"
```

---

## Task 8 — Extend `post_cost_report()` with savings row and fallbacks line

**Files:** `dark-factory/entrypoint.sh`

### TDD

The cost report is a bash function that calls `gh api`. The unit test approach is to extract and test the jq/bash logic inline. Use `test_cost_report_endpoint.sh` pattern if it exists; otherwise validate via dry-run of the function components.

**1. Write a targeted test** — create `dark-factory/tests/test_cost_report_savings.sh`:
```bash
#!/usr/bin/env bash
# Test: savings row is extracted correctly from a context-budget.json v2 artifact.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")/../scripts" && pwd)"
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

# Create a synthetic v2 budget artifact
cat > "$TMPDIR/context-budget.json" <<'EOF'
{
  "schema_version": 2,
  "baseline_input_tokens": 20000,
  "estimated_input_tokens": 14000,
  "savings_tokens": 6000,
  "savings_pct": 30.0,
  "sections": {
    "architecture_md": {
      "status": "included_slice",
      "tokens": 2000,
      "baseline_tokens": 8000,
      "fallback": false,
      "fallback_reason": null
    }
  }
}
EOF

# Test: savings extraction
SAVINGS_TOKENS=$(jq -r '.savings_tokens // 0' "$TMPDIR/context-budget.json")
SAVINGS_PCT=$(jq -r '.savings_pct // 0' "$TMPDIR/context-budget.json")
[ "$SAVINGS_TOKENS" = "6000" ] || { echo "FAIL: savings_tokens expected 6000, got $SAVINGS_TOKENS"; exit 1; }
[ "$SAVINGS_PCT" = "30" ] || { echo "FAIL: savings_pct expected 30, got $SAVINGS_PCT"; exit 1; }

# Test: fallbacks extraction (no fallbacks → empty)
FALLBACKS=$(jq -r '[.sections | to_entries[] | select(.value.fallback == true) | "\(.key) → \(.value.fallback_reason // "unknown")"] | join(", ")' "$TMPDIR/context-budget.json")
[ -z "$FALLBACKS" ] || { echo "FAIL: expected no fallbacks, got: $FALLBACKS"; exit 1; }

# Test: fallbacks extraction (with fallback)
cat > "$TMPDIR/context-budget-fallback.json" <<'EOF'
{
  "schema_version": 2,
  "baseline_input_tokens": 20000,
  "estimated_input_tokens": 20000,
  "savings_tokens": 0,
  "savings_pct": 0,
  "sections": {
    "architecture_md": {
      "status": "included",
      "tokens": 18000,
      "baseline_tokens": 18000,
      "fallback": true,
      "fallback_reason": "safety_keyword:performance"
    }
  }
}
EOF
FALLBACKS=$(jq -r '[.sections | to_entries[] | select(.value.fallback == true) | "\(.key) → \(.value.fallback_reason // \"unknown\")"] | join(", ")' "$TMPDIR/context-budget-fallback.json")
[ "$FALLBACKS" = "architecture_md → safety_keyword:performance" ] || { echo "FAIL: expected fallback line, got: $FALLBACKS"; exit 1; }

echo "PASS: savings row extraction tests"
```

**2. Verify test runs:**
```bash
bash dark-factory/tests/test_cost_report_savings.sh
# Expected: PASS (this validates the jq logic we'll embed)
```

**3. Implement** — in `dark-factory/entrypoint.sh`, update `post_cost_report()`.

After the `Subtotal` row in the `BODY` heredoc (after the `${RUN_ROWS}` and `| **Subtotal** |` line), add a savings block. Insert this logic **before** the `BODY` variable is assembled, after `RUN_ROWS`:

```bash
  # Read savings and fallbacks from context-budget.json (schema v2 — || true guards throughout)
  local SAVINGS_LINE="" FALLBACKS_LINE=""
  local BUDGET_FILE="${ARTIFACTS_DIR:-}/context-budget.json"
  if [ -f "$BUDGET_FILE" ]; then
    local SCHEMA_VER SAVINGS_TOKENS SAVINGS_PCT FALLBACKS_STR
    SCHEMA_VER=$(jq -r '.schema_version // 1' "$BUDGET_FILE" 2>/dev/null || echo "1")
    if [ "$SCHEMA_VER" -ge 2 ] 2>/dev/null; then
      SAVINGS_TOKENS=$(jq -r '.savings_tokens // 0' "$BUDGET_FILE" 2>/dev/null || echo "0")
      SAVINGS_PCT=$(jq -r '.savings_pct // 0' "$BUDGET_FILE" 2>/dev/null || echo "0")
      if [ "${SAVINGS_TOKENS:-0}" -gt 0 ] 2>/dev/null; then
        SAVINGS_LINE="Context savings: $(fmt_tokens "$SAVINGS_TOKENS") tokens (${SAVINGS_PCT}% vs. baseline)"
      fi
      FALLBACKS_STR=$(jq -r '[.sections | to_entries[] | select(.value.fallback == true) | "\(.key) → \(.value.fallback_reason // "unknown")"] | join(", ")' "$BUDGET_FILE" 2>/dev/null || true)
      if [ -n "$FALLBACKS_STR" ]; then
        FALLBACKS_LINE="Fallbacks: ${FALLBACKS_STR}"
      fi
    fi
  fi
```

Then update the `BODY` variable to include the savings block after the subtotal:
```bash
  BODY="${COST_MARKER}
<!-- cumulative: cost=${CUM_COST} in=${CUM_IN} out=${CUM_OUT} -->
## Dark Factory — Cost Report

**${RUN_COUNT} run(s) — Total: \$${CUM_COST} ($(fmt_tokens "$CUM_IN") in / $(fmt_tokens "$CUM_OUT") out)**

${PRIOR_RUNS}
### Run: ${TIMESTAMP} (${INTENT:-fix}, ${RUN_STATUS})

| Step | Model | In tokens | Out tokens | Cost | Duration |
|------|-------|-----------|------------|------|----------|
${RUN_ROWS}
| **Subtotal** | | **$(fmt_tokens "$TOTAL_IN")** | **$(fmt_tokens "$TOTAL_OUT")** | **\$${TOTAL_COST}** | |
${SAVINGS_LINE:+
> ${SAVINGS_LINE}}${FALLBACKS_LINE:+
> ${FALLBACKS_LINE}}

---
*Updated by MarketHawk Dark Factory*"
```

The `${VAR:+...}` pattern emits the savings/fallbacks lines only when non-empty, and both are wrapped in the existing `|| true` guard pattern (via the earlier reads).

**4. Validate:**
```bash
bash dark-factory/tests/test_cost_report_savings.sh
# Expected: PASS
```

**5. Commit:**
```bash
git add dark-factory/entrypoint.sh dark-factory/tests/test_cost_report_savings.sh
git commit -m "feat(#673): post_cost_report renders savings row and fallbacks from context-budget.json v2"
```

---

## Task 9 — Operator runbook

**Files:** `docs/agents/dark-factory-token-optimization.md`

No TDD — documentation only.

**Create `docs/agents/dark-factory-token-optimization.md`** with the following sections:

```markdown
# Dark Factory — Token Optimization

This document covers the four active token optimizations, how to read the cost
report savings row, how to disable any one feature, and the path to Phase 4
(budget enforcement).

## What's active

All four optimizations shipped in epic #663 (closed issues #664–#671) and are
active on every factory run:

| Feature | Script | Config key | Issue |
|---------|--------|-----------|-------|
| Architecture slicing | `architecture_slice.py` | `token_optimization.architecture` | #664 |
| Memory top-k | `memory_retrieve.py` | `token_optimization.memory` | #665 |
| Comment digesting | `comment_digest.py` | `token_optimization.comments` | #668 |
| Diff ranking | `diff_rank.py` | `token_optimization.diff` | #670 |

**Current phase:** Phase 2/3 active. Phase 4 (budget enforcement) deferred —
see [Path to Phase 4](#path-to-phase-4-enforce) below.

## Reading the cost report

Each issue's cost report comment (posted by `post_cost_report()` in
`entrypoint.sh`) includes a savings row beneath the subtotal when the
`context-budget.json` artifact is schema_version 2:

```
| **Subtotal** | | **18.4K** | **6.2K** | **$0.0312** | |
> Context savings: 6.0K tokens (30% vs. baseline)
> Fallbacks: architecture_md → safety_keyword:performance
```

- **Context savings** — estimated tokens saved vs. loading full/unoptimized context.
  Derived from `savings_tokens` and `savings_pct` in `context-budget.json`.
- **Fallbacks** — any optimization that reverted to full/original context for this run
  (e.g., architecture slicer triggered a safety keyword and loaded the full
  `ARCHITECTURE.md` instead). The reason code is surfaced directly from the artifact.
  Absence of this line means no fallbacks occurred.

The savings row is omitted gracefully when the `context-budget.json` artifact is
missing or schema_version 1 (pre-#673 runs).

## Feature flag reference

Flags live in `.claude/skills/refinement/config.yaml` under `token_optimization:`
and can be overridden per-run via env vars in `.archon/.env`.

| Feature | config.yaml path | Env var override |
|---------|-----------------|-----------------|
| Architecture slicing | `token_optimization.architecture.enabled` | `TOKEN_OPTIMIZATION_ARCHITECTURE_ENABLED` |
| Memory top-k | `token_optimization.memory.enabled` | `TOKEN_OPTIMIZATION_MEMORY_ENABLED` |
| Comment digesting | `token_optimization.comments.enabled` | `TOKEN_OPTIMIZATION_COMMENTS_ENABLED` |
| Diff ranking | `token_optimization.diff.enabled` | `TOKEN_OPTIMIZATION_DIFF_ENABLED` |

All flags default to `true` when absent. Setting to `false` widens context to
the pre-optimization baseline (fail-safe — never silently drops content).

## Per-feature rollback

To disable a single feature without affecting others:

**Option A — config.yaml (persistent, affects all runs):**
```yaml
# .claude/skills/refinement/config.yaml
token_optimization:
  architecture:
    enabled: false   # disable only architecture slicing
```

**Option B — env var (per-run, overrides config):**
```bash
# .archon/.env
TOKEN_OPTIMIZATION_ARCHITECTURE_ENABLED=false
```

The disable path for each feature:
- **Architecture**: `slice_architecture()` returns `_full_doc_result(fallback_reason="feature_disabled")` → full ARCHITECTURE.md loaded.
- **Memory**: `format_index_output()` bypasses top-k and token cap → all memory entries returned.
- **Comments**: `digest-comments` step exits 0 early → `comment_digest.py` not called → raw `comments` from `issue.json` used.
- **Diff**: `build_ranked_diff()` returns the raw diff unchanged → no truncation or ranking.

## Full rollback

To disable all optimizations at once:
```bash
# .archon/.env
TOKEN_OPTIMIZATION_ENABLED=false
```

This is the existing global kill-switch (present before #673).

## Path to Phase 4 (enforce)

Phase 4 flips `enforce_budgets: true` in `config.yaml`. Enforcement means runs
that exceed the per-scenario token budget are flagged in the cost report (not
truncated silently). Recommended preconditions before flipping:

1. Confirm `savings_pct` is stable (±5%) across 20+ consecutive runs.
2. No quality regressions flagged in architect or conformance reviews.
3. No Fallbacks lines in the cost report for ≥10 consecutive runs (or fallback
   reasons are expected and understood).

When ready:
```yaml
# .claude/skills/refinement/config.yaml
token_optimization:
  enforce_budgets: true
```

No code changes required — `context_budget.py` already reads this flag.
```

**Commit:**
```bash
git add docs/agents/dark-factory-token-optimization.md
git commit -m "docs(#673): add operator runbook for Dark Factory token optimization"
```

---

## Task Order Summary

| # | Task | Tests | Files Changed |
|---|------|-------|--------------|
| 1 | Config flags | 4 new pytest | `config.yaml`, `test_token_optimization_flags.py` |
| 2 | Scheduler wiring | 4 new pytest | `scheduler.sh`, `test_token_optimization_flags.py` |
| 3 | Architecture bypass | 1 new pytest | `architecture_slice.py`, `test_architecture_slice.py` |
| 4 | Diff rank bypass + raw_diff_tokens | 4 new pytest | `diff_rank.py`, `test_diff_rank.py` |
| 5 | Memory bypass + uncapped_tokens | 2 new pytest | `memory_retrieve.py`, `test_memory_retrieve.py` |
| 6 | Workflow YAML gate | 1 new pytest | `archon-dark-factory.yaml`, `test_token_optimization_flags.py` |
| 7 | Context budget schema v2 | 3 new pytest | `context_budget.py`, `test_context_budget.py` |
| 8 | Cost report savings row | 1 new shell test | `entrypoint.sh`, `test_cost_report_savings.sh` |
| 9 | Operator runbook | — | `docs/agents/dark-factory-token-optimization.md` |

**Total:** 9 tasks, 40 steps (≈4–5 hours)
