# Epic Autopilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Build constraint:** This modifies the scheduler/factory itself (a "factory self-edit"). It must be implemented by a HUMAN, never dispatched through the dark factory.

**Goal:** When the backlog scheduler is starved, review the refined, below-ceiling children of in-progress epics with Opus 4.8 and advance the low-risk ones via `direct-to-pr`, with email/push notifications and hard guardrails.

**Architecture:** A pure, dependency-injected Python core in `dark-factory/scripts/factory_core/epic_autopilot.py` (eligibility, hard-rule exclusions, verdict parsing, decision rule, daily cap, verdict cache — all unit-testable with no IO). A thin orchestrator wires GraphQL fetch, the `claude -p` Opus call, and gh/notify actions through injected callables. Exposed via `cli.py epic-autopilot --once` and called from a guarded **Priority 6** step in `scheduler.sh` that only runs when a poll dispatched nothing.

**Tech Stack:** Python 3.12 (stdlib only — argparse, json, subprocess, datetime, hashlib), bash (`scheduler.sh`), `gh` CLI, `claude -p`.

**Spec:** `docs/superpowers/specs/2026-06-20-epic-autopilot-design.md`
**Depends on:** `2026-06-20-system-notifications-enabler.md` (provides `POST /api/v1/alerts/system`).

## Global Constraints

- **Ships disabled:** `epic_autopilot.enabled: false` in config; the scheduler hook is a no-op until enabled. Decision threshold: ADVANCE only on `decision==ADVANCE AND risk==low AND confidence>=confidence_floor` (default 0.7).
- **Fail-closed everywhere:** unparseable Opus output → HOLD; undeclared file scope → excluded; any exception in the autopilot step must never crash the scheduler loop (the `scheduler.sh` call is guarded with `|| true` semantics).
- **Hard exclusions (deterministic, before Opus):** factory self-edits (`dark-factory/`, `.archon/`, `scheduler.sh`, `factory_core/`), automated-trading (`app/services/trading`, `app/tasks/trading.py`), authN/authZ (`app/core/auth`, `app/routers/auth`). Plain `security` label is allowed.
- **Pacing:** ≤1 advance per cycle; daily cap (default 5, UTC reset); verdict cache keyed by `(issue, spec_hash)`.
- Notifications POST to `http://backend:8000/api/v1/alerts/system` with header `X-Internal-Token: $INTERNAL_API_TOKEN`.
- Tests live in `dark-factory/tests/`; run with `python -m pytest dark-factory/tests/test_epic_autopilot.py -v`. No live `gh`/`claude`/HTTP in tests (inject fakes).

---

### Task 1: Config knobs (config.yaml + scheduler.sh)

**Files:**
- Modify: `.claude/skills/refinement/config.yaml` (add `epic_autopilot:` section)
- Modify: `dark-factory/scheduler.sh` (`read_config` block ~lines 68-83; add a guarded Priority-6 call is Task 6)
- Test: `dark-factory/tests/test_epic_autopilot_config.sh`

**Interfaces:**
- Produces env vars (via `read_config`): `EPIC_AUTOPILOT_ENABLED`, `EPIC_AUTOPILOT_MODEL`, `EPIC_AUTOPILOT_DAILY_CAP`, `EPIC_AUTOPILOT_CONFIDENCE_FLOOR`, `EPIC_AUTOPILOT_OPT_OUT_LABEL`.

- [ ] **Step 1: Write the failing test**
```bash
# dark-factory/tests/test_epic_autopilot_config.sh
#!/usr/bin/env bash
set -euo pipefail
export SCHEDULER_SOURCE_ONLY=1
source "$(dirname "$0")/../scheduler.sh"
cfg="$(dirname "$0")/../../.claude/skills/refinement/config.yaml"
val=$(yq '.epic_autopilot.enabled' "$cfg")
[ "$val" = "false" ] || { echo "FAIL: epic_autopilot.enabled should default false, got '$val'"; exit 1; }
cap=$(yq '.epic_autopilot.daily_cap' "$cfg")
[ "$cap" = "5" ] || { echo "FAIL: daily_cap should be 5, got '$cap'"; exit 1; }
echo "PASS"
```

- [ ] **Step 2: Run to verify it fails**

Run: `bash dark-factory/tests/test_epic_autopilot_config.sh`
Expected: FAIL (`null` for `.epic_autopilot.enabled`)

- [ ] **Step 3: Add the config section**

