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


# ── Epic selector (pure; used by epic-starter workflow) ──────────────────────

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


# ── Orchestrator (pure control flow; all IO injected via `io`) ──────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# Live IO (exercised in manual validation, not unit tests — all gh/claude/HTTP)
# ─────────────────────────────────────────────────────────────────────────────
import os  # noqa: E402
import subprocess  # noqa: E402
import urllib.request  # noqa: E402

OWNER = "omniscient/markethawk"
PROJECT_ID = "PVT_kwHOAAFds84BWh4w"
_GATING_LABELS = ("plan-pending-review", "spec-pending-review")  # plan takes precedence
_DEFAULT_EXCLUDE = ["dark-factory/", ".archon/", "scheduler.sh", "factory_core/",
                    "app/services/trading", "app/tasks/trading.py", "app/core/auth", "app/routers/auth"]
_CONFIG_PATHS = ["/workspace/project/.claude/skills/refinement/config.yaml",
                 "/opt/refinement-skills/config.yaml"]


def _gh_json(args: list):
    """Run a gh command and parse JSON stdout; return None on failure."""
    try:
        p = subprocess.run(["gh"] + args, capture_output=True, text=True, timeout=60)
        if p.returncode != 0 or not p.stdout.strip():
            return None
        return json.loads(p.stdout)
    except Exception:
        return None


def _load_exclude_paths() -> list:
    """Read epic_autopilot.hard_exclude_paths from config.yaml (via yq); fall back to defaults."""
    for cfg in _CONFIG_PATHS:
        if not os.path.exists(cfg):
            continue
        try:
            p = subprocess.run(["yq", ".epic_autopilot.hard_exclude_paths[]", cfg],
                               capture_output=True, text=True, timeout=15)
            paths = [ln.strip().strip('"') for ln in p.stdout.splitlines() if ln.strip()]
            if paths:
                return paths
        except Exception:
            pass
    return list(_DEFAULT_EXCLUDE)


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


def _in_progress_epics() -> list:
    """Issue numbers of epics whose board Status is 'In progress'."""
    q = ('query { node(id: "%s") { ... on ProjectV2 { items(first:100) { nodes { '
         'fieldValueByName(name:"Status"){ ... on ProjectV2ItemFieldSingleSelectValue { name } } '
         'content { ... on Issue { number labels(first:20){nodes{name}} } } } } } } }') % PROJECT_ID
    data = _gh_json(["api", "graphql", "-f", "query=" + q])
    if not data:
        return []
    out = []
    for n in data.get("data", {}).get("node", {}).get("items", {}).get("nodes", []):
        content = n.get("content") or {}
        status = (n.get("fieldValueByName") or {}).get("name")
        labels = [x["name"] for x in (content.get("labels") or {}).get("nodes", [])]
        if content.get("number") and status == "In progress" and "epic" in labels:
            out.append(content["number"])
    return out


def _sub_issue_numbers(epic: int) -> list:
    q = ('query { repository(owner:"omniscient", name:"markethawk") { issue(number:%d) { '
         'subIssues(first:50) { nodes { number state labels(first:20){nodes{name}} } } } } }') % epic
    data = _gh_json(["api", "graphql", "-f", "query=" + q])
    if not data:
        return []
    out = []
    for s in data.get("data", {}).get("repository", {}).get("issue", {}).get("subIssues", {}).get("nodes", []):
        labels = [x["name"].lower() for x in (s.get("labels") or {}).get("nodes", [])]
        if s.get("state") == "OPEN" and any(g in labels for g in _GATING_LABELS):
            out.append(s["number"])
    return out


def _fetch_spec_doc(comment_body: str) -> str:
    """Best-effort: pull the linked spec/plan markdown file (path + ref) from a comment."""
    m = re.search(r"/blob/([^/]+)/(\S+?\.md)", comment_body or "")
    if not m:
        return ""
    ref, path = m.group(1), m.group(2)
    data = _gh_json(["api", f"repos/{OWNER}/contents/{path}", "-f", f"ref={ref}", "--jq", ".content"])
    if isinstance(data, str):
        try:
            import base64
            return base64.b64decode(data).decode("utf-8", "replace")
        except Exception:
            return ""
    return ""


def _build_candidate(num: int) -> dict:
    info = _gh_json(["issue", "view", str(num), "--repo", OWNER, "--json", "title,body,labels,comments"])
    if not info:
        return {}
    labels = [x["name"] for x in info.get("labels", [])]
    low = [x.lower() for x in labels]
    status = next((g for g in _GATING_LABELS if g in low), "")
    gen = ""
    for cm in info.get("comments", []):
        if "Spec Generated" in cm.get("body", "") or "Plan Generated" in cm.get("body", ""):
            gen = cm["body"]
    spec_text = "\n\n".join(filter(None, [info.get("body", ""), gen, _fetch_spec_doc(gen)]))
    return {"number": num, "title": info.get("title", ""), "body": info.get("body", ""),
            "labels": labels, "size": None, "status": status, "spec_text": spec_text,
            "target_paths": extract_target_paths(spec_text)}


class LiveIO:
    """Real adapters: gh GraphQL/REST + claude -p + the /api/v1/alerts/system notify endpoint."""

    def __init__(self, model: str):
        self.model = model

    def fetch_candidates(self) -> list:
        cands = []
        for epic in _in_progress_epics():
            for num in _sub_issue_numbers(epic):
                cand = _build_candidate(num)
                if cand:
                    cands.append(cand)
        # oldest issue number first (rough proxy for priority/age)
        return sorted(cands, key=lambda x: x["number"])

    def review(self, prompt: str, model: str) -> str:
        try:
            p = subprocess.run(["claude", "-p", "--model", model], input=prompt,
                               capture_output=True, text=True, timeout=300)
            return p.stdout if p.returncode == 0 else ""
        except Exception:
            return ""

    def advance(self, issue: int) -> None:
        subprocess.run(["gh", "issue", "edit", str(issue), "--repo", OWNER,
                        "--add-label", "direct-to-pr"], check=False)

    def comment(self, issue: int, body: str) -> None:
        subprocess.run(["gh", "issue", "comment", str(issue), "--repo", OWNER, "--body", body], check=False)

    def fetch_ready_epics(self) -> list:
        return _ready_epics()

    def promote_epic(self, epic: int) -> None:
        from factory_core.board import set_board_status
        set_board_status(epic, "In progress")
        for child in _open_child_numbers(epic):
            subprocess.run(["gh", "issue", "edit", str(child), "--repo", OWNER,
                            "--add-label", "ready-for-agent"], check=False)

    def notify(self, title: str, body: str, severity: str, dedupe_key) -> None:
        token = os.environ.get("INTERNAL_API_TOKEN", "")
        if not token:
            return
        payload = {"title": title, "body": body, "severity": severity}
        if dedupe_key:
            payload["dedupe_key"] = dedupe_key
        try:
            req = urllib.request.Request(
                "http://backend:8000/api/v1/alerts/system",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json", "X-Internal-Token": token},
                method="POST")
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass  # fail-soft


def main_once() -> int:
    from datetime import datetime, timezone
    state_dir = os.environ.get("SCHEDULER_STATE_DIR", "/var/lib/dark-factory")
    path = os.path.join(state_dir, "autopilot-state.json")
    try:
        with open(path) as f:
            state = json.load(f)
    except Exception:
        state = {}
    today = datetime.now(timezone.utc).date().isoformat()
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
    try:
        with open(path, "w") as f:
            json.dump(state, f)
    except Exception:
        pass
    print(f"autopilot={out['outcome']} issue=#{out['issue']}")
    return 0
