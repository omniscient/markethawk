# Epic Autopilot — Broaden Reach Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Epic Autopilot actually advance work — stop accidental over-drops, advance size-L children, and start the next epic when its child pool is dry.

**Architecture:** Extends the existing pure-core + injected-IO module `dark-factory/scripts/factory_core/epic_autopilot.py` (three behaviour changes), raises the global factory dispatch ceiling in `scheduler.sh`, and adds an epic-starter stage. All pure logic stays unit-tested with no IO; the scheduler change is grep-tested; live adapters are exercised in manual validation.

**Tech Stack:** Python 3 (stdlib only), POSIX sh (`scheduler.sh`), `gh` CLI + GraphQL, `yq`, pytest, `claude -p` (Opus 4.8 reviewer).

## Global Constraints

- **Factory self-edit → human-implemented only.** Never auto-refine/implement this.
- **Baked files.** `epic_autopilot.py`, `cli.py`, `scheduler.sh` are baked into `markethawk-dark-factory:latest`. Changes deploy only after `docker compose build backlog-scheduler && docker compose up -d --force-recreate backlog-scheduler` (Task 8).
- **Fail-closed safety preserved.** Trading/auth keyword hits and declared exclude-path matches remain hard drops; Opus parse errors → HOLD; Opus defaults to HOLD when uncertain.
- **Backward-compatible signatures.** New parameters on existing pure functions are optional with defaults so the current test-suite calls keep compiling.
- **Run python tests:** `cd dark-factory && python -m pytest tests/test_epic_autopilot.py -v` (pure functions, no DB/network).
- **Run scheduler test:** `bash dark-factory/tests/test_scheduler_ceiling.sh`.

## File Structure

- `dark-factory/scripts/factory_core/epic_autopilot.py` — MODIFY. `hard_excluded`, `is_eligible`, `cached_verdict`/`record_verdict`, `build_review_prompt`, `run_once`, new `pick_next_epic`/`_priority_rank`/`_epic_excluded`/`_size_rank`/`_age_hours`; new `LiveIO.fetch_ready_epics`/`promote_epic`; `main_once` cfg assembly + outcome print.
- `dark-factory/tests/test_epic_autopilot.py` — MODIFY. Update ceiling/undeclared-scope tests; add TTL, keyword, `pick_next_epic`, and epic-starter tests.
- `dark-factory/scheduler.sh` — MODIFY. Raise dispatch ceiling (`get_size_label`, `is_above_ceiling`, `is_below_ceiling`), map `epic_started` → `DISPATCHED`, add `_set_cfg` for new knobs.
- `dark-factory/tests/test_scheduler_ceiling.sh` — CREATE. Grep-assert the ceiling + epic_started wiring.
- `.claude/skills/refinement/config.yaml` — MODIFY. New `epic_autopilot` knobs + ceiling comment.

---

### Task 1: Soft over-drops in `hard_excluded`

Undeclared scope stops being a hard drop; it flags the candidate so Opus is warned. A new `sensitive_keywords` pattern hard-drops trading/auth by title/body keyword even when scope is undeclared.

**Files:**
- Modify: `dark-factory/scripts/factory_core/epic_autopilot.py` (`hard_excluded`, ~lines 54-63)
- Test: `dark-factory/tests/test_epic_autopilot.py`

**Interfaces:**
- Produces: `hard_excluded(c: dict, exclude_paths: list, sensitive_keywords: str = "") -> (bool, str)`. Sets `c["scope_undeclared"] = True` when no paths are declared. Reasons: `"sensitive-keyword"`, an exclude-path string, `"undeclared-scope"` (now non-excluding), or `""`.

- [ ] **Step 1: Replace the two undeclared-scope tests with the new contract**

In `tests/test_epic_autopilot.py`, replace `test_hard_exclude_undeclared_scope_fails_closed` with:

```python
def test_undeclared_scope_is_soft_and_flags():
    cand = c(target_paths=[])
    ex, why = ap.hard_excluded(cand, ["app/core/auth"])
    assert not ex and why == "undeclared-scope"
    assert cand.get("scope_undeclared") is True


def test_sensitive_keyword_hard_drops_even_without_paths():
    cand = c(title="Live IBKR order path kill switch", body="", target_paths=[])
    ex, why = ap.hard_excluded(cand, ["app/core/auth"],
                               sensitive_keywords=r"trading|ibkr|order|jwt|/auth")
    assert ex and why == "sensitive-keyword"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd dark-factory && python -m pytest tests/test_epic_autopilot.py -k "undeclared or sensitive" -v`
Expected: FAIL (`test_undeclared_scope_is_soft_and_flags` asserts `not ex` but current code returns `ex=True`; `sensitive_keywords` is an unexpected kwarg).

- [ ] **Step 3: Rewrite `hard_excluded`**

Replace the function body (currently lines ~54-63) with:

```python
def hard_excluded(c: dict, exclude_paths: list, sensitive_keywords: str = ""):
    """Stage B — categorical exclusions. Returns (excluded: bool, reason: str).

    Trading/auth keywords in title/body hard-drop (fail-closed) even when scope is
    undeclared. A declared path matching an exclude prefix hard-drops. No declared
    paths is NOT a drop anymore — flag scope_undeclared so Opus is warned and leans HOLD.
    """
    if sensitive_keywords:
        text = f"{c.get('title', '')} {c.get('body', '')}".lower()
        if re.search(sensitive_keywords, text):
            return True, "sensitive-keyword"
    paths = c.get("target_paths") or []
    for p in paths:
        for ex in exclude_paths:
            if ex in p:
                return True, ex
    if not paths:
        c["scope_undeclared"] = True
        return False, "undeclared-scope"
    return False, ""
```