Append to `.claude/skills/refinement/config.yaml`:
```yaml
epic_autopilot:
  enabled: false              # kill-switch — ship OFF. env: EPIC_AUTOPILOT_ENABLED
  model: claude-opus-4-8
  daily_cap: 5                # max autonomous advances / UTC day
  confidence_floor: 0.7       # min Opus confidence to ADVANCE
  opt_out_label: no-autopilot
  hard_exclude_paths:
    - "dark-factory/"
    - ".archon/"
    - "scheduler.sh"
    - "factory_core/"
    - "app/services/trading"
    - "app/tasks/trading.py"
    - "app/core/auth"
    - "app/routers/auth"
```

- [ ] **Step 4: Wire the knobs in `read_config`**

In `dark-factory/scheduler.sh`, inside `read_config()` after the existing `_set_cfg` calls (~line 81), add:
```sh
  _set_cfg EPIC_AUTOPILOT_ENABLED          '.epic_autopilot.enabled'
  _set_cfg EPIC_AUTOPILOT_MODEL            '.epic_autopilot.model'
  _set_cfg EPIC_AUTOPILOT_DAILY_CAP        '.epic_autopilot.daily_cap'
  _set_cfg EPIC_AUTOPILOT_CONFIDENCE_FLOOR '.epic_autopilot.confidence_floor'
  _set_cfg EPIC_AUTOPILOT_OPT_OUT_LABEL    '.epic_autopilot.opt_out_label'
```

- [ ] **Step 5: Run to verify it passes**

Run: `bash dark-factory/tests/test_epic_autopilot_config.sh`
Expected: `PASS`

- [ ] **Step 6: Commit**
```bash
git add .claude/skills/refinement/config.yaml dark-factory/scheduler.sh dark-factory/tests/test_epic_autopilot_config.sh
git commit -m "feat(autopilot): config section + scheduler read_config knobs (ships disabled)"
```

---

### Task 2: Eligibility + hard-rule exclusions (pure)

**Files:**
- Create: `dark-factory/scripts/factory_core/epic_autopilot.py`
- Test: `dark-factory/tests/test_epic_autopilot.py`

**Interfaces:**
- Produces:
  - `Candidate` = a dict `{number:int, title:str, body:str, labels:list[str], size:str|None, status:str, spec_text:str, target_paths:list[str]}`
  - `is_eligible(c: dict, opt_out_label: str, ceiling_keywords: str) -> tuple[bool, str]`
  - `extract_target_paths(text: str) -> list[str]`
  - `hard_excluded(c: dict, exclude_paths: list[str]) -> tuple[bool, str]`

- [ ] **Step 1: Write failing tests**
```python
# dark-factory/tests/test_epic_autopilot.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from factory_core import epic_autopilot as ap

CEIL = "migration|migrate|performance|perf|architectur|refactor"

def c(**kw):
    base = dict(number=1, title="t", body="b", labels=["ready-for-agent"], size="S",
                status="spec-pending-review", spec_text="touches backend/app/services/foo.py",
                target_paths=["backend/app/services/foo.py"])
    base.update(kw); return base

def test_eligible_happy():
    ok, why = ap.is_eligible(c(), "no-autopilot", CEIL)
    assert ok, why

def test_ineligible_opt_out():
    ok, _ = ap.is_eligible(c(labels=["ready-for-agent", "no-autopilot"]), "no-autopilot", CEIL)
    assert not ok

def test_ineligible_already_direct_to_pr():
    ok, _ = ap.is_eligible(c(labels=["direct-to-pr"]), "no-autopilot", CEIL)
    assert not ok

def test_ineligible_wrong_status():
    ok, _ = ap.is_eligible(c(status="Ready"), "no-autopilot", CEIL)
    assert not ok

def test_ineligible_above_ceiling_size_l():
    ok, _ = ap.is_eligible(c(size="L"), "no-autopilot", CEIL)
    assert not ok

def test_ineligible_m_with_ceiling_keyword():
    ok, _ = ap.is_eligible(c(size="M", title="perf refactor of scanner"), "no-autopilot", CEIL)
    assert not ok

def test_eligible_m_without_keyword():
    ok, why = ap.is_eligible(c(size="M", title="add data quality preflight"), "no-autopilot", CEIL)
    assert ok, why

def test_extract_paths():
    paths = ap.extract_target_paths("Modifies `backend/app/services/x.py` and dark-factory/seed/y.sql")
    assert "backend/app/services/x.py" in paths
    assert "dark-factory/seed/y.sql" in paths

def test_hard_exclude_factory_self():
    ex, why = ap.hard_excluded(c(target_paths=["dark-factory/scheduler.sh"]),
                               ["dark-factory/", "app/core/auth"])
    assert ex and "dark-factory/" in why

def test_hard_exclude_auth():
    ex, _ = ap.hard_excluded(c(target_paths=["backend/app/core/auth/jwt.py"]),
                             ["app/core/auth"])
    assert ex

def test_hard_exclude_undeclared_scope_fails_closed():
    ex, why = ap.hard_excluded(c(target_paths=[]), ["app/core/auth"])
    assert ex and why == "undeclared-scope"

def test_security_label_not_excluded():
    ex, _ = ap.hard_excluded(c(labels=["security", "ready-for-agent"],
                               target_paths=["backend/app/services/redaction.py"]),
                             ["app/core/auth", "app/services/trading"])
    assert not ex
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest dark-factory/tests/test_epic_autopilot.py -v`
Expected: FAIL (`ModuleNotFoundError` / functions missing)

