#!/usr/bin/env python3
"""Stage 1: pull GitHub issue data + compute metrics → metrics.json

Pulls every issue (all states) and its comments via the ``gh`` CLI, parses the
Dark Factory ``<!-- dark-factory-cost-report -->`` markers, computes delivery
metrics, and writes a committable ``metrics.json`` snapshot. The JSON is the
contract consumed by ``render_report.py`` (stage 2).
"""
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

REPO = "omniscient/markethawk"

# ── regex patterns ────────────────────────────────────────────────────────────
_CUMULATIVE_RE = re.compile(
    r"<!-- cumulative: cost=([0-9.]+) in=(\d+) out=(\d+) -->"
)
_RUN_HEADER_RE = re.compile(
    r"### Run: (\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC) \((\w+),\s*(\w+)\)"
)
# Token columns are written either as plain integers ("56700") or with a "K"
# suffix ("66.2K", "39K") — accept both; ``_tokens_from_str`` normalises them.
_TABLE_ROW_RE = re.compile(
    r"^\s*\|\s*\*{0,2}([^|*]+?)\*{0,2}\s*\|[^|]*\|\s*\*{0,2}([0-9.]+K?)\*{0,2}\s*"
    r"\|\s*\*{0,2}([0-9.]+K?)\*{0,2}\s*\|\s*\*{0,2}\$([0-9.]+)\*{0,2}\s*\|"
)

# ── label helpers ─────────────────────────────────────────────────────────────
_SIZE_RE = re.compile(r"size:\s*([SMLX]+)")
_PRIORITY_RE = re.compile(r"priority:\s*(.+)")


# ── cost-report parsing ───────────────────────────────────────────────────────
def parse_cost_comment(body: str) -> dict | None:
    """Extract cumulative totals from a cost-report comment. Returns None if absent."""
    m = _CUMULATIVE_RE.search(body)
    if not m:
        return None
    return {
        "cost": float(m.group(1)),
        "in_tokens": int(m.group(2)),
        "out_tokens": int(m.group(3)),
    }


def parse_run_headers(body: str) -> list[dict]:
    """Return list of {timestamp, run_type, status} for each run block."""
    return [
        {"timestamp": m.group(1), "run_type": m.group(2), "status": m.group(3)}
        for m in _RUN_HEADER_RE.finditer(body)
    ]


def _tokens_from_str(s: str) -> int:
    """Convert '56.9K' → 56900, '271' → 271, '0' → 0."""
    s = s.strip()
    if s.endswith("K"):
        return int(float(s[:-1]) * 1000)
    if "." in s:
        return int(float(s))
    return int(s)


def parse_step_table(body: str, run_index: int | None = None) -> list[dict]:
    """Return aggregated step costs across all runs (or a specific run_index).

    Each item: {step, in_tokens, out_tokens, cost_usd}
    Subtotal/header rows are excluded from the returned list.
    """
    run_positions = [m.start() for m in _RUN_HEADER_RE.finditer(body)]
    if not run_positions:
        return []
    run_positions.append(len(body))

    if run_index is not None:
        if run_index >= len(run_positions) - 1:
            return []
        slices = [body[run_positions[run_index]:run_positions[run_index + 1]]]
    else:
        slices = [
            body[run_positions[i]:run_positions[i + 1]]
            for i in range(len(run_positions) - 1)
        ]

    aggregated: dict[str, dict] = {}
    for block in slices:
        for line in block.splitlines():
            m = _TABLE_ROW_RE.match(line)
            if not m:
                continue
            step = m.group(1).strip()
            if step.lower() in ("step", "subtotal"):
                continue
            in_tok = _tokens_from_str(m.group(2))
            out_tok = _tokens_from_str(m.group(3))
            cost = float(m.group(4))
            if step in aggregated:
                aggregated[step]["in_tokens"] += in_tok
                aggregated[step]["out_tokens"] += out_tok
                aggregated[step]["cost_usd"] += cost
            else:
                aggregated[step] = {
                    "step": step,
                    "in_tokens": in_tok,
                    "out_tokens": out_tok,
                    "cost_usd": cost,
                }
    return list(aggregated.values())