- [ ] **Step 4: Run the hard_excluded tests to verify they pass**

Run: `cd dark-factory && python -m pytest tests/test_epic_autopilot.py -k "exclude or undeclared or sensitive or security" -v`
Expected: PASS (incl. the still-valid `test_hard_exclude_factory_self`, `test_hard_exclude_auth`, `test_security_label_not_excluded`).

- [ ] **Step 5: Commit**

```bash
git add dark-factory/scripts/factory_core/epic_autopilot.py dark-factory/tests/test_epic_autopilot.py
git commit -m "feat(autopilot): undeclared-scope becomes a soft Opus concern; keyword fail-closed for trading/auth"
```

---

### Task 2: Size ceiling → XL-only in `is_eligible`

`is_eligible` should drop only `XL`; `L` and `M` become eligible (Opus weighs blast radius). Replaces the `(L, XL)` drop and the `M`+keyword drop.

**Files:**
- Modify: `dark-factory/scripts/factory_core/epic_autopilot.py` (`is_eligible`, ~lines 38-51; add `_size_rank`)
- Test: `dark-factory/tests/test_epic_autopilot.py`

**Interfaces:**
- Produces: `is_eligible(c: dict, opt_out_label: str, size_ceiling: str = "XL") -> (bool, str)`. Drops when the candidate size rank ≥ the `size_ceiling` rank. `_size_rank(s: str) -> int` maps S<M<L<XL (unknown/blank rank −1, i.e. below S).

- [ ] **Step 1: Update the ceiling tests to the new contract**

In `tests/test_epic_autopilot.py`, the helper passes `CEIL` as the third arg to `is_eligible` in several tests. Replace the affected tests (`test_eligible_happy`, `test_ineligible_opt_out`, `test_ineligible_already_direct_to_pr`, `test_ineligible_wrong_status`, `test_ineligible_above_ceiling_size_l`, `test_ineligible_m_with_ceiling_keyword`, `test_eligible_m_without_keyword`, `test_size_from_label_prefix`) with:

```python
def test_eligible_happy():
    ok, why = ap.is_eligible(c(), "no-autopilot")
    assert ok, why


def test_ineligible_opt_out():
    ok, _ = ap.is_eligible(c(labels=["ready-for-agent", "no-autopilot"]), "no-autopilot")
    assert not ok


def test_ineligible_already_direct_to_pr():
    ok, _ = ap.is_eligible(c(labels=["direct-to-pr"]), "no-autopilot")
    assert not ok


def test_ineligible_wrong_status():
    ok, _ = ap.is_eligible(c(status="Ready"), "no-autopilot")
    assert not ok


def test_size_l_now_eligible():
    ok, why = ap.is_eligible(c(size="L"), "no-autopilot")
    assert ok, why


def test_size_m_with_keyword_now_eligible():
    ok, why = ap.is_eligible(c(size="M", title="perf refactor of scanner"), "no-autopilot")
    assert ok, why


def test_size_xl_dropped():
    ok, why = ap.is_eligible(c(size="XL"), "no-autopilot")
    assert not ok and "above-ceiling" in why


def test_size_xl_from_label_prefix():
    ok, _ = ap.is_eligible(c(size=None, labels=["ready-for-agent", "size: XL"]), "no-autopilot")
    assert not ok
```

- [ ] **Step 2: Run to verify failures**

Run: `cd dark-factory && python -m pytest tests/test_epic_autopilot.py -k "eligib or size" -v`
Expected: FAIL (`size="L"` currently drops; `XL` currently slips through because the old code only special-cases L; `is_eligible` still expects a third positional `ceiling_keywords`).

- [ ] **Step 3: Rewrite `is_eligible` + add `_size_rank`**

Replace `is_eligible` (lines ~38-51) and add the rank helper just above it:

```python
_SIZE_ORDER = {"S": 0, "M": 1, "L": 2, "XL": 3}


def _size_rank(s: str) -> int:
    """Rank a size token; unknown/blank ranks below S so it is never above ceiling."""
    return _SIZE_ORDER.get((s or "").upper(), -1)


def is_eligible(c: dict, opt_out_label: str, size_ceiling: str = "XL"):
    """Stage A — structural eligibility. Returns (ok: bool, reason: str)."""
    labels = [label.lower() for label in c.get("labels", [])]
    if c.get("status") not in _GATED_STATUSES:
        return False, f"status={c.get('status')}"
    for blk in ("direct-to-pr", opt_out_label, "needs-discussion", "epic"):
        if blk.lower() in labels:
            return False, f"label:{blk}"
    size = _size(c) or ""
    if _size_rank(size) >= _size_rank(size_ceiling):
        return False, f"above-ceiling:size={size or '?'}"
    return True, ""
```

Note: `_size(c)` already reads a `size:`-prefixed label; it upper-cases the suffix so `"size: XL"` → `"XL"`.