- [ ] **Step 3: Implement eligibility + exclusions**
```python
# dark-factory/scripts/factory_core/epic_autopilot.py
"""Epic Autopilot — starved-only self-unlock reviewer (pure core + injected IO)."""
import re

_GATED_STATUSES = {"spec-pending-review", "plan-pending-review"}
_PATH_RE = re.compile(r"[A-Za-z0-9_./-]+\.(?:py|ts|tsx|sh|ya?ml|md|sql)")


def extract_target_paths(text: str) -> list[str]:
    """Best-effort: pull code-path-like tokens from a spec/plan/body."""
    if not text:
        return []
    seen, out = set(), []
    for m in _PATH_RE.findall(text):
        if m not in seen:
            seen.add(m); out.append(m)
    return out


def _size(c: dict) -> str | None:
    for l in c.get("labels", []):
        if l.lower().startswith("size:"):
            return l.split(":", 1)[1].strip().upper()
    return c.get("size")


def is_eligible(c: dict, opt_out_label: str, ceiling_keywords: str) -> tuple[bool, str]:
    labels = [l.lower() for l in c.get("labels", [])]
    if c.get("status") not in _GATED_STATUSES:
        return False, f"status={c.get('status')}"
    for blk in ("direct-to-pr", opt_out_label, "needs-discussion", "epic"):
        if blk.lower() in labels:
            return False, f"label:{blk}"
    size = (_size(c) or "").upper()
    if size in ("L", "XL"):
        return False, f"above-ceiling:size={size}"
    if size == "M" and re.search(ceiling_keywords, c.get("title", ""), re.I):
        return False, "above-ceiling:M+keyword"
    return True, ""


def hard_excluded(c: dict, exclude_paths: list[str]) -> tuple[bool, str]:
    paths = c.get("target_paths") or []
    if not paths:
        return True, "undeclared-scope"   # fail-closed
    for p in paths:
        for ex in exclude_paths:
            if ex in p:
                return True, ex
    return False, ""
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest dark-factory/tests/test_epic_autopilot.py -v`
Expected: PASS (all eligibility/exclusion tests)

- [ ] **Step 5: Commit**
```bash
git add dark-factory/scripts/factory_core/epic_autopilot.py dark-factory/tests/test_epic_autopilot.py
git commit -m "feat(autopilot): eligibility + hard-rule exclusions (pure, fail-closed)"
```

---

### Task 3: Verdict parsing + decision rule (pure)

**Files:**
- Modify: `dark-factory/scripts/factory_core/epic_autopilot.py`
- Test: `dark-factory/tests/test_epic_autopilot.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `parse_verdict(text: str) -> dict` — returns `{"decision","risk","confidence","reasons","concerns"}`; on any error returns the HOLD sentinel `{"decision":"HOLD","risk":"high","confidence":0.0,"reasons":["unparseable"],"concerns":[]}`.
  - `should_advance(verdict: dict, confidence_floor: float) -> bool`

- [ ] **Step 1: Append failing tests**
```python
def test_parse_clean_json():
    v = ap.parse_verdict('{"decision":"ADVANCE","risk":"low","confidence":0.9,"reasons":["ok"],"concerns":[]}')
    assert v["decision"] == "ADVANCE" and v["confidence"] == 0.9

def test_parse_json_in_fence():
    v = ap.parse_verdict('blah\n```json\n{"decision":"HOLD","risk":"medium","confidence":0.5,"reasons":[],"concerns":["x"]}\n```\n')
    assert v["decision"] == "HOLD"

def test_parse_garbage_fails_closed():
    v = ap.parse_verdict("the model rambled with no json")
    assert v["decision"] == "HOLD" and v["risk"] == "high"

