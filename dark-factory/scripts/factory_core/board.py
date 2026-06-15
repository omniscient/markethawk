import json
import os
import subprocess
import tempfile

OWNER = "omniscient"
REPO = "markethawk"
PROJECT_NUMBER = 1
PROJECT_ID = "PVT_kwHOAAFds84BWh4w"
STATUS_FIELD = "PVTSSF_lAHOAAFds84BWh4wzhR1VaA"
STATUS_READY = "61e4505c"
STATUS_IN_PROGRESS = "47fc9ee4"
STATUS_IN_REVIEW = "df73e18b"
STATUS_BLOCKED = "93d87b2f"
STATUS_DONE = "98236657"
STATUS_BACKLOG = "f75ad846"
STATUS_REFINED = "0c79ebe5"


def find_board_item(issue_num: int) -> str:
    r = subprocess.run(
        ["gh", "project", "item-list", str(PROJECT_NUMBER),
         "--owner", OWNER, "--format", "json", "--limit", "200"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return ""
    try:
        for item in json.loads(r.stdout).get("items", []):
            c = item.get("content", {})
            if c.get("number") == issue_num and c.get("type") == "Issue":
                return item["id"]
    except (json.JSONDecodeError, KeyError):
        pass
    return ""


def set_board_status(issue_num: int, option_id: str) -> None:
    item_id = find_board_item(issue_num)
    if not item_id:
        return
    subprocess.run(
        ["gh", "project", "item-edit",
         "--project-id", PROJECT_ID,
         "--id", item_id,
         "--field-id", STATUS_FIELD,
         "--single-select-option-id", option_id],
        capture_output=True,
    )


def post_or_update_comment(issue_num: int, marker: str, body: str) -> None:
    r = subprocess.run(
        ["gh", "api", f"repos/{OWNER}/{REPO}/issues/{issue_num}/comments",
         "--jq", f'[.[] | select(.body | contains("{marker}"))] | last | .id // empty'],
        capture_output=True, text=True,
    )
    comment_id = r.stdout.strip() if r.returncode == 0 else ""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as fh:
        fh.write(body)
        tmp = fh.name
    try:
        if comment_id:
            subprocess.run(
                ["gh", "api",
                 f"repos/{OWNER}/{REPO}/issues/comments/{comment_id}",
                 "--method", "PATCH", "-F", f"body=@{tmp}"],
                capture_output=True,
            )
        else:
            subprocess.run(
                ["gh", "issue", "comment", str(issue_num), "--body-file", tmp],
                capture_output=True,
            )
    finally:
        os.unlink(tmp)
