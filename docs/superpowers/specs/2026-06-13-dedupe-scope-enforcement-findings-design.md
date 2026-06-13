# Dedupe Scope-Enforcement Findings Before Filing Tickets

**Date:** 2026-06-13
**Issue:** #384
**Status:** Spec

---

## Problem

The conformance gate's scope-enforcement stage (`dark-factory-conformance.md` Phase 3.6) fires a `gh issue create` for every `[OOS]` bullet the reviewer emits, with no deduplication against the existing backlog. This inflates the `scope-spillover` label with redundant tickets and buries genuine work:

1. **Within-run duplicates** — the same pre-existing defect is described twice in one reviewer output (same file, same error class), producing sibling tickets from a single run.
2. **Cross-run duplicates** — a later conformance run on a different issue detects the same pre-existing defect and files a second (or sixth) ticket for it.
3. **Ruff-reformat spillovers** — non-actionable cosmetic formatter findings make it past the existing `fmt_hunk_filter.py` pre-triage step (often via `$ARTIFACTS_DIR/out-of-scope.md` recorded by the implement agent) and are filed as scope-spillover tickets even though no human action is possible.

---

## Requirements

1. Within-run finding list is deduped on `(file/area, finding-type)` before any ticket is filed.
2. Cross-run: existing open `scope-spillover` issue with a matching normalized key gets a comment referencing the new run — no new sibling ticket.
3. Ruff-reformat-of-touched-files findings are suppressed entirely; they never reach the ticket-filing loop.
4. New spillover issue bodies embed `<!-- dedup-key: <file/area>|<finding-type> -->` so future runs can match reliably without LLM title-interpretation.
5. The script is **fail-open**: any error in `dedupe_oos.py` falls back to the existing per-finding `gh issue create` behavior (no finding is silently lost).
6. Unit tests cover: cross-run dup via embedded key, within-run dup, genuinely-new finding, suppressed ruff-reformat class.

---

## Architecture / Approach

### New file: `dark-factory/scripts/dedupe_oos.py`

A pure-Python, side-effect-free helper that classifies each `[OOS]` entry into one of three actions. Follows the exact I/O and fail-open contract established by `fmt_hunk_filter.py`.

#### Input (via `--oos` and `--spillovers` JSON args or stdin pipe):

```
--oos       JSON array of OOS entry strings, e.g.:
              ["[OOS] frontend/src/components/Chart.tsx — TypeScript TS2322 …",
               "[OOS] backend/app/services/scanner.py — ruff reformatting …"]

--spillovers JSON array of existing open scope-spillover issues:
              [{"number": 305, "title": "…", "body": "…"}, …]
              (from `gh issue list --label scope-spillover --state open --json number,title,body`)
```

#### Output (stdout, JSON):

```json
[
  {"entry": "[OOS] …", "action": "create",      "key": "frontend/src/components/chart.tsx|ts-type-error"},
  {"entry": "[OOS] …", "action": "comment:305",  "key": "frontend/src/components/chart.tsx|ts-type-error"},
  {"entry": "[OOS] …", "action": "suppress",     "key": "backend/app/services/scanner.py|ruff-reformat"}
]
```

`action` values:
- `"create"` — no existing match; file a new ticket
- `"comment:<num>"` — existing open issue `<num>` has the same key; post a comment instead
- `"suppress"` — ruff-reformat class; drop silently

#### Normalization pipeline (per entry):

1. **Parse** — split on first ` — ` to extract `file_or_area` and `description`.
2. **Suppression check** — if `description` contains any of: `ruff`, `reformat`, `formatter`, `isort`, `import order`, `import-ordering`, `whitespace rewrap` → action = `suppress`, stop.
3. **Finding-type extraction** — match `description` (case-insensitive) against `FINDING_TYPES` registry (first-match wins):

   ```python
   FINDING_TYPES = {
       "ts-type-error":       ["ts2322", "ts2345", "ts type", "typescript", "type error", "type mismatch"],
       "missing-test":        ["missing test", "test coverage", "no test", "untested", "out-of-scope test"],
       "seed-drift":          ["seed", "seed file", "seed drift", "default config", "default value"],
       "unused-import":       ["unused import", "import not used", "f401"],
       "lint-error":          ["lint", "pylint", "flake8", "mypy"],
       "missing-migration":   ["migration", "alembic", "schema change"],
       "ts-missing-type":     ["ts2339", "ts2304", "property does not exist", "cannot find name"],
       "ruff-reformat":       ["ruff", "reformat", "formatter", "isort", "import order", "import-ordering"],
   }
   # fallback: normalized slug of first 50 chars of description
   ```

   Note: `ruff-reformat` in the registry is a redundant safety net — suppression (step 2) should already catch these before normalization.