def test_parse_empty_fails_closed():
    assert ap.parse_verdict("")["decision"] == "HOLD"

def test_should_advance_only_on_low_and_floor():
    assert ap.should_advance({"decision":"ADVANCE","risk":"low","confidence":0.8}, 0.7)
    assert not ap.should_advance({"decision":"ADVANCE","risk":"medium","confidence":0.9}, 0.7)
    assert not ap.should_advance({"decision":"ADVANCE","risk":"low","confidence":0.6}, 0.7)
    assert not ap.should_advance({"decision":"HOLD","risk":"low","confidence":0.99}, 0.7)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest dark-factory/tests/test_epic_autopilot.py -k "parse or advance" -v`
Expected: FAIL

- [ ] **Step 3: Implement**
```python
import json

_HOLD = {"decision": "HOLD", "risk": "high", "confidence": 0.0,
         "reasons": ["unparseable"], "concerns": []}


def parse_verdict(text: str) -> dict:
    if not text or not text.strip():
        return dict(_HOLD)
    # find the first {...} block (tolerates ```json fences / surrounding prose)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return dict(_HOLD)
    try:
        v = json.loads(text[start:end + 1])
    except Exception:
        return dict(_HOLD)
    if not isinstance(v, dict) or v.get("decision") not in ("ADVANCE", "HOLD"):
        return dict(_HOLD)
    v.setdefault("risk", "high")
    v.setdefault("confidence", 0.0)
    v.setdefault("reasons", [])
    v.setdefault("concerns", [])
    try:
        v["confidence"] = float(v["confidence"])
    except Exception:
        return dict(_HOLD)
    return v


def should_advance(verdict: dict, confidence_floor: float) -> bool:
    return (verdict.get("decision") == "ADVANCE"
            and verdict.get("risk") == "low"
            and float(verdict.get("confidence", 0.0)) >= confidence_floor)
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest dark-factory/tests/test_epic_autopilot.py -k "parse or advance" -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add dark-factory/scripts/factory_core/epic_autopilot.py dark-factory/tests/test_epic_autopilot.py
git commit -m "feat(autopilot): verdict parsing + decision rule (fail-closed to HOLD)"
```

---

### Task 4: Daily cap + verdict cache (state file)

**Files:**
- Modify: `dark-factory/scripts/factory_core/epic_autopilot.py`
- Test: `dark-factory/tests/test_epic_autopilot.py` (append)

**Interfaces:**
- Produces (all take/return a plain `state` dict so they're pure; the orchestrator loads/saves JSON):
  - `daily_remaining(state: dict, cap: int, today: str) -> int`
  - `record_advance(state: dict, today: str) -> None`
  - `cached_verdict(state: dict, issue: int, spec_hash: str) -> str | None`
  - `record_verdict(state: dict, issue: int, spec_hash: str, verdict: str) -> None`
  - `spec_hash(spec_text: str) -> str`

- [ ] **Step 1: Append failing tests**
```python
def test_daily_cap_counts_and_resets():
    st = {}
    assert ap.daily_remaining(st, 5, "2026-06-20") == 5
    ap.record_advance(st, "2026-06-20"); ap.record_advance(st, "2026-06-20")
    assert ap.daily_remaining(st, 5, "2026-06-20") == 3
    # next UTC day resets
    assert ap.daily_remaining(st, 5, "2026-06-21") == 5

def test_verdict_cache_roundtrip_and_hash_invalidation():
    st = {}
    h1 = ap.spec_hash("spec A")
    assert ap.cached_verdict(st, 402, h1) is None
    ap.record_verdict(st, 402, h1, "HOLD")
    assert ap.cached_verdict(st, 402, h1) == "HOLD"
    # regenerated spec → different hash → cache miss (re-review)
    assert ap.cached_verdict(st, 402, ap.spec_hash("spec A v2")) is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest dark-factory/tests/test_epic_autopilot.py -k "daily or cache" -v`
Expected: FAIL

- [ ] **Step 3: Implement**
```python
import hashlib


def spec_hash(spec_text: str) -> str:
    return hashlib.sha256((spec_text or "").encode("utf-8")).hexdigest()[:16]


def daily_remaining(state: dict, cap: int, today: str) -> int:
    d = state.get("daily") or {}
    used = d.get("count", 0) if d.get("date") == today else 0
    return max(0, cap - used)


def record_advance(state: dict, today: str) -> None:
    d = state.get("daily") or {}
    if d.get("date") != today:
        d = {"date": today, "count": 0}
    d["count"] = d.get("count", 0) + 1
    state["daily"] = d


