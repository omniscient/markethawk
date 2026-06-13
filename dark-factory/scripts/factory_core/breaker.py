import json
import os
import subprocess
from pathlib import Path

_DEFAULT_STATE = Path(
    os.environ.get("STATE_FILE", "/var/lib/dark-factory/scheduler-state.json")
)


def get_retry_count(key: str, state_file: Path = _DEFAULT_STATE) -> int:
    if not state_file.exists():
        return 0
    try:
        return int(json.loads(state_file.read_text()).get(key, 0))
    except (json.JSONDecodeError, ValueError, OSError):
        return 0


def increment_retry(key: str, state_file: Path = _DEFAULT_STATE) -> int:
    new = get_retry_count(key, state_file) + 1
    _write_key(key, new, state_file)
    return new


def reset_retry(key: str, state_file: Path = _DEFAULT_STATE) -> None:
    if not state_file.exists():
        return
    try:
        data = json.loads(state_file.read_text())
        data.pop(key, None)
        _atomic_write(state_file, data)
    except (json.JSONDecodeError, OSError):
        pass


def _write_key(key: str, value: int, state_file: Path) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(state_file.read_text()) if state_file.exists() else {}
        data[key] = value
        _atomic_write(state_file, data)
    except (json.JSONDecodeError, OSError):
        pass


def _atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.rename(path)


def _make_key(issue_num: int, phase: str) -> str:
    return str(issue_num) if phase == "implement" else f"{issue_num}:{phase}"


def trip_to_blocked(
    issue_num: int,
    phase: str,
    reason: str,
    state_file: Path = _DEFAULT_STATE,
    owner: str = "omniscient",
    repo: str = "markethawk",
) -> None:
    from .board import set_board_status, STATUS_BLOCKED

    key = _make_key(issue_num, phase)
    attempts = get_retry_count(key, state_file)

    retry_cmds = {
        "refine": f"Refine issue #{issue_num}",
        "plan": f"Plan issue #{issue_num}",
        "resolve": f"Deconflict issue #{issue_num}",
    }
    retry_cmd = retry_cmds.get(phase, f"Fix issue #{issue_num}")

    set_board_status(issue_num, STATUS_BLOCKED)

    for label in ("needs-discussion", "factory-regression"):
        subprocess.run(
            ["gh", "issue", "edit", str(issue_num),
             "--repo", f"{owner}/{repo}", "--add-label", label],
            capture_output=True,
        )

    body = (
        f"## Scheduler — Circuit-Breaker Tripped (`{phase}`)\n\n"
        f"The scheduler attempted **{phase}** **{attempts} time(s)** without success "
        f"and cannot recover automatically.\n\n"
        f"**Reason:** {reason}\n\n"
        "This ticket has been moved to **Blocked** and labelled `needs-discussion` "
        "to pause automation.\n\n"
        "**To resume:**\n"
        "1. Investigate the failure comments above and fix the root cause.\n"
        "2. Remove the `needs-discussion` label — the scheduler resumes on its next poll.\n\n"
        "```bash\n"
        f"# Or re-run manually:\n"
        f'docker compose --profile factory run --rm dark-factory "{retry_cmd}"\n'
        "```\n\n"
        "---\n*Posted by MarketHawk Backlog Scheduler*"
    )
    subprocess.run(
        ["gh", "issue", "comment", str(issue_num),
         "--repo", f"{owner}/{repo}", "--body", body],
        capture_output=True,
    )

    reset_retry(key, state_file)