def compute_cost_by_step(
    issues_raw: list[dict], comments_map: dict[str, list[dict]]
) -> dict[str, float]:
    """Aggregate cost per pipeline step across all cost-report comments."""
    agg: dict[str, float] = {}
    for issue in issues_raw:
        num = str(issue["number"])
        for comment in comments_map.get(num, []):
            body = comment.get("body", "")
            if "<!-- dark-factory-cost-report -->" not in body:
                continue
            for step in parse_step_table(body):
                name = step["step"]
                agg[name] = agg.get(name, 0.0) + step["cost_usd"]
    return {k: round(v, 6) for k, v in sorted(agg.items(), key=lambda x: -x[1])}


# ── datetime helpers ──────────────────────────────────────────────────────────
def _extract_label(labels: list[dict], pattern: re.Pattern) -> str | None:
    for lbl in labels:
        m = pattern.match(lbl["name"])
        if m:
            return m.group(1).strip()
    return None


def _iso_to_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _hours_between(a: str | None, b: str | None) -> float | None:
    da, db = _iso_to_dt(a), _iso_to_dt(b)
    if da is None or db is None:
        return None
    return (db - da).total_seconds() / 3600


def _run_ts_to_dt(ts: str | None) -> datetime | None:
    """Parse a run-header timestamp ('2026-06-04 18:47 UTC').

    Run headers are minute precision, which ``datetime.fromisoformat`` rejects on
    Python < 3.11; parse explicitly so this works on 3.10+.
    """
    if not ts:
        return None
    try:
        return datetime.strptime(ts.strip(), "%Y-%m-%d %H:%M UTC").replace(
            tzinfo=timezone.utc
        )
    except (ValueError, TypeError):
        return None


def _week_key(iso: str) -> str:
    """Return the ISO date of the Monday of the (UTC) week containing ``iso``."""
    d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    monday = d - timedelta(days=d.weekday())
    return monday.strftime("%Y-%m-%d")


def _compute_weekly_timeseries(issues: list[dict]) -> list[dict]:
    created_by_week: dict[str, int] = {}
    closed_by_week: dict[str, int] = {}
    for iss in issues:
        if iss.get("created_at"):
            w = _week_key(iss["created_at"])
            created_by_week[w] = created_by_week.get(w, 0) + 1
        if iss.get("closed_at"):
            w = _week_key(iss["closed_at"])
            closed_by_week[w] = closed_by_week.get(w, 0) + 1
    all_weeks = sorted(set(list(created_by_week) + list(closed_by_week)))
    backlog = 0
    cum = 0
    result = []
    for w in all_weeks:
        cr = created_by_week.get(w, 0)
        cl = closed_by_week.get(w, 0)
        backlog += cr - cl
        cum += cl
        result.append(
            {
                "week": w,
                "created": cr,
                "closed": cl,
                "cum_closed": cum,
                "backlog": max(0, backlog),
            }
        )
    return result