def cached_verdict(state: dict, issue: int, spec_hash_: str) -> str | None:
    entry = (state.get("verdicts") or {}).get(str(issue))
    if entry and entry.get("spec_hash") == spec_hash_:
        return entry.get("verdict")
    return None


def record_verdict(state: dict, issue: int, spec_hash_: str, verdict: str) -> None:
    state.setdefault("verdicts", {})[str(issue)] = {"spec_hash": spec_hash_, "verdict": verdict}
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest dark-factory/tests/test_epic_autopilot.py -k "daily or cache" -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add dark-factory/scripts/factory_core/epic_autopilot.py dark-factory/tests/test_epic_autopilot.py
git commit -m "feat(autopilot): daily cap + spec-hash verdict cache (pure)"
```

---

### Task 5: Orchestrator with injected IO

**Files:**
- Modify: `dark-factory/scripts/factory_core/epic_autopilot.py`
- Test: `dark-factory/tests/test_epic_autopilot.py` (append)

**Interfaces:**
- Produces: `run_once(cfg, io, state, today) -> dict` where:
  - `cfg` = `{exclude_paths, opt_out_label, ceiling_keywords, confidence_floor, daily_cap, model}`
  - `io` = an object/namespace with injected callables: `fetch_candidates() -> list[dict]`, `review(prompt, model) -> str`, `advance(issue) -> None` (adds `direct-to-pr`), `comment(issue, body) -> None`, `notify(title, body, severity, dedupe_key) -> None`
  - returns `{"outcome": "advanced|hold|no_candidates|daily_cap_reached", "issue": int|None, "reason": str}`
- The orchestrator: enforce daily cap → fetch → filter (eligible & not hard-excluded & not cache-HOLD) → if none, notify "stuck" (throttled) + return `no_candidates` → pick first → build prompt → review → parse → decide → ADVANCE: advance+comment+notify+record; HOLD: comment+cache.

- [ ] **Step 1: Append failing tests (fakes, no real IO)**
```python
class FakeIO:
    def __init__(self, candidates, review_text):
        self._cands = candidates; self._review = review_text
        self.advanced = []; self.comments = []; self.notes = []
    def fetch_candidates(self): return self._cands
    def review(self, prompt, model): return self._review
    def advance(self, issue): self.advanced.append(issue)
    def comment(self, issue, body): self.comments.append((issue, body))
    def notify(self, title, body, severity, dedupe_key): self.notes.append((severity, dedupe_key))

CFG = dict(exclude_paths=["app/core/auth", "dark-factory/"], opt_out_label="no-autopilot",
           ceiling_keywords=CEIL, confidence_floor=0.7, daily_cap=5, model="claude-opus-4-8")

def test_run_advances_low_risk():
    io = FakeIO([c(number=402)], '{"decision":"ADVANCE","risk":"low","confidence":0.9,"reasons":["safe"],"concerns":[]}')
    st = {}
    out = ap.run_once(CFG, io, st, "2026-06-20")
    assert out["outcome"] == "advanced" and out["issue"] == 402
    assert io.advanced == [402]
    assert any(sev == "info" for sev, _ in io.notes)          # advance notice
    assert ap.daily_remaining(st, 5, "2026-06-20") == 4

def test_run_holds_medium_risk():
    io = FakeIO([c(number=402)], '{"decision":"ADVANCE","risk":"medium","confidence":0.9,"reasons":[],"concerns":["risky"]}')
    st = {}
    out = ap.run_once(CFG, io, st, "2026-06-20")
    assert out["outcome"] == "hold" and io.advanced == []
    assert ap.cached_verdict(st, 402, ap.spec_hash(c(number=402)["spec_text"])) == "HOLD"

def test_run_no_candidates_notifies_stuck():
    io = FakeIO([c(number=402, labels=["no-autopilot", "ready-for-agent"])], "x")
    out = ap.run_once(CFG, io, {}, "2026-06-20")
    assert out["outcome"] == "no_candidates"
    assert any(sev == "warning" and key == "autopilot-stuck" for sev, key in io.notes)

def test_run_daily_cap_reached_notifies():
    io = FakeIO([c(number=402)], "x")
    st = {"daily": {"date": "2026-06-20", "count": 5}}
    out = ap.run_once(CFG, io, st, "2026-06-20")
    assert out["outcome"] == "daily_cap_reached"
    assert io.advanced == []
    assert any(key == "autopilot-cap" for _, key in io.notes)

