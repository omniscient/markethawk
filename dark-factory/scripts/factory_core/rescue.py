"""factory_core.rescue — un-strand Blocked tickets whose PR is already green.

A ticket can land in **Blocked** (the In-review CI gate, a circuit-breaker trip, or
an orphaned-run sweep) while its PR is actually green, conflict-free, and mergeable.
The Priority-3 retry loop then re-dispatches ``Continue`` on it, which re-runs the
whole factory pipeline — burning the Max 5h session window and re-hitting the same
gate/limit — and once the retry counter is exhausted ``trip_to_blocked`` parks it in
Blocked **permanently**, stranding a perfectly mergeable PR forever.

This module detects that case and promotes the ticket to **In review** so the normal
merge flow (a human, or a ``Close issue #N`` dispatch) can take it, instead of
re-running the factory. It deliberately escalates only to In review — it never merges
(the factory's human-merge / draft-PR policy is preserved).

The scheduler calls ``rescue-blocked --issue N`` once per Blocked item each cycle,
*before* the Priority-3 retry loop, and skips any issue this returns ``rescued`` for.
"""
import json
import subprocess

from factory_core import board

OWNER = board.OWNER
REPO = board.REPO

# Idempotency marker so post_or_update_comment edits one comment instead of spamming.
RESCUE_MARKER = "<!-- df:blocked-rescue -->"


def _repo() -> str:
    return f"{OWNER}/{REPO}"


def pr_for_issue(issue_num: int) -> dict | None:
    """The open PR for an issue's feature branch (feat/issue-<N>-*), or None.

    Returns the first match with the fields rescue needs. ``gh`` is run with
    ``--repo`` because the scheduler executes outside a git checkout.
    """
    r = subprocess.run(
        ["gh", "pr", "list", "--repo", _repo(),
         "--search", f"head:feat/issue-{issue_num}-",
         "--json", "number,isDraft,mergeable"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return None
    try:
        arr = json.loads(r.stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(arr, list) or not arr:
        return None
    return arr[0]


def pr_check_buckets(pr_num: int) -> list:
    """Bucket of every check on a PR ("pass" / "fail" / "pending" / "skipping" / …).

    ``gh pr checks`` exits non-zero when any check is failing or pending, but still
    prints valid JSON on stdout, so the return code is ignored and stdout is parsed
    defensively (empty / non-array ⇒ []).
    """
    r = subprocess.run(
        ["gh", "pr", "checks", str(pr_num), "--repo", _repo(), "--json", "bucket"],
        capture_output=True, text=True,
    )
    try:
        arr = json.loads(r.stdout)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(arr, list):
        return []
    return [c.get("bucket") for c in arr]


def assess(issue_num: int) -> tuple[str, str]:
    """Decide whether a Blocked issue's PR can be rescued.

    Returns ``("rescue", "<pr_num>")`` only when the PR is green (≥1 check, none
    failing, none pending), conflict-free (mergeable == MERGEABLE), so it is genuinely
    ready for the merge flow. Otherwise ``("skip", "<reason>")`` — a no-PR or red /
    pending / conflicting PR is left for the Priority-3 retry loop to drive.
    """
    pr = pr_for_issue(issue_num)
    if not pr:
        return ("skip", "no_pr")
    pr_num = pr["number"]

    buckets = pr_check_buckets(pr_num)
    if not buckets:
        return ("skip", "no_checks")
    if "fail" in buckets:
        return ("skip", "failing_ci")
    if "pending" in buckets:
        return ("skip", "pending_ci")

    if pr.get("mergeable") != "MERGEABLE":
        return ("skip", "mergeable_%s" % (pr.get("mergeable") or "UNKNOWN"))

    return ("rescue", str(pr_num))


def _comment_body(issue_num: int, pr_num: int) -> str:
    return (
        f"{RESCUE_MARKER}\n"
        "## Dark Factory — Rescued from Blocked\n\n"
        f"This ticket was in **Blocked**, but PR #{pr_num} is **green and conflict-free** "
        "(all checks passing, no merge conflicts). Re-running the factory on it would only "
        "burn another session window and re-trip the breaker, so the scheduler promoted it "
        "to **In review** instead — ready for the normal merge flow "
        f"(merge the PR, or dispatch `Close issue #{issue_num}`).\n\n"
        "---\n"
        "*Posted by MarketHawk Backlog Scheduler*"
    )


def rescue_blocked(issue_num: int) -> str:
    """Promote a Blocked issue with a green, mergeable PR to In review.

    Returns ``"rescued"`` when it acts, or ``"skip:<reason>"`` otherwise. A draft PR
    is marked ready first so it is actually mergeable by the normal flow. Never merges.
    """
    action, detail = assess(issue_num)
    if action != "rescue":
        return f"skip:{detail}"
    pr_num = detail

    pr = pr_for_issue(issue_num)
    if pr and pr.get("isDraft"):
        subprocess.run(
            ["gh", "pr", "ready", str(pr_num), "--repo", _repo()],
            capture_output=True,
        )

    board.set_board_status(issue_num, board.STATUS_IN_REVIEW)
    board.post_or_update_comment(issue_num, RESCUE_MARKER, _comment_body(issue_num, int(pr_num)))
    return "rescued"