- [ ] **Step 4: Run to verify passes**

Run: `cd dark-factory && python -m pytest tests/test_epic_autopilot.py -k "eligib or size" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dark-factory/scripts/factory_core/epic_autopilot.py dark-factory/tests/test_epic_autopilot.py
git commit -m "feat(autopilot): raise size ceiling to XL-only (L/M now eligible)"
```

---

### Task 3: HOLD verdict TTL

A cached `HOLD` expires after `hold_ttl_hours` so a one-off HOLD isn't permanent; ADVANCE stays terminal via the label. Backward-compatible: no timestamp args ⇒ old behaviour.

**Files:**
- Modify: `dark-factory/scripts/factory_core/epic_autopilot.py` (`cached_verdict`, `record_verdict`, ~lines 124-132; add `_age_hours`)
- Test: `dark-factory/tests/test_epic_autopilot.py`

**Interfaces:**
- Produces: `record_verdict(state, issue, spec_hash_, verdict, now_iso: str | None = None)` (stamps `ts` when `now_iso` given). `cached_verdict(state, issue, spec_hash_, now_iso: str | None = None, ttl_hours: float | None = None)` (returns `None` if expired). `_age_hours(ts_iso, now_iso) -> float`.

- [ ] **Step 1: Add the TTL tests**

Append to `tests/test_epic_autopilot.py`:

```python
def test_hold_ttl_expires_and_reenables_review():
    st = {}
    h = ap.spec_hash("spec A")
    ap.record_verdict(st, 402, h, "HOLD", now_iso="2026-06-20T00:00:00+00:00")
    # within TTL → still cached
    assert ap.cached_verdict(st, 402, h, "2026-06-20T10:00:00+00:00", 24) == "HOLD"
    # past TTL → cache miss (re-review)
    assert ap.cached_verdict(st, 402, h, "2026-06-21T01:00:00+00:00", 24) is None


def test_cached_verdict_backward_compatible_without_timestamps():
    st = {}
    h = ap.spec_hash("spec A")
    ap.record_verdict(st, 402, h, "HOLD")  # no now_iso
    assert ap.cached_verdict(st, 402, h) == "HOLD"  # no ttl args → unconditional
```

- [ ] **Step 2: Run to verify failure**

Run: `cd dark-factory && python -m pytest tests/test_epic_autopilot.py -k "ttl or backward_compatible" -v`
Expected: FAIL (`record_verdict`/`cached_verdict` reject the extra args).

- [ ] **Step 3: Implement the TTL**

Add `_age_hours` near the top imports area, and replace `cached_verdict`/`record_verdict`:

```python
def _age_hours(ts_iso: str, now_iso: str) -> float:
    from datetime import datetime
    try:
        return (datetime.fromisoformat(now_iso) - datetime.fromisoformat(ts_iso)).total_seconds() / 3600.0
    except Exception:
        return 0.0


def cached_verdict(state: dict, issue: int, spec_hash_: str, now_iso=None, ttl_hours=None):
    entry = (state.get("verdicts") or {}).get(str(issue))
    if not entry or entry.get("spec_hash") != spec_hash_:
        return None
    if ttl_hours and now_iso and entry.get("ts") and _age_hours(entry["ts"], now_iso) >= ttl_hours:
        return None
    return entry.get("verdict")


def record_verdict(state: dict, issue: int, spec_hash_: str, verdict: str, now_iso=None) -> None:
    entry = {"spec_hash": spec_hash_, "verdict": verdict}
    if now_iso:
        entry["ts"] = now_iso
    state.setdefault("verdicts", {})[str(issue)] = entry
```

- [ ] **Step 4: Run to verify passes (incl. the legacy cache tests)**

Run: `cd dark-factory && python -m pytest tests/test_epic_autopilot.py -k "ttl or verdict or cache or hold" -v`
Expected: PASS (`test_verdict_cache_roundtrip_and_hash_invalidation`, `test_run_skips_cached_hold` still green).

- [ ] **Step 5: Commit**

```bash
git add dark-factory/scripts/factory_core/epic_autopilot.py dark-factory/tests/test_epic_autopilot.py
git commit -m "feat(autopilot): expire cached HOLD verdicts after a TTL"
```

---

### Task 4: `pick_next_epic` selector

Pure selector for the epic-starter: choose the highest-priority unstarted epic, skipping hard-excluded categories (security/auth/trading/factory-self).

**Files:**
- Modify: `dark-factory/scripts/factory_core/epic_autopilot.py` (add functions near the pure-core block)
- Test: `dark-factory/tests/test_epic_autopilot.py`

**Interfaces:**
- Produces: `pick_next_epic(epics: list, exclude_pattern: str = _EPIC_EXCLUDE_RE) -> int | None`. `epics` items: `{number:int, title:str, labels:list[str], board_order:int}`. Orders by `_priority_rank(labels)` (must-have<should-have<other), then `board_order`, then `number`. Skips any epic whose title/labels match `exclude_pattern`.

- [ ] **Step 1: Add the selector tests**

Append to `tests/test_epic_autopilot.py`:

```python
def _e(number, title="epic", labels=None, board_order=0):
    return {"number": number, "title": title, "labels": labels or [], "board_order": board_order}


def test_pick_next_epic_skips_security_and_orders_by_priority():
    epics = [
        _e(373, "Authorization model", labels=["epic", "security", "should-have"], board_order=0),
        _e(450, "LLM narrative", labels=["epic", "should-have"], board_order=2),
        _e(483, "Signal replay engine", labels=["epic", "must-have"], board_order=1),
    ]
    assert ap.pick_next_epic(epics) == 483  # must-have, security #373 skipped


def test_pick_next_epic_board_order_tiebreak():
    epics = [
        _e(449, labels=["epic", "must-have"], board_order=5),
        _e(448, labels=["epic", "must-have"], board_order=3),
    ]
    assert ap.pick_next_epic(epics) == 448  # same priority → lower board_order wins


def test_pick_next_epic_none_when_all_excluded():
    epics = [_e(373, "auth", labels=["epic", "security"]),
             _e(601, "trading kill switch", labels=["epic"])]
    assert ap.pick_next_epic(epics) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd dark-factory && python -m pytest tests/test_epic_autopilot.py -k "pick_next_epic" -v`
Expected: FAIL (`AttributeError: module ... has no attribute 'pick_next_epic'`).

- [ ] **Step 3: Implement the selector**

Add to `epic_autopilot.py` after the verdict-cache helpers:

```python
_EPIC_EXCLUDE_RE = r"security|auth|authz|authn|trading|ibkr|dark.?factory|scheduler|factory.self"


def _priority_rank(labels: list) -> int:
    low = [label.lower() for label in labels]
    if any("must-have" in label for label in low):
        return 0
    if any("should-have" in label for label in low):
        return 1
    return 2


def _epic_excluded(e: dict, pattern: str) -> bool:
    hay = (e.get("title", "") + " " + " ".join(e.get("labels", []))).lower()
    return bool(re.search(pattern, hay))


def pick_next_epic(epics: list, exclude_pattern: str = _EPIC_EXCLUDE_RE):
    """Highest-priority unstarted epic, skipping hard-excluded categories. None if none."""
    elig = [e for e in epics if not _epic_excluded(e, exclude_pattern)]
    elig.sort(key=lambda e: (_priority_rank(e.get("labels", [])),
                             e.get("board_order", 10 ** 9), e["number"]))
    return elig[0]["number"] if elig else None
```

- [ ] **Step 4: Run to verify passes**

Run: `cd dark-factory && python -m pytest tests/test_epic_autopilot.py -k "pick_next_epic" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dark-factory/scripts/factory_core/epic_autopilot.py dark-factory/tests/test_epic_autopilot.py
git commit -m "feat(autopilot): pick_next_epic selector (priority order, skip sensitive epics)"
```

---

### Task 5: Orchestrator epic-starter + wired config

`run_once` threads timestamps into the cache, uses the new eligibility/exclusion signatures, warns Opus on undeclared scope, and — when the child pool is empty and `start_epics` is on — promotes the next epic. New outcome `epic_started`.

**Files:**
- Modify: `dark-factory/scripts/factory_core/epic_autopilot.py` (`build_review_prompt`, `run_once`)
- Test: `dark-factory/tests/test_epic_autopilot.py`

**Interfaces:**
- Consumes: `is_eligible(..., size_ceiling)`, `hard_excluded(..., sensitive_keywords)`, `cached_verdict(..., now_iso, ttl_hours)`, `record_verdict(..., now_iso)`, `pick_next_epic(...)`.
- Produces: `run_once(cfg, io, state, today, now_iso=None) -> {"outcome", "issue", "reason"}` where outcome ∈ {advanced, hold, epic_started, no_candidates, daily_cap_reached}. Epic-starter requires `cfg.get("start_epics")` truthy and `io.fetch_ready_epics()` / `io.promote_epic(n)`. `cfg` keys read with defaults: `size_ceiling="XL"`, `sensitive_keywords=""`, `hold_ttl_hours=None`, `start_epics=False`.

- [ ] **Step 1: Add the epic-starter orchestrator test**

Append to `tests/test_epic_autopilot.py`:

```python
class FakeEpicIO(FakeIO):
    def __init__(self, candidates, review_text, ready_epics):
        super().__init__(candidates, review_text)
        self._epics = ready_epics
        self.promoted = []

    def fetch_ready_epics(self):
        return self._epics

    def promote_epic(self, n):
        self.promoted.append(n)


def test_run_starts_epic_when_no_child_candidates():
    io = FakeEpicIO([], "x", [_e(483, labels=["epic", "must-have"])])
    cfg = dict(CFG, start_epics=True)
    out = ap.run_once(cfg, io, {}, "2026-06-20", now_iso="2026-06-20T00:00:00+00:00")
    assert out["outcome"] == "epic_started" and out["issue"] == 483
    assert io.promoted == [483]
    assert any(sev == "info" for sev, _ in io.notes)


def test_run_stuck_when_no_children_and_no_eligible_epic():
    io = FakeEpicIO([], "x", [_e(373, "auth", labels=["epic", "security"])])
    cfg = dict(CFG, start_epics=True)
    out = ap.run_once(cfg, io, {}, "2026-06-20")
    assert out["outcome"] == "no_candidates"
    assert io.promoted == []
    assert any(key == "autopilot-stuck" for _, key in io.notes)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd dark-factory && python -m pytest tests/test_epic_autopilot.py -k "starts_epic or stuck_when" -v`
