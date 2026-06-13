# Implementation Plan: Dedupe Scope-Enforcement Findings Before Filing Tickets

**Date:** 2026-06-13
**Issue:** #384
**Spec:** [docs/superpowers/specs/2026-06-13-dedupe-scope-enforcement-findings-design.md](../specs/2026-06-13-dedupe-scope-enforcement-findings-design.md)
**Branch:** `refine/issue-384-factory--dedupe-scope-enforcement-findin`

---

## Goal

Add a dedupe pre-processing step to the dark-factory conformance gate's scope-enforcement stage that classifies each `[OOS]` entry as `create`, `comment:<num>`, or `suppress` before the ticket-filing loop runs. Prevents within-run and cross-run duplicate `scope-spillover` tickets and suppresses non-actionable ruff-reformat findings.

## Architecture

New pure-Python script `dark-factory/scripts/dedupe_oos.py` (JSON I/O, fail-open, no side effects) slots between the OOS extraction step and the `gh issue create` loop in `.archon/commands/dark-factory-conformance.md` Phase 3.6.2. Follows the exact I/O and fail-open contract established by `fmt_hunk_filter.py`.

New spillover issue bodies embed `<!-- dedup-key: <file/area>|<finding-type> -->` for reliable cross-run matching; a best-effort fallback handles legacy keyless issues.

## Tech Stack

- **Runtime**: Python 3 (already in dark-factory container — used by `fmt_hunk_filter.py`, `gate_blast_radius.py`)
- **Tests**: pytest, direct function-call style (no subprocess for unit tests)
- **Integration**: `.archon/commands/dark-factory-conformance.md` shell block

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `dark-factory/scripts/dedupe_oos.py` | Create | OOS entry deduplication classifier (pure Python, JSON I/O, fail-open) |
| `dark-factory/tests/test_dedupe_oos.py` | Create | 4 behavioral unit tests for `dedupe_oos.py` |
| `.archon/commands/dark-factory-conformance.md` | Modify | Replace Phase 3.6.2 create loop with dedupe-aware Step A/B/C block |
| `dark-factory/tests/test_conformance_dedupe_step.py` | Create | Marker tests asserting `dedupe_oos.py` is wired into the conformance command file |

---

## Task 1: Create `dedupe_oos.py` with unit tests (TDD)

**Files:** `dark-factory/tests/test_dedupe_oos.py`, `dark-factory/scripts/dedupe_oos.py`

### Step 1.1 — Write failing tests

Create `dark-factory/tests/test_dedupe_oos.py`:

```python
"""
Tests for dark-factory/scripts/dedupe_oos.py.

classify_entry and classify_all are tested directly with synthetic inputs.
No subprocess or gh calls needed — the script is pure Python with JSON I/O.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import dedupe_oos  # noqa: E402


def test_suppress_ruff_reformat_class():
    """Findings with ruff/reformat keywords are suppressed before key creation."""
    entries = ["[OOS] backend/app/services/scanner.py — cosmetic ruff reformatting applied by formatter"]
    results = dedupe_oos.classify_all(entries, [])
    assert len(results) == 1
    assert results[0]["action"] == "suppress"
    assert results[0]["key"].endswith("|ruff-reformat")


def test_within_run_dedup():
    """Two entries sharing the same (file, finding-type) key: first creates, second suppresses."""
    entries = [
        "[OOS] frontend/src/components/Chart.tsx — TypeScript TS2322 type mismatch on line 42",
        "[OOS] frontend/src/components/Chart.tsx — TypeScript TS2322 type error at prop assignment",
    ]
    results = dedupe_oos.classify_all(entries, [])
    assert len(results) == 2
    assert results[0]["action"] == "create"
    assert results[1]["action"] == "suppress"
    assert results[0]["key"] == results[1]["key"]


def test_cross_run_dedup_via_embedded_key():
    """Entry matching an open issue's embedded dedup-key gets comment action, not create."""
    entries = [
        "[OOS] frontend/src/components/Chart.tsx — TypeScript TS2322 type mismatch",
    ]
    spillovers = [
        {
            "number": 305,
            "title": "Add frontend test coverage for Chart.tsx",
            "body": (
                "## Scope spillover from #250\n\n"
                "**File/area:** frontend/src/components/Chart.tsx\n"
                "**Defect:** TypeScript TS2322 type error\n\n"
                "<!-- dedup-key: frontend/src/components/chart.tsx|ts-type-error -->\n\n"
                "---\n*Automatically triaged by MarketHawk Dark Factory scope enforcement.*"
            ),
        }
    ]
    results = dedupe_oos.classify_all(entries, spillovers)
    assert len(results) == 1
    assert results[0]["action"] == "comment:305"
    assert results[0]["key"] == "frontend/src/components/chart.tsx|ts-type-error"


def test_genuinely_new_finding_returns_create():
    """Entry with no matching key in existing issues produces create action."""
    entries = [
        "[OOS] backend/app/models/trade.py — missing Alembic migration for new nullable column",
    ]
    spillovers = [
        {
            "number": 99,
            "title": "Unrelated old issue",
            "body": (
                "Some body\n"
                "<!-- dedup-key: frontend/src/other.tsx|missing-test -->\n"
            ),
        }
    ]
    results = dedupe_oos.classify_all(entries, spillovers)
    assert len(results) == 1
    assert results[0]["action"] == "create"
    assert results[0]["key"] == "backend/app/models/trade.py|missing-migration"
```