def test_run_skips_cached_hold():
    cand = c(number=402)
    st = {}; ap.record_verdict(st, 402, ap.spec_hash(cand["spec_text"]), "HOLD")
    io = FakeIO([cand], '{"decision":"ADVANCE","risk":"low","confidence":0.9}')
    out = ap.run_once(CFG, io, st, "2026-06-20")
    assert out["outcome"] == "no_candidates"   # the only candidate is cache-suppressed
    assert io.advanced == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest dark-factory/tests/test_epic_autopilot.py -k "run_" -v`
Expected: FAIL

- [ ] **Step 3: Implement the orchestrator + prompt builder**
```python
def build_review_prompt(c: dict) -> str:
    return f"""You are a cautious senior engineer deciding whether a refined ticket is safe to
implement and merge AUTONOMOUSLY (adding the direct-to-pr label means it flows
spec→plan→implement→PR with NO further human gate before the PR opens).

Reply with ONLY a JSON object:
{{"decision":"ADVANCE|HOLD","risk":"low|medium|high","confidence":0.0-1.0,
  "reasons":[...],"concerns":[...]}}

ADVANCE only if the work is genuinely low-risk: small, well-scoped, reversible, good test
coverage in the spec/plan, low blast radius, and NOT touching automated trading,
authentication/authorization, or the factory/scheduler itself. If the spec is vague, an
empty-branch/no-op risk, or you are unsure — choose HOLD.

Ticket #{c['number']}: {c['title']}
Labels: {', '.join(c.get('labels', []))}   Size: {c.get('size')}
Declared target files: {', '.join(c.get('target_paths') or []) or '(none declared)'}

--- SPEC/PLAN ---
{c.get('spec_text', '')[:8000]}
"""


def run_once(cfg: dict, io, state: dict, today: str) -> dict:
    if daily_remaining(state, cfg["daily_cap"], today) <= 0:
        io.notify("Epic autopilot — daily cap reached",
                  f"Hit the daily cap of {cfg['daily_cap']} autonomous advances; paused until UTC reset. Review the backlog.",
                  "warning", "autopilot-cap")
        return {"outcome": "daily_cap_reached", "issue": None, "reason": "cap"}

    candidates = []
    for cand in io.fetch_candidates():
        ok, _ = is_eligible(cand, cfg["opt_out_label"], cfg["ceiling_keywords"])
        if not ok:
            continue
        ex, _ = hard_excluded(cand, cfg["exclude_paths"])
        if ex:
            continue
        if cached_verdict(state, cand["number"], spec_hash(cand.get("spec_text", ""))) == "HOLD":
            continue
        candidates.append(cand)

    if not candidates:
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
                   f"🤖 **Epic Autopilot** — advancing (risk={verdict['risk']}, conf={verdict['confidence']}). "
                   f"Reason: {reason}\n\n---\n*Posted by MarketHawk Epic Autopilot*")
        io.notify(f"Autopilot advancing #{cand['number']}",
                  f"{cand['title']} — risk=low: {reason}", "info", None)
        record_advance(state, today)
        record_verdict(state, cand["number"], h, "ADVANCE")
        return {"outcome": "advanced", "issue": cand["number"], "reason": reason}

    concerns = "; ".join(verdict.get("concerns", [])) or "not low-risk / low confidence"
    io.comment(cand["number"],
               f"🤖 **Epic Autopilot** — parked (HOLD). {concerns}\n\n---\n*Posted by MarketHawk Epic Autopilot*")
    record_verdict(state, cand["number"], h, "HOLD")
    return {"outcome": "hold", "issue": cand["number"], "reason": concerns}
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest dark-factory/tests/test_epic_autopilot.py -v`
Expected: PASS (full suite)

- [ ] **Step 5: Commit**
```bash
git add dark-factory/scripts/factory_core/epic_autopilot.py dark-factory/tests/test_epic_autopilot.py
git commit -m "feat(autopilot): orchestrator (advance/hold/stuck/cap) with injected IO"
```

---

### Task 6: Real IO adapter, CLI subcommand, scheduler hook

**Files:**
- Modify: `dark-factory/scripts/factory_core/epic_autopilot.py` (add real `LiveIO` + `main_once()`)
- Modify: `dark-factory/scripts/factory_core/cli.py` (subcommand `epic-autopilot`)
- Modify: `dark-factory/scheduler.sh` (Priority-6 guarded call)
- Test: `dark-factory/tests/test_scheduler_autopilot_guard.sh`

**Interfaces:**
- Consumes: `run_once`, all pure helpers.
- Produces: `cli.py epic-autopilot --once` prints one structured line (`autopilot=<outcome> issue=#N`); `scheduler.sh` Priority 6 calls it only when starved.