4. **Key** = `<lowercase(file_or_area)>|<finding-type>`.
5. **Within-run dedup** — track `seen_keys` set across entries; if key already in `seen_keys`, merge (use the first entry's key, discard the duplicate). Only one `create` per key per run.
6. **Cross-run dedup**:
   - Extract `<!-- dedup-key: ... -->` from each existing spillover issue body (primary path).
   - If no key found in body, attempt best-effort match: parse `**File/area:**` line and normalize the title (secondary path, advisory only — may miss).
   - If a match found → action = `"comment:<num>"` (lowest-numbered open issue wins on tie).

#### Fail-open contract

The script exits 0 on success with JSON to stdout. On any exception, it exits non-zero and prints an error to stderr. The calling shell must handle this:

```bash
DEDUPE_OUT=$(python3 dark-factory/scripts/dedupe_oos.py \
  --oos "$OOS_JSON" --spillovers "$SPILLOVER_JSON" 2>/tmp/dedupe_err.txt) \
  && ACTION_LIST="$DEDUPE_OUT" \
  || {
    echo "dedupe_oos.py failed ($(cat /tmp/dedupe_err.txt)) — falling back to create-per-finding"
    # Fall back: action="create" for every entry, no dedup
    ACTION_LIST=$(echo "$OOS_ENTRIES_JSON" | python3 -c \
      "import json,sys; print(json.dumps([{'entry':e,'action':'create','key':''} for e in json.load(sys.stdin)]))")
  }
```

---

### Changes to `dark-factory-conformance.md` Phase 3.6.2

Replace the existing `gh issue create` loop with a three-step block:

**Step A — Fetch existing open spillover issues:**
```bash
SPILLOVER_JSON=$(gh issue list \
  --repo omniscient/markethawk \
  --label "$BACKLOG_LABEL" \
  --state open \
  --json number,title,body \
  --limit 200 2>/dev/null || echo "[]")
```

**Step B — Call dedupe_oos.py (fail-open):**
```bash
OOS_ENTRIES_JSON=$(printf '%s\n' "${OOS_ENTRIES[@]}" | python3 -c \
  "import json,sys; print(json.dumps(sys.stdin.read().splitlines()))")

DEDUPE_OUT=$(python3 dark-factory/scripts/dedupe_oos.py \
  --oos "$OOS_ENTRIES_JSON" --spillovers "$SPILLOVER_JSON" 2>/tmp/dedupe_err.txt) \
  && ACTION_LIST="$DEDUPE_OUT" \
  || {
    echo "dedupe_oos.py failed — falling back to create-per-finding"
    ACTION_LIST=$(echo "$OOS_ENTRIES_JSON" | python3 -c \
      "import json,sys; print(json.dumps([{'entry':e,'action':'create','key':''} for e in json.load(sys.stdin)]))")
  }
```

**Step C — Process actions:**
```bash
SPILLOVER_TICKETS=""

echo "$ACTION_LIST" | python3 -c "import json,sys; [print(r['action']+'|'+r['entry']+'|'+r.get('key','')) for r in json.load(sys.stdin)]" \
| while IFS='|' read -r ACTION ENTRY KEY; do
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

      SPILLOVER_NUM=$(gh issue create \
        --repo omniscient/markethawk \
        --title "$SPILLOVER_TITLE" \
        --body "$SPILLOVER_BODY" \
        --label "needs-triage,${BACKLOG_LABEL}" \
        --json number --jq '.number')
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
done
```

---

### New test file: `dark-factory/tests/test_dedupe_oos.py`

Four required test scenarios (table-driven, pure Python — no `gh` calls):

| Test case | Input | Expected action |
|-----------|-------|----------------|
| Ruff-reformat class | `[OOS] backend/app/foo.py — cosmetic ruff reformatting` | `suppress` |
| Within-run dup | Two entries with same file + `ts-type-error` | First → `create`, second → merged (only one create) |
| Cross-run dup (key match) | Entry + open issue body containing `<!-- dedup-key: frontend/src/chart.tsx\|ts-type-error -->` | `comment:<num>` |
| Genuinely new finding | Entry with no matching key in existing issues | `create` |

Tests use `subprocess.run` or direct function calls on the script's logic, consistent with `test_fmt_hunk_filter.py`'s approach.

---

## Alternatives Considered

### A: Inline shell in `dark-factory-conformance.md`

Extend Phase 3.6.2 with bash `gh issue list | grep` matching and string normalization. Rejected because:
- The command file is already 383 lines; adding complex string-processing logic makes it unreadable.
- The acceptance criteria require behavioral unit tests (four test cases) — bash string-munging in a markdown command file cannot be tested at that level. Existing conformance tests (`test_conformance_formatter_step.py`) only grep the markdown for marker strings, not behavior.
- Bash normalization of LLM-generated descriptions is inherently fragile. Python is the right tool.

### B: LLM extraction of finding-type in the conformance reviewer prompt

Ask the conformance reviewer subagent to emit a machine-readable `<!-- dedup-key: ... -->` annotation alongside each `[OOS]` bullet.
Rejected because:
- The conformance reviewer is the stage already emitting duplicate-but-differently-phrased descriptions. Trusting the same LLM to assign stable keys moves the drift problem from descriptions into keys.
- Adds complexity to a prompt already responsible for spec conformance review.
- Violates the isolation principle: parsing/classification belongs in deterministic code, not in the agent's output.

### C: Title-only matching (no embedded key)

Normalize existing issue titles and fuzzy-match against new findings. Rejected because:
- LLM-generated titles drift significantly between runs (confirmed by #305-#316 cluster).
- Produces false positives (over-matching distinct findings) and false negatives (missing same finding with different phrasing).
- The embedded key approach costs one additional line in the issue body template and gives a reliable machine contract.

---

## Open Questions (non-blocking)

1. **Legacy dedup coverage** — the ~30 open `scope-spillover` issues created before this feature deployed lack `<!-- dedup-key: -->`. The best-effort fallback (parse `**File/area:**` + title) is intentionally lossy. Manual triage (already underway for #305-#316) is the correct path for the existing backlog; the script's job is to prevent new duplicates.

2. **FINDING_TYPES registry drift** — new error classes not in the registry fall back to a normalized description slug. Two runs that phrase the same novel error differently will still file two tickets. The registry can be extended over time; `other` is not a canonical type that would cause false deduplication.

3. **Legacy spillover issues without the key** — the best-effort title/`**File/area:**` fallback path may misfire on unusual titles. Per Q2 discussion, this path is advisory and its failures are acceptable.

---

## Assumptions

- `[OOS]` entries parsed by `dedupe_oos.py` follow the format established by the conformance reviewer prompt: `[OOS] <file or area> — <one-sentence description>`. If the format changes in the prompt, the parser must be updated.
- `gh issue list --label scope-spillover --state open --limit 200` returns enough coverage; at current volume this is well within limits.
- `python3` is available in the dark-factory container (confirmed — it's used by `fmt_hunk_filter.py` and `gate_blast_radius.py`).

---

## Implementation Checklist

- [ ] Create `dark-factory/scripts/dedupe_oos.py` with `FINDING_TYPES` registry, normalization pipeline, within-run dedup, cross-run key matching, best-effort fallback, and JSON I/O
- [ ] Update `dark-factory-conformance.md` Phase 3.6.2: fetch open spillovers → call `dedupe_oos.py` (fail-open) → process action list
- [ ] Update spillover issue body template in Phase 3.6.2 to embed `<!-- dedup-key: <key> -->`
- [ ] Create `dark-factory/tests/test_dedupe_oos.py` with four required test scenarios
- [ ] Add `test_conformance_dedupe_wired` marker test to `test_conformance_formatter_step.py` (or a new `test_conformance_dedupe_step.py`) asserting `dedupe_oos.py` is referenced in the command file

---

*Spec generated by MarketHawk Refinement Pipeline — 2026-06-13*