### Step 1.2 — Verify tests fail

```bash
cd /workspace/markethawk && python3 -m pytest dark-factory/tests/test_dedupe_oos.py -v 2>&1 | head -20
```

Expected output: `ModuleNotFoundError: No module named 'dedupe_oos'`

### Step 1.3 — Implement `dark-factory/scripts/dedupe_oos.py`

```python
"""
OOS entry deduplication classifier for dark-factory conformance scope enforcement.

Usage:
    python3 dedupe_oos.py --oos '<json array>' --spillovers '<json array>'

Classifies each [OOS] entry as:
  create      - no existing match; file a new ticket
  comment:<n> - existing issue <n> has the same embedded dedup-key; post a comment
  suppress    - ruff-reformat class or within-run duplicate; drop silently

Exits 0 on success (JSON to stdout). Exits non-zero on error (message to stderr).
Caller must handle non-zero exit as fail-open fallback (no finding silently lost).
"""
import argparse
import json
import re
import sys

SUPPRESSION_KEYWORDS = [
    "ruff",
    "reformat",
    "formatter",
    "isort",
    "import order",
    "import-ordering",
    "whitespace rewrap",
]

FINDING_TYPES = {
    "ts-type-error":     ["ts2322", "ts2345", "ts type", "typescript", "type error", "type mismatch"],
    "missing-test":      ["missing test", "test coverage", "no test", "untested", "out-of-scope test"],
    "seed-drift":        ["seed", "seed file", "seed drift", "default config", "default value"],
    "unused-import":     ["unused import", "import not used", "f401"],
    "lint-error":        ["lint", "pylint", "flake8", "mypy"],
    "missing-migration": ["migration", "alembic", "schema change"],
    "ts-missing-type":   ["ts2339", "ts2304", "property does not exist", "cannot find name"],
    "ruff-reformat":     ["ruff", "reformat", "formatter", "isort", "import order", "import-ordering"],
}


def _normalize_slug(text, max_len=50):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower().strip())[:max_len]
    return slug.strip("-")


def classify_entry(entry, seen_keys, spillovers):
    """
    Classify one [OOS] entry. Returns dict with 'entry', 'action', 'key'.
    Modifies seen_keys in place for within-run dedup.
    """
    # Parse: split on first em-dash separator, fall back to hyphen-dash
    if " — " in entry:
        parts = entry.split(" — ", 1)
    elif " - " in entry:
        parts = entry.split(" - ", 1)
    else:
        parts = [entry, entry]

    file_or_area = parts[0]
    if file_or_area.upper().startswith("[OOS]"):
        file_or_area = file_or_area[5:].strip()
    description = parts[1] if len(parts) > 1 else entry

    # Step 2: Suppression check — raw keyword scan before normalization
    desc_lower = description.lower()
    for kw in SUPPRESSION_KEYWORDS:
        if kw in desc_lower:
            key = f"{file_or_area.lower()}|ruff-reformat"
            return {"entry": entry, "action": "suppress", "key": key}

    # Step 3: Finding-type extraction (first-match wins; skip ruff-reformat safety net)
    finding_type = None
    for type_name, keywords in FINDING_TYPES.items():
        if type_name == "ruff-reformat":
            continue
        for kw in keywords:
            if kw in desc_lower:
                finding_type = type_name
                break
        if finding_type:
            break
    if finding_type is None:
        slug = _normalize_slug(description[:50])
        finding_type = slug if slug else "other"

    # Step 4: Build normalized key
    key = f"{file_or_area.lower()}|{finding_type}"

    # Step 5: Within-run dedup
    if key in seen_keys:
        return {"entry": entry, "action": "suppress", "key": key}
    seen_keys.add(key)

    # Step 6: Cross-run dedup — primary path via embedded dedup-key
    for issue in spillovers:
        body = issue.get("body") or ""
        m = re.search(r"<!--\s*dedup-key:\s*([^>]+?)\s*-->", body)
        if m and m.group(1).strip() == key:
            return {"entry": entry, "action": f"comment:{issue['number']}", "key": key}

    # Best-effort fallback for keyless legacy issues (advisory; may miss)
    for issue in spillovers:
        body = issue.get("body") or ""
        if re.search(r"<!--\s*dedup-key:", body):
            continue  # has a key but didn't match; skip fallback for keyed issues
        fa_match = re.search(r"\*\*File/area:\*\*\s*(.+)", body)
        if fa_match:
            fa_norm = fa_match.group(1).strip().lower()
            if fa_norm and fa_norm in file_or_area.lower():
                return {"entry": entry, "action": f"comment:{issue['number']}", "key": key}

    return {"entry": entry, "action": "create", "key": key}


def classify_all(oos_entries, spillovers):
    """Classify all OOS entries. Returns list of action dicts."""
    seen_keys = set()
    return [classify_entry(entry, seen_keys, spillovers) for entry in oos_entries]


def main():
    parser = argparse.ArgumentParser(description="OOS entry deduplication classifier")
    parser.add_argument("--oos", required=True, help="JSON array of OOS entry strings")
    parser.add_argument("--spillovers", required=True,
                        help="JSON array of existing open scope-spillover issue objects")
    args = parser.parse_args()

    oos_entries = json.loads(args.oos)
    spillovers = json.loads(args.spillovers)
    results = classify_all(oos_entries, spillovers)
    print(json.dumps(results))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"dedupe_oos.py error: {e}", file=sys.stderr)
        sys.exit(1)
```