- [ ] **Step 1: Write the failing scheduler-guard test**
```bash
# dark-factory/tests/test_scheduler_autopilot_guard.sh
#!/usr/bin/env bash
set -euo pipefail
# The Priority-6 block must be gated on DISPATCHED empty + main green + enabled.
grep -q 'EPIC_AUTOPILOT_ENABLED' "$(dirname "$0")/../scheduler.sh" || { echo "FAIL: no autopilot hook"; exit 1; }
# Must reference the cli subcommand and the starved guard
grep -qE 'epic-autopilot' "$(dirname "$0")/../scheduler.sh" || { echo "FAIL: cli call missing"; exit 1; }
grep -qE '\[ -z "\$DISPATCHED" \].*EPIC_AUTOPILOT_ENABLED|EPIC_AUTOPILOT_ENABLED.*-z "\$DISPATCHED"' "$(dirname "$0")/../scheduler.sh" \
  || grep -A3 'EPIC_AUTOPILOT_ENABLED' "$(dirname "$0")/../scheduler.sh" | grep -q 'DISPATCHED' \
  || { echo "FAIL: not guarded by DISPATCHED-empty"; exit 1; }
echo "PASS"
```

- [ ] **Step 2: Run to verify it fails**

Run: `bash dark-factory/tests/test_scheduler_autopilot_guard.sh`
Expected: FAIL