Expected: FAIL (`run_once` has no epic-starter branch).

- [ ] **Step 3: Update `build_review_prompt` and `run_once`**

In `build_review_prompt`, surface the undeclared-scope flag so Opus is warned. Replace the whole function with:

```python
def build_review_prompt(c: dict) -> str:
    scope = ", ".join(c.get("target_paths") or []) or "(none declared)"
    warn = ("\nNOTE: file scope is UNDECLARED — treat trading/auth/factory-self risk as "
            "possible and lean HOLD unless the spec is clearly safe." if c.get("scope_undeclared") else "")
    return f"""You are a cautious senior engineer deciding whether a refined ticket is safe to
implement and merge AUTONOMOUSLY (adding the direct-to-pr label means it flows
spec->plan->implement->PR with NO further human gate before the PR opens).

Reply with ONLY a JSON object:
{{"decision":"ADVANCE|HOLD","risk":"low|medium|high","confidence":0.0-1.0,
  "reasons":[...],"concerns":[...]}}

ADVANCE only if the work is genuinely low-risk: small, well-scoped, reversible, good test
coverage in the spec/plan, low blast radius, and NOT touching automated trading,
authentication/authorization, or the factory/scheduler itself. If the spec is vague, an
empty-branch/no-op risk, or you are unsure -- choose HOLD.

Ticket #{c['number']}: {c['title']}
Labels: {', '.join(c.get('labels', []))}   Size: {c.get('size')}
Declared target files: {scope}{warn}

--- SPEC/PLAN ---
{(c.get('spec_text') or '')[:8000]}
"""
```

Then replace `run_once` with the version below (changes: `now_iso` param; new signatures; epic-starter branch):

```python
def run_once(cfg: dict, io, state: dict, today: str, now_iso=None) -> dict:
    """One starved-cycle pass. Returns {outcome, issue, reason}."""
    if daily_remaining(state, cfg["daily_cap"], today) <= 0:
        io.notify("Epic autopilot — daily cap reached",
                  f"Hit the daily cap of {cfg['daily_cap']} autonomous advances; paused until UTC reset. Review the backlog.",
                  "warning", "autopilot-cap")
        return {"outcome": "daily_cap_reached", "issue": None, "reason": "cap"}

    candidates = []
    for cand in io.fetch_candidates():
        ok, _ = is_eligible(cand, cfg["opt_out_label"], cfg.get("size_ceiling", "XL"))
        if not ok:
            continue
        excluded, _ = hard_excluded(cand, cfg["exclude_paths"], cfg.get("sensitive_keywords", ""))
        if excluded:
            continue
        if cached_verdict(state, cand["number"], spec_hash(cand.get("spec_text", "")),
                          now_iso, cfg.get("hold_ttl_hours")) == "HOLD":
            continue
        candidates.append(cand)

    if not candidates:
        if cfg.get("start_epics") and hasattr(io, "fetch_ready_epics"):
            epic_num = pick_next_epic(io.fetch_ready_epics())
            if epic_num is not None:
                io.promote_epic(epic_num)
                io.comment(epic_num,
                           "\U0001f916 **Epic Autopilot** — starting epic: promoted to In progress and "
                           "marked its open children ready-for-agent.\n\n---\n*Posted by MarketHawk Epic Autopilot*")
                io.notify(f"Autopilot starting epic #{epic_num}",
                          "Promoted to In progress; children marked ready-for-agent.", "info", None)
                record_advance(state, today)
                return {"outcome": "epic_started", "issue": epic_num, "reason": "promote"}
        io.notify("Epic autopilot — idle, nothing safe to advance",
                  "The factory is starved and the autopilot has no eligible low-risk ticket to advance. Human input needed.",
                  "warning", "autopilot-stuck")
        return {"outcome": "no_candidates", "issue": None, "reason": "empty"}

    cand = candidates[0]
    verdict = parse_verdict(io.review(build_review_prompt(cand), cfg["model"]))
    h = spec_hash(cand.get("spec_text", ""))
    if should_advance(verdict, cfg["confidence_floor"]):
        io.advance(cand["number"])
        reason = "; ".join(verdict.get("reasons", [])) or "low-risk"
        io.comment(cand["number"],
                   f"\U0001f916 **Epic Autopilot** — advancing (risk={verdict['risk']}, conf={verdict['confidence']}). "
                   f"Reason: {reason}\n\n---\n*Posted by MarketHawk Epic Autopilot*")
        io.notify(f"Autopilot advancing #{cand['number']}",
                  f"{cand['title']} — risk=low: {reason}", "info", None)
        record_advance(state, today)
        record_verdict(state, cand["number"], h, "ADVANCE", now_iso)
        return {"outcome": "advanced", "issue": cand["number"], "reason": reason}

    concerns = "; ".join(verdict.get("concerns", [])) or "not low-risk / low confidence"
    io.comment(cand["number"],
               f"\U0001f916 **Epic Autopilot** — parked (HOLD). {concerns}\n\n---\n*Posted by MarketHawk Epic Autopilot*")
    record_verdict(state, cand["number"], h, "HOLD", now_iso)
    return {"outcome": "hold", "issue": cand["number"], "reason": concerns}
```

- [ ] **Step 4: Run the full orchestrator suite**