### Step 1.4 — Verify tests pass

```bash
cd /workspace/markethawk && python3 -m pytest dark-factory/tests/test_dedupe_oos.py -v
```

Expected output:
```
PASSED dark-factory/tests/test_dedupe_oos.py::test_suppress_ruff_reformat_class
PASSED dark-factory/tests/test_dedupe_oos.py::test_within_run_dedup
PASSED dark-factory/tests/test_dedupe_oos.py::test_cross_run_dedup_via_embedded_key
PASSED dark-factory/tests/test_dedupe_oos.py::test_genuinely_new_finding_returns_create
4 passed
```

### Step 1.5 — Commit

```bash
git add dark-factory/scripts/dedupe_oos.py dark-factory/tests/test_dedupe_oos.py
git commit -m "feat(#384): add dedupe_oos.py OOS entry deduplication classifier

Pure-Python script that classifies each [OOS] entry as create/comment/suppress
before the ticket-filing loop runs. Includes FINDING_TYPES registry, within-run
and cross-run dedup (embedded dedup-key primary; best-effort fallback for legacy
keyless issues), ruff-reformat suppression, and fail-open exit contract."
```

---

## Task 2: Wire `dedupe_oos.py` into conformance Phase 3.6.2

**Files:** `dark-factory/tests/test_conformance_dedupe_step.py`, `.archon/commands/dark-factory-conformance.md`

### Step 2.1 — Write failing marker tests

Create `dark-factory/tests/test_conformance_dedupe_step.py`:

```python
from pathlib import Path

CMD = (
    Path(__file__).resolve().parents[2]
    / ".archon" / "commands" / "dark-factory-conformance.md"
)


def test_conformance_dedupe_wired():
    """Phase 3.6.2 must invoke dedupe_oos.py."""
    text = CMD.read_text(encoding="utf-8")
    assert "dedupe_oos.py" in text, "Phase 3.6.2 must invoke dedupe_oos.py"


def test_conformance_dedupe_embeds_dedup_key():
    """New spillover issue bodies must embed a dedup-key HTML comment."""
    text = CMD.read_text(encoding="utf-8")
    assert "dedup-key" in text, \
        "Spillover issue body template must include '<!-- dedup-key: ... -->'"


def test_conformance_dedupe_fetches_spillovers():
    """Phase 3.6.2 must fetch existing open spillover issues before calling dedupe_oos.py."""
    text = CMD.read_text(encoding="utf-8")
    assert "SPILLOVER_JSON" in text, \
        "Phase 3.6.2 must fetch open spillover issues into SPILLOVER_JSON"


def test_conformance_dedupe_action_list():
    """Phase 3.6.2 must process an ACTION_LIST from dedupe_oos.py output."""
    text = CMD.read_text(encoding="utf-8")
    assert "ACTION_LIST" in text, \
        "Phase 3.6.2 must build ACTION_LIST from dedupe_oos.py output"
```

### Step 2.2 — Verify marker tests fail

```bash
cd /workspace/markethawk && python3 -m pytest dark-factory/tests/test_conformance_dedupe_step.py -v 2>&1 | head -20
```

Expected: `FAILED ... AssertionError: Phase 3.6.2 must invoke dedupe_oos.py`

### Step 2.3 — Update Phase 3.6.2 in `.archon/commands/dark-factory-conformance.md`

Replace the existing Phase 3.6.2 block (from `### 3.6.2 — Create backlog ticket` through `Collect all created ticket numbers into \`SPILLOVER_TICKETS\` (space-separated list).`) with:

```markdown
### 3.6.2 — Create backlog ticket

Before filing tickets, deduplicate OOS entries against each other and against the
existing `scope-spillover` backlog.

**Populate `OOS_ENTRIES` array from `$CONFORMANCE_DIALOGUE`** (the accumulated reviewer output
set in Phase 3.1 step 5 and appended on each reconcile cycle):

```bash
OOS_ENTRIES=()
while IFS= read -r line; do
  stripped="${line#- }"
  [[ "$stripped" == \[OOS\]* ]] && OOS_ENTRIES+=("$stripped")