# ── metrics computation ───────────────────────────────────────────────────────
def build_issue_metrics(
    issues: list[dict], comments_map: dict[str, list[dict]]
) -> dict:
    """Compute full metrics dict from raw issue list + comments map.

    comments_map keys are str(issue_number). Returns the metrics.json structure.
    """
    processed = []
    total_cost = 0.0
    autonomous_count = 0

    for issue in issues:
        num = issue["number"]
        labels = issue.get("labels", [])
        comments = comments_map.get(str(num), [])

        cost_info = None
        runs = []
        for c in comments:
            body = c.get("body", "")
            if "<!-- dark-factory-cost-report -->" in body:
                cost_info = parse_cost_comment(body)
                runs = parse_run_headers(body)
                break

        autonomous = cost_info is not None
        if autonomous:
            autonomous_count += 1
            total_cost += cost_info["cost"]

        lead_time = _hours_between(issue.get("createdAt"), issue.get("closedAt"))

        first_run_dt = _run_ts_to_dt(runs[0]["timestamp"]) if runs else None
        closed_dt = _iso_to_dt(issue.get("closedAt"))
        factory_cycle = (
            (closed_dt - first_run_dt).total_seconds() / 3600
            if first_run_dt and closed_dt
            else None
        )

        processed.append(
            {
                "number": num,
                "title": issue["title"],
                "state": issue["state"],
                "created_at": issue.get("createdAt"),
                "closed_at": issue.get("closedAt"),
                "lead_time_hours": lead_time,
                "factory_cycle_hours": factory_cycle,
                "labels": [lbl["name"] for lbl in labels],
                "size": _extract_label(labels, _SIZE_RE),
                "priority": _extract_label(labels, _PRIORITY_RE),
                "autonomous": autonomous,
                "cost": {
                    "total_usd": cost_info["cost"],
                    "in_tokens": cost_info["in_tokens"],
                    "out_tokens": cost_info["out_tokens"],
                    "runs": runs,
                }
                if cost_info
                else None,
            }
        )

    closed = [i for i in processed if i["state"] == "CLOSED"]
    lead_times = sorted(
        [i["lead_time_hours"] for i in closed if i["lead_time_hours"] is not None]
    )
    median_lt = lead_times[len(lead_times) // 2] if lead_times else None
    p85_lt = lead_times[int(len(lead_times) * 0.85)] if lead_times else None

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_issues": len(issues),
            "closed_issues": len(closed),
            "open_issues": len(issues) - len(closed),
            "autonomous_issues": autonomous_count,
            "pct_autonomous": round(autonomous_count / len(issues) * 100, 1)
            if issues
            else 0,
            "total_cost_usd": round(total_cost, 4),
            "avg_cost_per_ticket": round(total_cost / autonomous_count, 4)
            if autonomous_count
            else 0,
            "median_lead_time_hours": median_lt,
            "p85_lead_time_hours": p85_lt,
        },
        "issues": processed,
        "cost_by_step": compute_cost_by_step(issues, comments_map),
        "timeseries": {"weekly": _compute_weekly_timeseries(processed)},
    }


# ── GitHub data fetching ───────────────────────────────────────────────────────
def _gh(*args: str) -> list | dict:
    # gh emits UTF-8; force it so Windows' locale codec (cp1252) doesn't choke on
    # the em-dashes/box-drawing chars in cost-report comments.
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def fetch_all_issues() -> list[dict]:
    return _gh(
        "issue", "list", "--repo", REPO,
        "--state", "all", "--limit", "1000",
        "--json", "number,title,state,createdAt,closedAt,labels",
    )


def fetch_issue_comments(number: int) -> list[dict]:
    data = _gh(
        "issue", "view", str(number), "--repo", REPO,
        "--json", "comments",
    )
    return data.get("comments", [])


def build_comments_map(issues: list[dict]) -> dict[str, list[dict]]:
    """Fetch comments for all issues; print progress to stderr."""
    result = {}
    for i, issue in enumerate(issues, 1):
        num = issue["number"]
        print(f"  [{i}/{len(issues)}] fetching comments for #{num}", file=sys.stderr)
        result[str(num)] = fetch_issue_comments(num)
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="metrics.json")
    args = parser.parse_args()

    print("Fetching issues…", file=sys.stderr)
    issues = fetch_all_issues()
    print(f"  {len(issues)} issues found", file=sys.stderr)

    print("Fetching comments…", file=sys.stderr)
    comments_map = build_comments_map(issues)

    print("Computing metrics…", file=sys.stderr)
    metrics = build_issue_metrics(issues, comments_map)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, default=str)
    print(f"Wrote {args.output}", file=sys.stderr)