Run: `cd dark-factory && python -m pytest tests/test_epic_autopilot.py -v`
Expected: PASS (all tasks 1-5, incl. legacy `test_run_advances_low_risk`, `test_run_holds_medium_risk`, `test_run_no_candidates_notifies_stuck`, `test_run_daily_cap_reached_notifies`, `test_run_skips_cached_hold`).

- [ ] **Step 5: Commit**

```bash
git add dark-factory/scripts/factory_core/epic_autopilot.py dark-factory/tests/test_epic_autopilot.py
git commit -m "feat(autopilot): epic-starter branch + undeclared-scope reviewer warning + TTL threading"
```

---

### Task 6: Live adapters, cfg assembly, and config knobs

Wire the new behaviour to the real world: GraphQL adapters to fetch Ready epics and promote one, cfg assembly from env/config in `main_once`, the new outcome line, and the `config.yaml` knobs. IO-heavy — exercised in manual validation (Task 8), no new unit tests (mirrors the existing "LiveIO not unit-tested" note).

**Files:**
- Modify: `dark-factory/scripts/factory_core/epic_autopilot.py` (`LiveIO`, `main_once`)
- Modify: `.claude/skills/refinement/config.yaml` (`epic_autopilot` section)

**Interfaces:**
- Consumes: `factory_core.board.set_board_status` (existing), `_in_progress_epics`-style GraphQL, `_sub_issue_numbers` pattern.
- Produces: `LiveIO.fetch_ready_epics() -> list[dict]`, `LiveIO.promote_epic(n: int) -> None`.

- [ ] **Step 1: Add `fetch_ready_epics` + `promote_epic` to `LiveIO`**

Add a `_ready_epics()` module helper near `_in_progress_epics` (it reuses the same project query, filtering Status == "Ready" + `epic` label, and reads the `priority:` label + board order):

```python
def _ready_epics() -> list:
    """Ready-column epics as [{number, title, labels, board_order}], board order preserved."""
    q = ('query { node(id: "%s") { ... on ProjectV2 { items(first:100) { nodes { '
         'fieldValueByName(name:"Status"){ ... on ProjectV2ItemFieldSingleSelectValue { name } } '
         'content { ... on Issue { number title labels(first:20){nodes{name}} } } } } } } }') % PROJECT_ID
    data = _gh_json(["api", "graphql", "-f", "query=" + q])
    if not data:
        return []
    out, order = [], 0
    for n in data.get("data", {}).get("node", {}).get("items", {}).get("nodes", []):
        content = n.get("content") or {}
        status = (n.get("fieldValueByName") or {}).get("name")
        labels = [x["name"] for x in (content.get("labels") or {}).get("nodes", [])]
        if content.get("number") and status == "Ready" and "epic" in labels:
            out.append({"number": content["number"], "title": content.get("title", ""),
                        "labels": labels, "board_order": order})
        order += 1
    return out


def _open_child_numbers(epic: int) -> list:
    """All OPEN sub-issue numbers of an epic (any label)."""
    q = ('query { repository(owner:"omniscient", name:"markethawk") { issue(number:%d) { '
         'subIssues(first:50) { nodes { number state } } } } }') % epic
    data = _gh_json(["api", "graphql", "-f", "query=" + q])
    if not data:
        return []
    return [s["number"] for s in
            data.get("data", {}).get("repository", {}).get("issue", {}).get("subIssues", {}).get("nodes", [])
            if s.get("state") == "OPEN"]
```

Then add these two methods to the `LiveIO` class:

```python
    def fetch_ready_epics(self) -> list:
        return _ready_epics()

    def promote_epic(self, epic: int) -> None:
        from factory_core.board import set_board_status
        set_board_status(epic, "In progress")
        for child in _open_child_numbers(epic):
            subprocess.run(["gh", "issue", "edit", str(child), "--repo", OWNER,
                            "--add-label", "ready-for-agent"], check=False)
```

- [ ] **Step 2: Assemble new cfg keys + outcome line in `main_once`**

In `main_once`, extend the `cfg = dict(...)` with the new knobs and update the final print:

```python
    cfg = dict(
        exclude_paths=_load_exclude_paths(),
        opt_out_label=os.environ.get("EPIC_AUTOPILOT_OPT_OUT_LABEL", "no-autopilot"),
        size_ceiling=os.environ.get("EPIC_AUTOPILOT_SIZE_CEILING", "XL"),
        sensitive_keywords=os.environ.get(
            "EPIC_AUTOPILOT_SENSITIVE_KEYWORDS",
            r"trading|ibkr|live order|notional|authentication|authorization|authn|authz|jwt|oauth|rbac|/auth"),
        hold_ttl_hours=float(os.environ.get("EPIC_AUTOPILOT_HOLD_TTL_HOURS", "24")),
        start_epics=os.environ.get("EPIC_AUTOPILOT_START_EPICS", "true").lower() == "true",
        confidence_floor=float(os.environ.get("EPIC_AUTOPILOT_CONFIDENCE_FLOOR", "0.7")),
        daily_cap=int(os.environ.get("EPIC_AUTOPILOT_DAILY_CAP", "5")),
        model=os.environ.get("EPIC_AUTOPILOT_MODEL", "claude-opus-4-8"))
    now_iso = datetime.now(timezone.utc).isoformat()
    out = run_once(cfg, LiveIO(cfg["model"]), state, today, now_iso)
```