- [ ] **Step 3: Add `LiveIO` + `main_once()` to `epic_autopilot.py`**
```python
import os, subprocess, urllib.request

OWNER = "omniscient/markethawk"


class LiveIO:
    """Real adapters: gh GraphQL/REST + claude -p + the /system notify endpoint."""
    def __init__(self, model: str):
        self.model = model

    def fetch_candidates(self) -> list[dict]:
        # GraphQL: in-progress epics -> subIssues; map gated children to candidate dicts.
        # (Implementation mirrors fetch_board_items in scheduler.sh; for each gated child,
        #  pull its spec text from the latest "Spec/Plan Generated" comment and the issue body.)
        return _gh_fetch_candidates()

    def review(self, prompt: str, model: str) -> str:
        p = subprocess.run(["claude", "-p", "--model", model], input=prompt,
                           capture_output=True, text=True, timeout=300)
        return p.stdout if p.returncode == 0 else ""

    def advance(self, issue: int) -> None:
        subprocess.run(["gh", "issue", "edit", str(issue), "--repo", OWNER,
                        "--add-label", "direct-to-pr"], check=False)

    def comment(self, issue: int, body: str) -> None:
        subprocess.run(["gh", "issue", "comment", str(issue), "--repo", OWNER,
                        "--body", body], check=False)

    def notify(self, title: str, body: str, severity: str, dedupe_key) -> None:
        token = os.environ.get("INTERNAL_API_TOKEN", "")
        if not token:
            return
        payload = {"title": title, "body": body, "severity": severity}
        if dedupe_key:
            payload["dedupe_key"] = dedupe_key
        req = urllib.request.Request(
            "http://backend:8000/api/v1/alerts/system",
            data=__import__("json").dumps(payload).encode(),
            headers={"Content-Type": "application/json", "X-Internal-Token": token},
            method="POST")
        try:
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass  # fail-soft


def main_once() -> int:
    import json
    state_dir = os.environ.get("SCHEDULER_STATE_DIR", "/var/lib/dark-factory")
    path = os.path.join(state_dir, "autopilot-state.json")
    state = json.load(open(path)) if os.path.exists(path) else {}
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()
    cfg = dict(
        exclude_paths=_load_exclude_paths(),
        opt_out_label=os.environ.get("EPIC_AUTOPILOT_OPT_OUT_LABEL", "no-autopilot"),
        ceiling_keywords=os.environ.get("ABOVE_CEILING_KEYWORDS",
            "migration|migrate|performance|perf|architectur|refactor"),
        confidence_floor=float(os.environ.get("EPIC_AUTOPILOT_CONFIDENCE_FLOOR", "0.7")),
        daily_cap=int(os.environ.get("EPIC_AUTOPILOT_DAILY_CAP", "5")),
        model=os.environ.get("EPIC_AUTOPILOT_MODEL", "claude-opus-4-8"))
    out = run_once(cfg, LiveIO(cfg["model"]), state, today)
    json.dump(state, open(path, "w"))
    print(f"autopilot={out['outcome']} issue=#{out['issue']}")
    return 0
```
(Add stub helpers `_gh_fetch_candidates()` and `_load_exclude_paths()` — the latter reads `hard_exclude_paths` from config.yaml via `yq` or a small parser; `_gh_fetch_candidates()` does the GraphQL walk. These touch live `gh`, so they're exercised only in the manual validation step, not unit tests.)

- [ ] **Step 4: Add the CLI subcommand**

In `dark-factory/scripts/factory_core/cli.py`, add a handler and register it in `main()`:
```python
def _epic_autopilot(args):
    from factory_core.epic_autopilot import main_once
    return main_once()
```
```python
    ea = sub.add_parser("epic-autopilot")
    ea.add_argument("--once", action="store_true")
    ea.set_defaults(func=_epic_autopilot)
```

- [ ] **Step 5: Add the Priority-6 hook in `scheduler.sh`**

After Priority 5 (the Backlog loop ends ~line 1095) and before the cycle-summary log (~line 1097), add:
```sh
  # --- Priority 6: Epic Autopilot (starved self-unlock, #571) ---
  # Runs ONLY when this cycle dispatched nothing, main is green, and it is enabled.
  # Fail-soft: never let it abort the loop.
  if [ -z "$DISPATCHED" ] && [ "$MAIN_IS_RED" = "false" ] && [ "${EPIC_AUTOPILOT_ENABLED:-false}" = "true" ]; then
    AP_OUT=$(python3 "$FACTORY_CORE_CLI" epic-autopilot --once 2>&1) || true
    echo "[$(date -u +%FT%TZ)] ${AP_OUT}"
    case "$AP_OUT" in *"autopilot=advanced"*) DISPATCHED="$AP_OUT" ;; esac
  fi
```

- [ ] **Step 6: Run the guard test + full python suite**

Run: `bash dark-factory/tests/test_scheduler_autopilot_guard.sh && python -m pytest dark-factory/tests/test_epic_autopilot.py -v`
Expected: `PASS` + green suite

- [ ] **Step 7: Manual validation (with the image rebuilt)**

Per project memory: scheduler.sh + factory_core are baked into the factory image, so rebuild + recreate before this runs live.
```bash
docker compose --profile factory build dark-factory
docker compose --profile scheduler up -d --force-recreate --no-build backlog-scheduler
# Temporarily enable in .archon/.env (EPIC_AUTOPILOT_ENABLED=true) + ensure INTERNAL_API_TOKEN is set
# Watch one starved cycle advance a single low-risk ticket:
docker logs -f backlog-scheduler | grep autopilot
```
Expected: `autopilot=advanced issue=#N`, the ticket gains `direct-to-pr` + an autopilot comment, and an advance email/push arrives. Force the cap and the empty-pool path to confirm the `autopilot-cap` / `autopilot-stuck` notifications.

- [ ] **Step 8: Commit**
```bash
git add dark-factory/scripts/factory_core/epic_autopilot.py dark-factory/scripts/factory_core/cli.py dark-factory/scheduler.sh dark-factory/tests/test_scheduler_autopilot_guard.sh
git commit -m "feat(autopilot): live IO adapter, CLI subcommand, scheduler Priority-6 hook"
```

---

## Self-Review

- **Spec coverage:** starved-only trigger (Task 6 guard) ✓; Stage A eligibility + ceiling (Task 2) ✓; Stage B hard exclusions + fail-closed undeclared scope + security-passes (Task 2) ✓; Opus reviewer + structured verdict + decision rule + fail-closed (Task 3) ✓; ADVANCE/HOLD actions + comment + notify (Task 5) ✓; daily cap + verdict cache (Task 4) ✓; three notifications incl. throttled stuck via dedupe_key (Task 5) ✓; config + kill-switch (Task 1) ✓; CLI + hook + baked-image rebuild note (Task 6) ✓.
- **Placeholders:** the only deferred-to-implementation pieces are `_gh_fetch_candidates()` and `_load_exclude_paths()` (live-`gh`/config IO) — explicitly flagged as manual-validation-only, not unit-tested, with their contracts stated (return candidate dicts / exclude-path list). All pure logic is fully coded + tested.
- **Type consistency:** the `Candidate` dict keys (`number/title/body/labels/size/status/spec_text/target_paths`) are identical across Tasks 2/5; `run_once(cfg, io, state, today)` and the `io` callable set match between the Task 5 definition, the FakeIO test, and the Task 6 `LiveIO`; `spec_hash`/`cached_verdict`/`record_verdict` signatures consistent across Tasks 4/5.
- **Cross-plan dependency:** Task 5/6 `notify` targets `POST /api/v1/alerts/system` from the System Notifications Enabler plan — implement that plan first (or the notify calls fail-soft to no-ops until it exists).
