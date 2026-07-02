# Plan: Phase 4 T2 — Optimizer `max_tokens` cap-override reads

**Date:** 2026-07-02
**Issue:** #715
**Spec:** `docs/superpowers/specs/2026-07-02-phase4-t2-optimizer-cap-override-design.md`
**Epic:** #713 (Phase 4 budget enforcement)
**Branch:** `refine/issue-715-phase-4-t2--optimizer-max-tokens-cap-ove`

---

## Goal

Add a `max_tokens` env-override read to each of the four Dark Factory optimizers so that
`budget_enforce.py` (T1) can hand a tighter cap at runtime. When unset, each optimizer
falls back to its config value (current behavior). All safety carve-outs remain structurally
cap-immune — no new bypass logic required.

---

## Architecture

Each optimizer gains an env-first/config-fallback/hardcoded-default helper following the
pattern established by the `enabled`-override in #673:

| Optimizer | Env var | Config key | Default |
|---|---|---|---|
| `architecture_slice.py` | `TOKEN_OPTIMIZATION_ARCHITECTURE_MAX_TOKENS` | `token_optimization.architecture.max_tokens` | `None` (no cap) |
| `memory_retrieve.py` | `TOKEN_OPTIMIZATION_MEMORY_MAX_TOKENS` | `token_optimization.memory.max_tokens` | `TOKEN_BUDGET_DEFAULT` (1500) |
| `diff_rank.py` | `TOKEN_OPTIMIZATION_DIFF_MAX_REVIEW_TOKENS` | `token_optimization.diff.max_review_tokens` | `6000` |
| `comment_digest.py` | `TOKEN_OPTIMIZATION_COMMENTS_MAX_TOKENS` | `token_optimization.comments.max_tokens` | `2000` |

Safety carve-outs:
- `architecture_slice.py`: `_full_doc_result` never calls `_get_architecture_max_tokens`; cap only applies inside the non-fallback branch
- `memory_retrieve.py`: markdown fallback path never calls `_get_memory_max_tokens`
- `diff_rank.py`: critical-tier files call `_full(c, "critical")` which does not touch `budget`

---

## Tech Stack

- Python 3.11 (stdlib only for all helpers)
- pytest with `monkeypatch.setenv()` for env var isolation, `tmp_path` for config fixtures
- No new dependencies

---

## File Structure

| File | Change |
|---|---|
| `dark-factory/scripts/architecture_slice.py` | Add `_get_architecture_max_tokens(cfg)` helper; add cap loop in `slice_architecture()` |
| `dark-factory/scripts/memory_retrieve.py` | Add `_get_memory_max_tokens(clone_dir)` helper; replace `TOKEN_BUDGET_DEFAULT` in `format_index_output()` |
| `dark-factory/scripts/diff_rank.py` | Restructure `load_config()` to add env override for `token_cap` after try/except |
| `dark-factory/scripts/comment_digest.py` | Add `_get_comments_max_tokens()` helper + char-level truncation in `main()` |
| `dark-factory/tests/test_architecture_slice.py` | Add 4 cap-override tests |
| `dark-factory/tests/test_memory_retrieve.py` | Add 3 cap-override tests |
| `dark-factory/tests/test_diff_rank.py` | Add 3 cap-override tests |
| `dark-factory/tests/test_comment_digest.py` | Add 3 cap-override tests |

---

## Task 1: `architecture_slice.py` — section-exclusion cap

**Files:** `dark-factory/scripts/architecture_slice.py`, `dark-factory/tests/test_architecture_slice.py`

### Step 1.1 — Write failing tests

Append to `dark-factory/tests/test_architecture_slice.py`:

```python
# ── Cap-override tests (Task 1, Issue #715) ──────────────────────────────────

def test_slice_cap_env_override_drops_tail_section(arch_file, tmp_path, monkeypatch):
    """TOKEN_OPTIMIZATION_ARCHITECTURE_MAX_TOKENS forces exclusion of the last section."""
    clone_dir = make_config(tmp_path)
    # "backend" wants: Scan Execution Flow, Backend Module Map, Error Tracking System,
    # Celery Task Architecture, Test Architecture.
    # Each section content is ~40 chars (from _ARCH_CONTENT above).
    # Set cap to ~1 token (=4 chars) to force all but the first section to be dropped.
    monkeypatch.setenv("TOKEN_OPTIMIZATION_ARCHITECTURE_MAX_TOKENS", "1")
    result = aslice.slice_architecture(
        arch_path=arch_file, scenario="implement",
        spec_component="backend", clone_dir=clone_dir,
    )
    assert not result.fallback
    # With a 1-token cap, only 1 section survives (the keep-at-least-one guarantee)
    assert len(result.included_sections) == 1
    assert len(result.omitted_sections) > 0


def test_slice_cap_keeps_at_least_one_section(arch_file, tmp_path, monkeypatch):
    """Cap of 1 token triggers the loop but the >1 floor leaves exactly 1 section."""
    clone_dir = make_config(tmp_path)
    # Use "1" (truthy, triggers the loop); sections each have ~10 tokens, so all
    # but the first are popped, but the while-guard stops at len==1.
    monkeypatch.setenv("TOKEN_OPTIMIZATION_ARCHITECTURE_MAX_TOKENS", "1")
    result = aslice.slice_architecture(
        arch_path=arch_file, scenario="implement",
        spec_component="backend", clone_dir=clone_dir,
    )
    assert not result.fallback
    # The floor guard (len > 1) ensures at least 1 section always remains
    assert len(result.included_sections) >= 1


def test_slice_cap_immune_in_fallback(arch_file, tmp_path, monkeypatch):
    """Cap is NOT applied when safety fallback fires — full doc is returned."""
    clone_dir = make_config(tmp_path)
    monkeypatch.setenv("TOKEN_OPTIMIZATION_ARCHITECTURE_MAX_TOKENS", "1")
    result = aslice.slice_architecture(
        arch_path=arch_file, scenario="implement",
        spec_component="backend",
        labels=["migration"],  # safety keyword → triggers fallback
        clone_dir=clone_dir,
    )
    assert result.fallback is True
    # All sections are present — cap did not reduce them
    for sec in ["Scan Execution Flow", "Backend Module Map", "Test Architecture"]:
        assert sec in result.included_sections


def test_slice_cap_unset_uses_config_no_drop(arch_file, tmp_path):
    """When env var is unset and config has a large cap, no sections are dropped."""
    import textwrap
    content = textwrap.dedent("""\
        dispatch_ceiling:
          keywords: "migration|migrate|performance|perf|architectur|refactor"
        epic_autopilot:
          sensitive_keywords: "trading|ibkr"
          hard_exclude_paths:
            - "app/services/trading"
        token_optimization:
          architecture:
            max_tokens: 999999
    """)
    p = tmp_path / ".claude" / "skills" / "refinement" / "config.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    result = aslice.slice_architecture(
        arch_path=arch_file, scenario="implement",
        spec_component="backend", clone_dir=str(tmp_path),
    )
    assert not result.fallback
    assert set(result.included_sections) == set(aslice.COMPONENT_SECTION_MAP["backend"])
```

### Step 1.2 — Verify tests fail

```bash
python3 -m pytest dark-factory/tests/test_architecture_slice.py \
    -k "cap" -x --tb=short -q
```