(`from datetime import datetime, timezone` is already imported at the top of `main_once`.) Leave the final `print(f"autopilot={out['outcome']} issue=#{out['issue']}")` as-is — it already emits `autopilot=epic_started issue=#N`.

- [ ] **Step 3: Add the config knobs**

In `.claude/skills/refinement/config.yaml`, under `epic_autopilot:`, add after `confidence_floor`:

```yaml
  hold_ttl_hours: 24          # re-review a cached HOLD after this many hours. env EPIC_AUTOPILOT_HOLD_TTL_HOURS
  size_ceiling: XL            # drop only at/above this size (L/M now eligible). env EPIC_AUTOPILOT_SIZE_CEILING
  start_epics: true           # when no gated child is advanceable, promote the next Ready epic. env EPIC_AUTOPILOT_START_EPICS
  sensitive_keywords: "trading|ibkr|live order|notional|authentication|authorization|authn|authz|jwt|oauth|rbac|/auth"
```

- [ ] **Step 4: Byte-compile sanity check (no live calls)**

Run: `cd dark-factory && python -c "import sys; sys.path.insert(0,'scripts'); import factory_core.epic_autopilot as ap; print(hasattr(ap.LiveIO,'fetch_ready_epics'), hasattr(ap.LiveIO,'promote_epic'))"`
Expected: `True True`

- [ ] **Step 5: Commit**

```bash
git add dark-factory/scripts/factory_core/epic_autopilot.py .claude/skills/refinement/config.yaml
git commit -m "feat(autopilot): live Ready-epic adapters + cfg knobs (TTL, ceiling, epic-starter)"
```

---

### Task 7: Raise the global dispatch ceiling + map `epic_started`

Raise the factory's implement-side ceiling so `L` is below ceiling (only `XL` parks; `M`+keyword still escalates), recognise the `size: XL` label (currently unmatched), map the new `epic_started` outcome to a non-empty `DISPATCHED`, and export the new autopilot knobs.

**Files:**
- Modify: `dark-factory/scheduler.sh` (`get_size_label` ~236, `is_above_ceiling` ~242-251, `is_below_ceiling` ~259-263, Priority-6 `case` ~1109, `_set_cfg` block ~82-84)
- Create: `dark-factory/tests/test_scheduler_ceiling.sh`

- [ ] **Step 1: Write the grep-based scheduler test**

Create `dark-factory/tests/test_scheduler_ceiling.sh`:

```bash
#!/usr/bin/env bash
# Verifies scheduler.sh raised the dispatch ceiling to L and maps the epic_started outcome.
# Run: bash dark-factory/tests/test_scheduler_ceiling.sh
set -euo pipefail
sched="$(cd "$(dirname "$0")" && pwd)/../scheduler.sh"

# get_size_label must recognise XL (not just S/M/L)
grep -qE 'XL|xl' <(awk '/^get_size_label\(\)/{f=1} f{print} f&&/^}/{exit}' "$sched") \
  || { echo "FAIL: get_size_label does not recognise XL"; exit 1; }

# is_above_ceiling must park XL (not L)
block="$(awk '/^is_above_ceiling\(\)/{f=1} f{print} f&&/^}/{exit}' "$sched")"
echo "$block" | grep -qE 'XL\)' \
  || { echo "FAIL: is_above_ceiling does not special-case XL"; exit 1; }
echo "$block" | grep -qE '^[[:space:]]*L\)[[:space:]]*return 0' \
  && { echo "FAIL: is_above_ceiling still parks L unconditionally"; exit 1; }

# is_below_ceiling must treat L as below ceiling (timer-advance applies to S and L)
grep -qE 'S\|L\|""\)' <(awk '/^is_below_ceiling\(\)/{f=1} f{print} f&&/^}/{exit}' "$sched") \
  || { echo "FAIL: is_below_ceiling does not include L"; exit 1; }

# Priority-6 must map epic_started → DISPATCHED
grep -q 'autopilot=epic_started' "$sched" \
  || { echo "FAIL: scheduler does not map epic_started to DISPATCHED"; exit 1; }

echo "PASS"
```

- [ ] **Step 2: Run to verify failure**

Run: `bash dark-factory/tests/test_scheduler_ceiling.sh`
Expected: FAIL at the first assertion (`get_size_label` only matches `[SML]`).

- [ ] **Step 3: Edit `get_size_label` to recognise XL**

Replace line ~236:

```sh
  echo "$1" | jq -r '.labels[]?' 2>/dev/null | grep -oiE 'size: ?(xl|[sml])' | awk '{print toupper($NF)}' | head -1
```

- [ ] **Step 4: Edit `is_above_ceiling` — park XL, not L**

Replace the `case "$size"` block (~246-250):

```sh
  case "$size" in
    XL) return 0 ;;
    M) echo "$title" | grep -qiE "${ABOVE_CEILING_KEYWORDS}" && return 0 || return 1 ;;
    *) return 1 ;;
  esac
```

- [ ] **Step 5: Edit `is_below_ceiling` — include L**

Replace line ~262:

```sh
  case "$size" in S|L|"") return 0 ;; *) return 1 ;; esac
```

- [ ] **Step 6: Map `epic_started` in the Priority-6 case**

Replace line ~1109:

```sh
    case "$AP_OUT" in *"autopilot=advanced"*|*"autopilot=epic_started"*) DISPATCHED="$AP_OUT" ;; esac
```

- [ ] **Step 7: Export the new autopilot knobs**

After the existing `_set_cfg EPIC_AUTOPILOT_DAILY_CAP ...` line (~84), add:

```sh
  _set_cfg EPIC_AUTOPILOT_HOLD_TTL_HOURS    '.epic_autopilot.hold_ttl_hours'
  _set_cfg EPIC_AUTOPILOT_SIZE_CEILING      '.epic_autopilot.size_ceiling'
  _set_cfg EPIC_AUTOPILOT_START_EPICS       '.epic_autopilot.start_epics'
  _set_cfg EPIC_AUTOPILOT_SENSITIVE_KEYWORDS '.epic_autopilot.sensitive_keywords'
```

- [ ] **Step 8: Run both scheduler tests to verify pass**

Run: `bash dark-factory/tests/test_scheduler_ceiling.sh && bash dark-factory/tests/test_scheduler_autopilot_guard.sh`
Expected: `PASS` (both). The guard test still passes — the Priority-6 trigger guards are unchanged.

- [ ] **Step 9: Commit**

```bash
git add dark-factory/scheduler.sh dark-factory/tests/test_scheduler_ceiling.sh
git commit -m "feat(scheduler): raise dispatch ceiling to L (XL-only park), map epic_started, export autopilot knobs"
```

---

### Task 8: Deploy + manual validation

Rebuild the baked scheduler image, force-recreate, and validate on the live factory. Not a code task — a release gate.

**Files:** none (operational).

- [ ] **Step 1: Full python + bash test sweep**

Run: `cd dark-factory && python -m pytest tests/test_epic_autopilot.py -v && bash tests/test_scheduler_ceiling.sh && bash tests/test_scheduler_autopilot_guard.sh`
Expected: all green.

- [ ] **Step 2: Rebuild + recreate the baked scheduler**

```bash
docker compose build backlog-scheduler
docker compose up -d --force-recreate backlog-scheduler
```

- [ ] **Step 3: Confirm the image carries the change**

Run: `docker exec backlog-scheduler grep -c 'autopilot=epic_started' /opt/dark-factory/scheduler.sh` (adjust path to the baked location)
Expected: ≥ 1. Also `docker exec backlog-scheduler python3 -c "import sys;sys.path.insert(0,'<factory_core scripts path>');import factory_core.epic_autopilot as ap;print(ap.pick_next_epic([]))"` → `None`.

- [ ] **Step 4: Watch a live cycle**

Run: `docker logs backlog-scheduler --tail 40 -f | grep autopilot`
Expected (within a couple of cycles): an `autopilot=advanced issue=#…` for a now-eligible size-L data-quality child (e.g. #492/#494/#495), or — if the gated-child pool is dry — `autopilot=epic_started issue=#…` promoting the highest-priority non-security Ready epic (skipping #373). Confirm the matching GitHub comment + email/push notification.

- [ ] **Step 5: Push the branch + open the PR**

```bash
git push -u origin docs/autopilot-reach-and-main-red-autofix-specs
gh pr create --repo omniscient/markethawk --base main \
  --title "feat(autopilot): broaden reach (drain backlog, start next epic) — closes #590" \
  --body "Implements docs/superpowers/specs/2026-06-21-epic-autopilot-broaden-reach-design.md. Closes #590."
```

---

## Self-Review

**Spec coverage:**
- Soft over-drops (undeclared-scope → soft + keyword fail-closed) → Task 1. ✅
- HOLD-TTL → Task 3. ✅
- Size ceiling → L (autopilot) → Task 2; (factory global #339) → Task 7. ✅
- Broaden candidate source + epic-starter (promote & delegate, priority order, skip security) → Tasks 4-6. ✅
- Daily cap covers starts+advances → Task 5 (`record_advance` on the epic_started path). ✅
- Config knobs → Task 6; scheduler export → Task 7. ✅
- Unchanged safety (starved-only, main-green, Opus gate, opt-out, kill-switch, reversibility, notify) → trigger untouched (Task 7 guard test), Opus path intact (Task 5). ✅
- Validation (unit, scheduler, manual) → Tasks 1-5 (unit), 7 (scheduler), 8 (manual). ✅

**Placeholder scan:** No TBD/TODO; every code step shows complete code. (One operational path is environment-specific: Task 8 Step 3's baked `scheduler.sh` / `factory_core` paths inside the container — resolve them against the running image, e.g. `docker exec backlog-scheduler sh -c 'command -v scheduler.sh || find / -name scheduler.sh 2>/dev/null'`.)

**Type consistency:** `is_eligible(c, opt_out_label, size_ceiling="XL")`, `hard_excluded(c, exclude_paths, sensitive_keywords="")`, `cached_verdict(state, issue, spec_hash_, now_iso=None, ttl_hours=None)`, `record_verdict(..., now_iso=None)`, `pick_next_epic(epics, exclude_pattern=...)`, `run_once(cfg, io, state, today, now_iso=None)` — names/arities match across the orchestrator call sites in Task 5 and the LiveIO/cfg wiring in Task 6. Outcome string `epic_started` matches the scheduler `case` in Task 7.
