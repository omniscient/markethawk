"""Epic Autopilot — starved-only self-unlock reviewer (pure core + injected IO).

When the backlog scheduler is starved (a poll dispatched nothing) and main is green,
review the refined, below-ceiling children of in-progress epics with Opus 4.8 and
advance the low-risk ones via the `direct-to-pr` label. See
docs/superpowers/specs/2026-06-20-epic-autopilot-design.md.

The pure functions below take/return plain data so they unit-test with no IO.
"""
import hashlib
import json
import re

_GATED_STATUSES = {"spec-pending-review", "plan-pending-review"}
_PATH_RE = re.compile(r"[A-Za-z0-9_./-]+\.(?:py|ts|tsx|sh|ya?ml|md|sql)")


def extract_target_paths(text: str) -> list:
    """Best-effort: pull code-path-like tokens from a spec/plan/body."""
    if not text:
        return []
    seen, out = set(), []
    for m in _PATH_RE.findall(text):
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _size(c: dict):
    for label in c.get("labels", []):
        if label.lower().startswith("size:"):
            return label.split(":", 1)[1].strip().upper()
    s = c.get("size")
    return s.upper() if s else None


def is_eligible(c: dict, opt_out_label: str, ceiling_keywords: str):
    """Stage A — structural eligibility. Returns (ok: bool, reason: str)."""
    labels = [label.lower() for label in c.get("labels", [])]
    if c.get("status") not in _GATED_STATUSES:
        return False, f"status={c.get('status')}"
    for blk in ("direct-to-pr", opt_out_label, "needs-discussion", "epic"):
        if blk.lower() in labels:
            return False, f"label:{blk}"
    size = _size(c) or ""
    if size in ("L", "XL"):
        return False, f"above-ceiling:size={size}"
    if size == "M" and re.search(ceiling_keywords, c.get("title", ""), re.I):
        return False, "above-ceiling:M+keyword"
    return True, ""


def hard_excluded(c: dict, exclude_paths: list):
    """Stage B — categorical exclusions (fail-closed). Returns (excluded: bool, reason: str)."""
    paths = c.get("target_paths") or []
    if not paths:
        return True, "undeclared-scope"  # fail-closed: undeclared scope might be trading/auth
    for p in paths:
        for ex in exclude_paths:
            if ex in p:
                return True, ex
    return False, ""


# ── Verdict parsing + decision rule ─────────────────────────────────────────

_HOLD = {"decision": "HOLD", "risk": "high", "confidence": 0.0,
         "reasons": ["unparseable"], "concerns": []}


def parse_verdict(text: str) -> dict:
    """Parse Opus's JSON verdict. Fail-closed to HOLD on any error/ambiguity."""
    if not text or not text.strip():
        return dict(_HOLD)
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
    """ADVANCE only on decision=ADVANCE AND risk=low AND confidence>=floor."""
    return (verdict.get("decision") == "ADVANCE"
            and verdict.get("risk") == "low"
            and float(verdict.get("confidence", 0.0)) >= confidence_floor)


# ── Daily cap + verdict cache (state is a plain dict; orchestrator persists JSON) ──

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


def cached_verdict(state: dict, issue: int, spec_hash_: str):
    entry = (state.get("verdicts") or {}).get(str(issue))
    if entry and entry.get("spec_hash") == spec_hash_:
        return entry.get("verdict")
    return None


def record_verdict(state: dict, issue: int, spec_hash_: str, verdict: str) -> None:
    state.setdefault("verdicts", {})[str(issue)] = {"spec_hash": spec_hash_, "verdict": verdict}