Expected: 4 FAILED (AttributeError or AssertionError — `_get_architecture_max_tokens` doesn't exist yet).

### Step 1.3 — Implement: add helper to `architecture_slice.py`

Insert after `_is_architecture_enabled()` (after line 163, before the section parsing block):

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

### Step 1.4 — Implement: add cap loop in `slice_architecture()`

In `slice_architecture()`, the "Build slice" block (step 5) currently reads:

```python
    # 5. Build slice
    included_sections = [s for s in wanted if s in all_sections]
    omitted_sections = [s for s in all_section_names if s not in included_sections]

    if not included_sections:
        return _full_doc_result(arch_path, all_sections, all_section_names,
                                scenario, component, "no_sections_matched")

    section_hashes = {s: te.hash_text(all_sections[s]) for s in included_sections}
```

Replace with:

```python
    # 5. Build slice
    included_sections = [s for s in wanted if s in all_sections]
    omitted_sections = [s for s in all_section_names if s not in included_sections]

    if not included_sections:
        return _full_doc_result(arch_path, all_sections, all_section_names,
                                scenario, component, "no_sections_matched")

    # Apply token cap via section exclusion (drop lowest-priority tail sections first)
    max_tokens = _get_architecture_max_tokens(cfg)
    if max_tokens and included_sections:
        while len(included_sections) > 1:
            candidate = "".join(all_sections[s] for s in included_sections)
            if te.estimate_tokens(candidate) <= max_tokens:
                break
            dropped = included_sections.pop()
            omitted_sections.insert(0, dropped)

    section_hashes = {s: te.hash_text(all_sections[s]) for s in included_sections}
```

### Step 1.5 — Verify tests pass

```bash
python3 -m pytest dark-factory/tests/test_architecture_slice.py \
    -k "cap" -x --tb=short -q
```

Expected output:
```
4 passed in X.XXs
```

### Step 1.6 — Run full architecture_slice suite

```bash
python3 -m pytest dark-factory/tests/test_architecture_slice.py -x --tb=short -q
```

Expected: all existing tests pass (no regressions).

### Step 1.7 — Commit

```bash
git add dark-factory/scripts/architecture_slice.py \
        dark-factory/tests/test_architecture_slice.py
git commit -m "feat(#715): architecture_slice — TOKEN_OPTIMIZATION_ARCHITECTURE_MAX_TOKENS cap-override via section exclusion"
```

---

## Task 2: `memory_retrieve.py` — token budget override

**Files:** `dark-factory/scripts/memory_retrieve.py`, `dark-factory/tests/test_memory_retrieve.py`

### Step 2.1 — Write failing tests

Append to `dark-factory/tests/test_memory_retrieve.py`:

```python
# ── Cap-override tests (Task 2, Issue #715) ──────────────────────────────────

class TestMemoryCapOverride:
    """Tests for _get_memory_max_tokens and format_index_output token-cap override."""

    def _make_candidates(self, n=5, tokens_each=200):
        """Return n fake candidates, each ~tokens_each tokens of text."""
        return [
            {
                "source_file": "codebase-patterns.md",
                "text": "- [PATTERN] " + ("x" * (tokens_each * 4 - 12)),
                "specificity": 0,
                "created_at": f"2026-01-0{i+1}",
            }
            for i in range(n)
        ]

    def test_env_override_honored(self, monkeypatch):
        """TOKEN_OPTIMIZATION_MEMORY_MAX_TOKENS=1 forces all-but-first entry dropped."""
        monkeypatch.setenv("TOKEN_OPTIMIZATION_MEMORY_MAX_TOKENS", "1")
        candidates = self._make_candidates(n=3, tokens_each=200)
        cap_out = {}
        mr.format_index_output(candidates, _cap_out=cap_out)
        assert cap_out["entries_dropped_by_cap"] > 0

    def test_config_fallback_when_env_unset(self, tmp_path, monkeypatch):
        """When env var is not set, effective budget equals config value."""
        monkeypatch.delenv("TOKEN_OPTIMIZATION_MEMORY_MAX_TOKENS", raising=False)
        # Write config with max_tokens=5000 (large enough to hold all candidates)
        config_path = tmp_path / ".claude" / "skills" / "refinement" / "config.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            "token_optimization:\n  memory:\n    max_tokens: 5000\n"
        )
        candidates = self._make_candidates(n=3, tokens_each=200)
        cap_out = {}
        mr.format_index_output(candidates, _cap_out=cap_out, clone_dir=str(tmp_path))
        # With 5000 token budget and 3 * 200-token entries (600 total), none should be dropped
        assert cap_out["entries_dropped_by_cap"] == 0

    def test_fallback_path_cap_immune(self, tmp_path, monkeypatch):
        """When index scan raises OSError, markdown fallback runs; _cap_out shows fallback_used=True."""
        monkeypatch.setenv("TOKEN_OPTIMIZATION_MEMORY_MAX_TOKENS", "1")
        memory_dir = tmp_path / ".archon" / "memory"
        memory_dir.mkdir(parents=True)
        # Create index.jsonl so the index path is tried, then create a .md fallback file
        (memory_dir / "index.jsonl").write_text("{invalid json\n")
        (memory_dir / "codebase-patterns.md").write_text(
            "- [PATTERN] Something useful here\n"
        )
        cap_out = {}
        output = mr.retrieve_memory(
            str(memory_dir), "plan", [], _cap_out=cap_out
        )
        assert cap_out.get("fallback_used") is True
        assert output  # non-empty — cap did not suppress fallback output
```

### Step 2.2 — Verify tests fail

```bash
python3 -m pytest dark-factory/tests/test_memory_retrieve.py \
    -k "CapOverride" -x --tb=short -q
```

Expected: 3 FAILED (the helper doesn't exist yet; `TOKEN_BUDGET_DEFAULT` is hardcoded).

### Step 2.3 — Implement: add `_get_memory_max_tokens` helper to `memory_retrieve.py`

Insert after `_is_memory_enabled()` (after line 122):

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

### Step 2.4 — Implement: replace `TOKEN_BUDGET_DEFAULT` in `format_index_output()`

In `format_index_output()`, the function signature is:
```python
def format_index_output(candidates, labels=None, _cap_out=None, config_path=None, clone_dir=None):
```

At the start of the function body (after `labels = labels or []` and `memory_enabled = _is_memory_enabled(clone_dir)`), add:

```python
    effective_budget = _get_memory_max_tokens(clone_dir)
```

Then replace the two occurrences of `TOKEN_BUDGET_DEFAULT` in the cap-check block:

Old (lines 390–391):
```python
            if len(selected) >= TOP_K_DEFAULT or (selected and token_total + token_cost > TOKEN_BUDGET_DEFAULT):
                if selected and token_total + token_cost > TOKEN_BUDGET_DEFAULT and len(selected) < TOP_K_DEFAULT:
```

New:
```python
            if len(selected) >= TOP_K_DEFAULT or (selected and token_total + token_cost > effective_budget):
                if selected and token_total + token_cost > effective_budget and len(selected) < TOP_K_DEFAULT:
```

### Step 2.5 — Verify tests pass

```bash
python3 -m pytest dark-factory/tests/test_memory_retrieve.py \
    -k "CapOverride" -x --tb=short -q
```

Expected output:
```
3 passed in X.XXs
```

### Step 2.6 — Run full memory_retrieve suite

```bash
python3 -m pytest dark-factory/tests/test_memory_retrieve.py -x --tb=short -q
```

Expected: all existing tests pass.

### Step 2.7 — Commit

```bash
git add dark-factory/scripts/memory_retrieve.py \
        dark-factory/tests/test_memory_retrieve.py
git commit -m "feat(#715): memory_retrieve — TOKEN_OPTIMIZATION_MEMORY_MAX_TOKENS cap-override in format_index_output"
```

---

## Task 3: `diff_rank.py` — token cap override in `load_config()`

**Files:** `dark-factory/scripts/diff_rank.py`, `dark-factory/tests/test_diff_rank.py`

### Step 3.1 — Write failing tests

Append to `dark-factory/tests/test_diff_rank.py`:

```python
# ── Cap-override tests (Task 3, Issue #715) ──────────────────────────────────

class TestDiffCapOverride:
    """Tests for TOKEN_OPTIMIZATION_DIFF_MAX_REVIEW_TOKENS env override in load_config()."""

    def _make_tmp_config(self, tmp_path, token_cap=6000, score_floor=5.0):
        content = {
            "token_optimization": {"diff": {"max_review_tokens": token_cap}},
            "blast_radius": {"hotspot_score_floor": score_floor},
        }
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump(content))
        return str(p)

    def test_env_override_honored(self, tmp_path, monkeypatch):
        """TOKEN_OPTIMIZATION_DIFF_MAX_REVIEW_TOKENS overrides the config value."""
        monkeypatch.setenv("TOKEN_OPTIMIZATION_DIFF_MAX_REVIEW_TOKENS", "999")
        cfg = self._make_tmp_config(tmp_path, token_cap=6000)
        token_cap, _, _ = dr.load_config(cfg)
        assert token_cap == 999

    def test_config_fallback_when_env_unset(self, tmp_path, monkeypatch):
        """When env var is unset, token_cap comes from config."""
        monkeypatch.delenv("TOKEN_OPTIMIZATION_DIFF_MAX_REVIEW_TOKENS", raising=False)
        cfg = self._make_tmp_config(tmp_path, token_cap=4000)
        token_cap, _, _ = dr.load_config(cfg)
        assert token_cap == 4000

    def test_critical_tier_files_cap_immune(self):
        """With a 1-token cap passed directly, critical-tier files (alembic/) are still emitted in full."""
        # Note: this test verifies the structural invariant in build_ranked_diff (critical
        # files bypass budget). env override coverage is already in test_env_override_honored.
        diff = (
            "diff --git a/alembic/versions/001_init.py b/alembic/versions/001_init.py\n"
            "index aaa..bbb 100644\n"
            "--- a/alembic/versions/001_init.py\n"
            "+++ b/alembic/versions/001_init.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "+new\n"
            "diff --git a/backend/app/routers/scanner.py b/backend/app/routers/scanner.py\n"
            "index ccc..ddd 100644\n"
            "--- a/backend/app/routers/scanner.py\n"
            "+++ b/backend/app/routers/scanner.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "+new\n"
        )
        ranked, info = dr.build_ranked_diff(
            diff_text=diff,
            token_cap=1,  # extremely tight
            hotspot_paths=set(),
            hotspot_scores={},
            spec_names=set(),
            score_floor=5.0,
        )
        # Critical file (alembic/) must be in output as "full", not summarized
        critical_record = next(
            r for r in info["files"] if "alembic" in r["path"]
        )
        assert critical_record["included"] == "full"
        assert critical_record["risk_class"] == "critical"
        assert info["critical_tokens"] > 0
```

### Step 3.2 — Verify tests fail

```bash
python3 -m pytest dark-factory/tests/test_diff_rank.py \
    -k "DiffCapOverride" -x --tb=short -q
```

Expected: `test_env_override_honored` and `test_config_fallback_when_env_unset` FAILED (env override not wired yet). `test_critical_tier_files_cap_immune` may pass already (structural guarantee exists).

### Step 3.3 — Implement: restructure `load_config()` in `diff_rank.py`

Replace the existing `load_config()` function body:

Old:
```python
def load_config(path: str) -> tuple:
    """Return (token_cap: int, score_floor: float, diff_enabled: bool) from config yaml.
    ...
    """
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
        env_val = os.environ.get("TOKEN_OPTIMIZATION_DIFF_ENABLED", "").strip().lower()
        if env_val in ("false", "0", "no"):
            diff_enabled = False
        elif env_val in ("true", "1", "yes"):
            diff_enabled = True
        else:
            cfg_val = data.get("token_optimization", {}).get("diff", {}).get("enabled")
            diff_enabled = cfg_val is not False
        return token_cap, score_floor, diff_enabled
    except Exception:
        return 6000, 5.0, True
```

New:
```python
def load_config(path: str) -> tuple:
    """Return (token_cap: int, score_floor: float, diff_enabled: bool) from config yaml.

    Keys read:
      token_optimization.diff.max_review_tokens  → token_cap    (default 6000)
      blast_radius.hotspot_score_floor           → score_floor  (default 5.0)
      token_optimization.diff.enabled            → diff_enabled (default True)

    When diff_enabled is False, build_ranked_diff() emits the full diff without
    ranking or truncation. The env var TOKEN_OPTIMIZATION_DIFF_ENABLED overrides
    the config value; missing/unknown values default to True (fail-safe).
    TOKEN_OPTIMIZATION_DIFF_MAX_REVIEW_TOKENS overrides token_cap (checked after
    config parse, so it applies regardless of parse success — fail-open).
    """
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
        env_val = os.environ.get("TOKEN_OPTIMIZATION_DIFF_ENABLED", "").strip().lower()
        if env_val in ("false", "0", "no"):
            diff_enabled = False
        elif env_val in ("true", "1", "yes"):
            diff_enabled = True
        else:
            cfg_val = data.get("token_optimization", {}).get("diff", {}).get("enabled")
            diff_enabled = cfg_val is not False
    except Exception:
        token_cap, score_floor = 6000, 5.0
        diff_enabled = True

    # env override for token_cap — applied after config parse, regardless of parse success
    env_cap = os.environ.get("TOKEN_OPTIMIZATION_DIFF_MAX_REVIEW_TOKENS", "").strip()
    if env_cap:
        try:
            token_cap = int(env_cap)
        except ValueError:
            pass  # fail open: keep config-derived or default value

    return token_cap, score_floor, diff_enabled
```

### Step 3.4 — Verify tests pass

```bash
python3 -m pytest dark-factory/tests/test_diff_rank.py \
    -k "DiffCapOverride" -x --tb=short -q
```

Expected output:
```
3 passed in X.XXs
```

### Step 3.5 — Run full diff_rank suite

```bash
python3 -m pytest dark-factory/tests/test_diff_rank.py -x --tb=short -q
```

Expected: all existing tests pass.

### Step 3.6 — Commit

```bash
git add dark-factory/scripts/diff_rank.py \
        dark-factory/tests/test_diff_rank.py
git commit -m "feat(#715): diff_rank — TOKEN_OPTIMIZATION_DIFF_MAX_REVIEW_TOKENS cap-override in load_config"
```

---

## Task 4: `comment_digest.py` — post-digest character truncation

**Files:** `dark-factory/scripts/comment_digest.py`, `dark-factory/tests/test_comment_digest.py`

### Step 4.1 — Write failing tests

Append to `dark-factory/tests/test_comment_digest.py`:

```python
# ── Cap-override tests (Task 4, Issue #715) ──────────────────────────────────

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def _human_issue_data(body: str = "human feedback " * 20) -> dict:
    """Build issue_data with a factory boundary followed by one human comment."""
    return {
        "comments": [
            {
                "body": "---\n*Posted by MarketHawk Dark Factory*",
                "author": {"login": "bot"},
                "createdAt": "2026-01-01T00:00:00Z",
            },
            {
                "body": body,
                "author": {"login": "user"},
                "createdAt": "2026-01-02T00:00:00Z",
            },
        ],
        "pr_reviews": {},
        "pr_inline_comments": [],
    }


def test_comment_digest_cap_env_override_truncates(monkeypatch, tmp_path):
    """main() with TOKEN_OPTIMIZATION_COMMENTS_MAX_TOKENS=10 writes truncation marker to out file."""
    monkeypatch.setenv("TOKEN_OPTIMIZATION_COMMENTS_MAX_TOKENS", "10")
    issue_json = tmp_path / "issue.json"
    out_file = tmp_path / "digest.md"
    issue_json.write_text(json.dumps(_human_issue_data(body="x" * 200)))
    with patch.object(sys, "argv", ["comment_digest.py", "--issue-json", str(issue_json), "--out", str(out_file)]):
        cd.main()
    result = out_file.read_text()
    assert "<!-- truncated:" in result
    assert "chars dropped" in result


def test_comment_digest_cap_no_truncation_under_limit(monkeypatch, tmp_path):
    """main() with a very large cap writes the full digest without a truncation marker."""
    monkeypatch.setenv("TOKEN_OPTIMIZATION_COMMENTS_MAX_TOKENS", "99999")
    issue_json = tmp_path / "issue.json"
    out_file = tmp_path / "digest.md"
    issue_data = _human_issue_data(body="short feedback")
    issue_json.write_text(json.dumps(issue_data))
    with patch.object(sys, "argv", ["comment_digest.py", "--issue-json", str(issue_json), "--out", str(out_file)]):
        cd.main()
    result = out_file.read_text()
    assert "<!-- truncated:" not in result
    # Content matches what build_digest returns directly
    assert cd.build_digest(issue_data) == result


def test_comment_digest_cap_config_fallback(monkeypatch, tmp_path):
    """When env var is unset, _get_comments_max_tokens() reads cap from config."""
    monkeypatch.delenv("TOKEN_OPTIMIZATION_COMMENTS_MAX_TOKENS", raising=False)
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("token_optimization:\n  comments:\n    max_tokens: 500\n")
    monkeypatch.setattr(cd, "_COMMENTS_CONFIG_PATHS", [str(cfg_path)])
    assert cd._get_comments_max_tokens() == 500
```

### Step 4.2 — Verify tests fail

```bash
python3 -m pytest dark-factory/tests/test_comment_digest.py \
    -k "cap" -x --tb=short -q
```

Expected: 3 FAILED (AttributeError — `_COMMENTS_CONFIG_PATHS` and `_get_comments_max_tokens` don't exist).

### Step 4.3 — Implement: add config paths, default, and helper to `comment_digest.py`

After `_matched_marker` (after line 31, before `_feedback_sections`), insert:

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

### Step 4.4 — Implement: add truncation in `main()` in `comment_digest.py`

In `main()`, the current code after `build_digest()` is:

```python
    digest = build_digest(issue_data)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(digest)
```

Replace with:

```python
    digest = build_digest(issue_data)
    max_tokens = _get_comments_max_tokens()
    char_limit = max_tokens * 4
    if len(digest) > char_limit:
        dropped = len(digest) - char_limit
        digest = digest[:char_limit] + f"\n<!-- truncated: {dropped} chars dropped (cap={max_tokens} tokens) -->\n"
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(digest)
```

### Step 4.5 — Verify tests pass

```bash
python3 -m pytest dark-factory/tests/test_comment_digest.py \
    -k "cap" -x --tb=short -q
```

Expected output:
```
3 passed in X.XXs
```

### Step 4.6 — Run full comment_digest suite

```bash
python3 -m pytest dark-factory/tests/test_comment_digest.py -x --tb=short -q
```

Expected: all existing tests pass.

### Step 4.7 — Commit

```bash
git add dark-factory/scripts/comment_digest.py \
        dark-factory/tests/test_comment_digest.py
git commit -m "feat(#715): comment_digest — TOKEN_OPTIMIZATION_COMMENTS_MAX_TOKENS cap-override with post-digest truncation"
```

---

## Task 5: Full regression sweep

### Step 5.1 — Run the complete dark-factory test suite

```bash
python3 -m pytest dark-factory/tests/ -x --tb=short -q
```

Expected: all tests pass (no regressions across all four optimizers and any cross-cutting tests).

### Step 5.2 — Smoke-test env-override wiring end-to-end

Verify that setting the env var and calling each optimizer's CLI produces truncated output:

```bash
# architecture_slice: 1-token cap forces minimal slice
TOKEN_OPTIMIZATION_ARCHITECTURE_MAX_TOKENS=1 \
  python3 dark-factory/scripts/architecture_slice.py \
    --arch-file ARCHITECTURE.md \
    --scenario implement \
    --spec-component backend \
  | grep "omitted:"
# Expected: "omitted:" line lists multiple dropped sections

# diff_rank: 1-token cap, verify token_cap override in sidecar
mkdir -p /tmp/test-artifacts
TOKEN_OPTIMIZATION_DIFF_MAX_REVIEW_TOKENS=1 \
  python3 dark-factory/scripts/diff_rank.py \
    --diff /dev/stdin \
    --artifacts-dir /tmp/test-artifacts \
    --config .claude/skills/refinement/config.yaml \
  <<< "" && python3 -c "import json; d=json.load(open('/tmp/test-artifacts/diff-ranking.json')); print('token_cap:', d['token_cap'])"
# Expected: token_cap: 1
```

### Step 5.3 — Commit smoke results (no code change, just verify before final push)

No commit needed — smoke test is verification only. Proceed to branch push and PR.

---

## Acceptance Criteria

- [ ] `_get_architecture_max_tokens(cfg)` added to `architecture_slice.py`; cap loop in `slice_architecture()` drops tail sections until `te.estimate_tokens(candidate) <= max_tokens` or only 1 section remains
- [ ] `_full_doc_result` never calls `_get_architecture_max_tokens` — structurally cap-immune
- [ ] `_get_memory_max_tokens(clone_dir)` added to `memory_retrieve.py`; `format_index_output()` uses it instead of `TOKEN_BUDGET_DEFAULT`
- [ ] Markdown fallback path in `retrieve_memory()` is unchanged — no cap applied there
- [ ] `load_config()` in `diff_rank.py` applies `TOKEN_OPTIMIZATION_DIFF_MAX_REVIEW_TOKENS` after the try/except block (fail-open on ValueError)
- [ ] Critical-tier files in `build_ranked_diff()` bypass `budget` counter — structurally cap-immune
- [ ] `_get_comments_max_tokens()` added to `comment_digest.py`; `main()` truncates after `build_digest()` with `<!-- truncated: N chars dropped (cap=M tokens) -->` marker
- [ ] `build_digest()` remains pure (no truncation inside it)
- [ ] 4 new tests for architecture_slice cap behavior
- [ ] 3 new tests for memory_retrieve cap behavior
- [ ] 3 new tests for diff_rank cap behavior
- [ ] 3 new tests for comment_digest cap behavior
- [ ] All existing tests in all four test files continue to pass