done <<< "$CONFORMANCE_DIALOGUE"
```

Skip to 3.6.3 if `${#OOS_ENTRIES[@]} -eq 0`.

**Step A — Fetch existing open spillover issues:**

```bash
SPILLOVER_JSON=$(gh issue list \
  --repo omniscient/markethawk \
  --label "$BACKLOG_LABEL" \
  --state open \
  --json number,title,body \
  --limit 200 2>/dev/null || echo "[]")
```

**Step B — Build OOS JSON array and call `dedupe_oos.py` (fail-open):**

```bash
OOS_ENTRIES_JSON=$(python3 -c \
  "import json,sys; entries=sys.argv[1:]; print(json.dumps(entries))" \
  "${OOS_ENTRIES[@]}")

DEDUPE_OUT=$(python3 dark-factory/scripts/dedupe_oos.py \
  --oos "$OOS_ENTRIES_JSON" --spillovers "$SPILLOVER_JSON" 2>/tmp/dedupe_err.txt) \
  && ACTION_LIST="$DEDUPE_OUT" \
  || {
    echo "dedupe_oos.py failed ($(cat /tmp/dedupe_err.txt)) — falling back to create-per-finding"
    ACTION_LIST=$(echo "$OOS_ENTRIES_JSON" | python3 -c \
      "import json,sys; print(json.dumps([{'entry':e,'action':'create','key':''} for e in json.load(sys.stdin)]))")
  }
```

**Step C — Process actions (whether excision succeeded or not):**

Use process substitution so `SPILLOVER_TICKETS` mutations survive outside the loop:

```bash
SPILLOVER_TICKETS=""

while IFS='|' read -r ACTION ENTRY KEY; do
  case "$ACTION" in
    create)
      SPILLOVER_TITLE="<short title derived from ENTRY>"
      DEDUP_KEY_COMMENT="<!-- dedup-key: ${KEY} -->"
      SPILLOVER_BODY="## Scope spillover from #${ISSUE_NUM}

The dark factory noticed this pre-existing defect while implementing issue #${ISSUE_NUM} but did not fix it inline (scope enforcement).

**File/area:** <file from ENTRY>
**Defect:** <description from ENTRY>

${DEDUP_KEY_COMMENT}

---
*Automatically triaged by MarketHawk Dark Factory scope enforcement.*"

      SPILLOVER_URL=$(gh issue create \
        --repo omniscient/markethawk \
        --title "$SPILLOVER_TITLE" \
        --body "$SPILLOVER_BODY" \
        --label "needs-triage,${BACKLOG_LABEL}")
      SPILLOVER_NUM=$(basename "$SPILLOVER_URL")
      SPILLOVER_TICKETS="$SPILLOVER_TICKETS $SPILLOVER_NUM"
      echo "scope-enforcement: created new spillover #${SPILLOVER_NUM} (key: $KEY)"
      ;;
    comment:*)
      EXISTING_NUM="${ACTION#comment:}"
      gh issue comment "$EXISTING_NUM" \
        --repo omniscient/markethawk \
        --body "**Scope enforcement (re-observed):** This finding was re-surfaced while implementing issue #${ISSUE_NUM}.

**Entry:** ${ENTRY}

No new ticket created — deduped against this issue."
      echo "scope-enforcement: commented on existing spillover #${EXISTING_NUM} (key: $KEY)"
      ;;
    suppress)
      echo "scope-enforcement: suppressed non-actionable finding (key: $KEY): $ENTRY"
      ;;
  esac
done < <(echo "$ACTION_LIST" | python3 -c \
  "import json,sys; [print(r['action']+'|'+r['entry']+'|'+r.get('key','')) for r in json.load(sys.stdin)]")
```

Collect all created ticket numbers into `SPILLOVER_TICKETS` (space-separated list).
```

### Step 2.4 — Verify marker tests pass

```bash
cd /workspace/markethawk && python3 -m pytest dark-factory/tests/test_conformance_dedupe_step.py -v
```

Expected output:
```
PASSED dark-factory/tests/test_conformance_dedupe_step.py::test_conformance_dedupe_wired
PASSED dark-factory/tests/test_conformance_dedupe_step.py::test_conformance_dedupe_embeds_dedup_key
PASSED dark-factory/tests/test_conformance_dedupe_step.py::test_conformance_dedupe_fetches_spillovers
PASSED dark-factory/tests/test_conformance_dedupe_step.py::test_conformance_dedupe_action_list
4 passed
```

### Step 2.5 — Run full dark-factory test suite to confirm no regressions

```bash
cd /workspace/markethawk && python3 -m pytest dark-factory/tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all existing tests pass plus 8 new tests (4 behavioral + 4 marker).

### Step 2.6 — Commit

```bash
git add .archon/commands/dark-factory-conformance.md \
        dark-factory/tests/test_conformance_dedupe_step.py
git commit -m "feat(#384): wire dedupe_oos.py into conformance Phase 3.6.2

Replace per-entry gh issue create loop with dedupe-aware Step A/B/C block:
fetch open spillovers → classify via dedupe_oos.py (fail-open) → act on
create/comment/suppress per entry. New spillover bodies embed
<!-- dedup-key: file|finding-type --> for reliable future cross-run matching."
```

---

## Summary

| Task | Files | Steps |
|------|-------|-------|
| 1. Create dedupe_oos.py | `scripts/dedupe_oos.py`, `tests/test_dedupe_oos.py` | 5 |
| 2. Wire into conformance | `dark-factory-conformance.md`, `tests/test_conformance_dedupe_step.py` | 6 |

**Total:** 2 tasks, 11 steps

---

*Plan generated by MarketHawk Refinement Pipeline — 2026-06-13*
