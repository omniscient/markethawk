# Phase 4 T2 — Optimizer `max_tokens` cap-override reads

**Status:** design
**Date:** 2026-07-02
**Epic:** #713 (Phase 4 budget enforcement)
**Depends on:** T1 — `budget_enforce.py` + derivation (#721)
**See also:** Epic-level design: `docs/superpowers/specs/2026-07-02-token-opt-phase4-enforcement-design.md`

---

## Problem

`budget_enforce.py` (T1) derives per-scenario token caps and exports them as env vars
in enforce mode — but the four optimizers don't read those env vars yet.
Each optimizer uses either hardcoded constants or raw config values; there is no hook
for `budget_enforce.py` to hand a tighter cap at runtime.

T2 adds that hook: each optimizer gains an env-override read for its `max_tokens` key,
mirroring the `enabled` env-override pattern introduced in #673.
When unset, the optimizer falls back to its config value (current behavior, fail-open).
When set to an invalid value, same fallback — the feature is fail-open end to end.

---

## Goals & non-goals

**Goals**
- All four optimizers read their `max_tokens` env var; set → use it, unset → config default.
- Each optimizer's safety carve-outs remain structurally cap-immune (no new logic needed for the arch/diff carve-outs; the constraint is documented and tested).
- Tests proving env-override is honored AND safety carve-outs survive a tightened cap.

**Non-goals**
- No changes to `budget_enforce.py` (T1) or `context_budget.py` (T4).
- No DAG wiring changes (T3).
- No changes to `config.yaml` default values.

---

## Requirements (from Q&A)

1. **`architecture_slice.py`** — read `TOKEN_OPTIMIZATION_ARCHITECTURE_MAX_TOKENS`; when set and valid, apply as a token ceiling on the component-scoped slice via section exclusion (drop tail sections, never truncate mid-text). Cap only applies in the non-fallback (slice) path; `_full_doc_result` is structurally cap-immune.

2. **`memory_retrieve.py`** — read `TOKEN_OPTIMIZATION_MEMORY_MAX_TOKENS`; when set and valid, override the `TOKEN_BUDGET_DEFAULT` (1500) used in `format_index_output()`. The markdown fallback path is inherently cap-immune (no cap applied there). On any error, the full uncapped markdown is emitted (existing fail-open behavior).

3. **`diff_rank.py`** — read `TOKEN_OPTIMIZATION_DIFF_MAX_REVIEW_TOKENS`; when set and valid, override the `token_cap` derived from config in `load_config()`. Critical-tier files are structurally cap-immune (emitted via `_full()` into `critical_tokens`, outside the residual `budget` counter).

4. **`comment_digest.py`** — read `TOKEN_OPTIMIZATION_COMMENTS_MAX_TOKENS` (env-first, config-fallback, hardcoded default 2000); truncate the `build_digest()` output in `main()` after the fact. No cap-immune carve-out required (not listed in the issue's safety-immune set).

5. **Env-override pattern** (consistent across all four):
   - Check env var; if set and parseable as `int`, use it.
   - If not set or invalid, read `token_optimization.<section>.max_tokens` from config.
   - If config missing or invalid, use a hardcoded default.
   - Always fail open: any error → current behavior (no cap, or config default).

6. **Tests** — each optimizer gets tests for:
   - Env override honored when set.
   - Config fallback when env var unset.
   - Safety carve-out: tightened cap does not affect the immune path (arch fallback / diff critical tier / memory markdown fallback).

---

## Architecture

### 1. `architecture_slice.py`

Add a helper:

```python
def _get_architecture_max_tokens(cfg: dict) -> int | None:
    """Return max_tokens from env var or config; None = no cap."""
    env_val = os.environ.get("TOKEN_OPTIMIZATION_ARCHITECTURE_MAX_TOKENS", "").strip()
    if env_val:
        try:
            return int(env_val)
        except ValueError:
            pass
    try:
        return int(cfg.get("token_optimization", {}).get("architecture", {}).get("max_tokens", 0)) or None
    except (TypeError, ValueError):
        return None
```

In `slice_architecture()`, **after** building `included_sections` (step 5, inside the non-fallback branch), apply the cap via section exclusion before assembling `body`:

```python
max_tokens = _get_architecture_max_tokens(cfg)
if max_tokens and included_sections:
    while len(included_sections) > 1:
        candidate = "".join(all_sections[s] for s in included_sections)
        if te.estimate_tokens(candidate) <= max_tokens:
            break
        dropped = included_sections.pop()
        omitted_sections.insert(0, dropped)
```

**Cap-immune guarantee:** `_full_doc_result` is never modified and never calls `_get_architecture_max_tokens`. The safety fallback is structurally outside the cap path. When `arch_fallback=True`, `budget_enforce.py` does not export `TOKEN_OPTIMIZATION_ARCHITECTURE_MAX_TOKENS`, so the env var will be unset anyway — double protection.

---

### 2. `memory_retrieve.py`

Add a helper alongside `_is_memory_enabled()`:

```python
def _get_memory_max_tokens(clone_dir: str | None = None) -> int:
    """Return token budget from env var or config; default TOKEN_BUDGET_DEFAULT."""
    env_val = os.environ.get("TOKEN_OPTIMIZATION_MEMORY_MAX_TOKENS", "").strip()
    if env_val:
        try:
            return int(env_val)
        except ValueError:
            pass
    candidates = list(_MEMORY_CONFIG_PATHS)
    if clone_dir:
        candidates.insert(0, Path(clone_dir) / ".claude" / "skills" / "refinement" / "config.yaml")
    try:
        import yaml  # type: ignore[import]
        for path in candidates:
            try:
                with open(path, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                val = (data or {}).get("token_optimization", {}).get("memory", {}).get("max_tokens")
                if val is not None:
                    return int(val)
            except Exception:
                continue
    except Exception:
        pass
    return TOKEN_BUDGET_DEFAULT
```

In `format_index_output()`, replace the hardcoded `TOKEN_BUDGET_DEFAULT` reference with a call to `_get_memory_max_tokens(clone_dir)`, threading `clone_dir` through the call:

```python
effective_budget = _get_memory_max_tokens(clone_dir)
# replace TOKEN_BUDGET_DEFAULT with effective_budget in the cap check:
if len(selected) >= TOP_K_DEFAULT or (selected and token_total + token_cost > effective_budget):
```

**Cap-immune guarantee:** The markdown fallback path in `retrieve_memory()` calls `scan_markdown_files()` then `format_markdown_output()` — no cap applied there (existing behavior unchanged). The fail-open on any error is also preserved.

---

### 3. `diff_rank.py`

Extend `load_config()` to check env var after reading from config:

```python
def load_config(path: str) -> tuple:
    """Return (token_cap, score_floor, diff_enabled)."""
    try:
        import yaml
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
        # existing enabled-override logic unchanged
        env_val = os.environ.get("TOKEN_OPTIMIZATION_DIFF_ENABLED", "").strip().lower()
        ...
    except Exception:
        token_cap, score_floor = 6000, 5.0
        diff_enabled = True

    # env override for token_cap (checked after config, regardless of parse success)
    env_cap = os.environ.get("TOKEN_OPTIMIZATION_DIFF_MAX_REVIEW_TOKENS", "").strip()
    if env_cap:
        try:
            token_cap = int(env_cap)
        except ValueError:
            pass  # fail open: keep config-derived value

    return token_cap, score_floor, diff_enabled
```

**Cap-immune guarantee:** Critical-tier files are emitted by `_full(c, "critical")` which increments `critical_tokens` and never touches the `budget` counter. This is the existing invariant; no new code needed. The test just needs to verify it with an env cap set.

---

### 4. `comment_digest.py`

Add helper and truncation in `main()`:

```python
_COMMENTS_CONFIG_PATHS = [
    "/workspace/project/.claude/skills/refinement/config.yaml",
    "/opt/refinement-skills/config.yaml",
]
_COMMENTS_MAX_TOKENS_DEFAULT = 2000

def _get_comments_max_tokens() -> int:
    """Return max_tokens from env var or config; default 2000."""
    env_val = os.environ.get("TOKEN_OPTIMIZATION_COMMENTS_MAX_TOKENS", "").strip()
    if env_val:
        try:
            return int(env_val)
        except ValueError:
            pass
    for path in _COMMENTS_CONFIG_PATHS:
        try:
            import yaml  # type: ignore[import]
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            val = (data or {}).get("token_optimization", {}).get("comments", {}).get("max_tokens")
            if val is not None:
                return int(val)
        except Exception:
            continue
    return _COMMENTS_MAX_TOKENS_DEFAULT
```

In `main()`, after `build_digest()`:

```python
digest = build_digest(issue_data)
max_tokens = _get_comments_max_tokens()
char_limit = max_tokens * 4
if len(digest) > char_limit:
    dropped = len(digest) - char_limit
    digest = digest[:char_limit] + f"\n<!-- truncated: {dropped} chars dropped (cap={max_tokens} tokens) -->\n"
```

**No cap-immune carve-out** — comment_digest is not listed among the safety-immune sections. Simple character-level truncation is correct. `build_digest()` itself remains pure (no truncation logic inside it) so existing tests are unaffected.

---

## Alternatives considered

### A. Text truncation for `architecture_slice.py`
Rejected in Q&A: the slicer produces structured section-granular markdown. Truncating mid-string would produce a corrupt, half-finished section heading. Section exclusion (drop tail, keep head) is consistent with the "trim by dropping whole optimizable units" philosophy throughout this system and keeps `section_hashes` verifiable.

### B. Env-var only (no config read) for `comment_digest.py`
Rejected in Q&A: the issue explicitly requires "when unset, use the config value (current behavior)." A helper with config-fallback is the consistent contract across all four optimizers.

### C. Applying the cap inside `build_digest()` for `comment_digest.py`
Rejected: keeps the core function pure and untouched by enforcement concerns. Cap logic in `main()` keeps the test boundary clean.

---

## Test plan

### `architecture_slice.py`
- `test_slice_cap_env_override`: Set `TOKEN_OPTIMIZATION_ARCHITECTURE_MAX_TOKENS` to a value that forces exclusion of the last section in the backend component's section list. Assert omitted_sections contains the dropped section.
- `test_slice_cap_keeps_at_least_one_section`: Set cap to 1 token (impossibly tight). Assert included_sections has at least 1 entry.
- `test_slice_cap_immune_in_fallback`: Set cap to 100. Pass a safety-keyword label. Assert result.fallback=True and result.text contains all sections (cap not applied).
- `test_slice_cap_unset_uses_config`: No env var set. Set config max_tokens=999999. Assert no sections dropped.

### `memory_retrieve.py`
- `test_memory_cap_env_override`: Set `TOKEN_OPTIMIZATION_MEMORY_MAX_TOKENS` to 1 (forces entries dropped). Assert _cap_out["entries_dropped_by_cap"] > 0.
- `test_memory_cap_config_fallback`: No env var. Assert effective budget equals config value.
- `test_memory_cap_immune_on_error`: Simulate scan_index throwing OSError → fallback to scan_markdown_files. Assert output is non-empty and cap counters show fallback_used=True.

### `diff_rank.py`
- `test_diff_cap_env_override`: Set `TOKEN_OPTIMIZATION_DIFF_MAX_REVIEW_TOKENS` to a tight value. Build a diff with several high-tier files. Assert some are summarized (budget-exhausted).
- `test_diff_cap_critical_immune`: Set cap to 1 token. Build a diff with a critical-tier file (alembic/ path). Assert the critical file is always emitted in full.
- `test_diff_cap_config_fallback`: No env var. Config specifies 4000 tokens. Assert token_cap == 4000.

### `comment_digest.py`
- `test_comment_digest_cap_env_override`: Set `TOKEN_OPTIMIZATION_COMMENTS_MAX_TOKENS` to 10. Build a digest longer than 40 chars. Assert output contains the `<!-- truncated: ... -->` marker.
- `test_comment_digest_cap_no_truncation_under_limit`: Set cap to 99999. Assert output equals full digest.
- `test_comment_digest_cap_config_fallback`: No env var. Config specifies 500. Digest over 2000 chars. Assert truncation at 500*4 chars.

---

## Assumptions

- [ASSUMED] `budget_enforce.py` (T1) does not export `TOKEN_OPTIMIZATION_ARCHITECTURE_MAX_TOKENS` when `arch_fallback=True`. This is confirmed by T1's `_SLOTS` logic and `derive_caps()` exclusion — but if that contract ever changes, the architecture_slice safety guarantee relies on T1 not setting the var. The structural guard in `_full_doc_result` provides a second line of defense.
- [ASSUMED] `te.estimate_tokens()` (char ÷ 4) is the correct estimator for section-exclusion decisions in `architecture_slice.py`, matching how `budget_enforce.py` computed the derived cap.
- [ASSUMED] Comment digest truncation does not need to preserve the leading `<!-- comment-digest: cutoff=... -->` header under an extremely tight cap. No cap-immune carve-out is required for comment_digest per the design doc.

---

## Open questions (non-blocking)

- Should `architecture_slice.py` record the dropped section count in `SliceResult` for telemetry (T4)? Not required by T2 scope — `omitted_sections` already carries this signal.
- Should `memory_retrieve.py` expose `effective_budget` in `_cap_out` for T4 telemetry? Easy to add when T4 is implemented; not in T2 scope.
