# Codeindex Ops Lessons — Factory Memory Entries (Spillover from #200)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two codeindex CLI operational lessons to `.archon/memory/dark-factory-ops.md` under the existing `## Codeindex / MCP Integration` section. No code changes. No other files modified.

**Architecture:** Direct edit to one memory file. Two entries are appended at the end of the "Codeindex / MCP Integration" section, before the `## Docker Port Hardening` header. Both entries carry the standard inline metadata comment format.

**Tech Stack:** Plain markdown editing. No build, migration, or test steps.

**Spec:** `docs/superpowers/specs/2026-06-10-codeindex-ops-lessons-design.md`

---

## File Structure

| File | Change |
|---|---|
| `.archon/memory/dark-factory-ops.md` | **MODIFY** — insert two entries at the end of `## Codeindex / MCP Integration`, before `## Docker Port Hardening` |

---

## Task 1: Add codeindex ops entries to factory memory

**Files:** `.archon/memory/dark-factory-ops.md`

- [ ] **Step 1: Verify current state**

Confirm neither entry exists yet:

```bash
grep -c "codeindex symbols.*--inline\|high-blast.*tmp" .archon/memory/dark-factory-ops.md
```

Expected output: `0`

- [ ] **Step 2: Locate insertion point**

Confirm the section structure before editing:

```bash
grep -n "^## Codeindex\|^## Docker Port" .archon/memory/dark-factory-ops.md
```

Expected output (approximate line numbers):
```
NN:## Codeindex / MCP Integration
MM:## Docker Port Hardening
```

The new entries go between the last existing Codeindex entry and `## Docker Port Hardening`.

- [ ] **Step 3: Insert the two entries**

Use the Edit tool to insert the two new entries immediately after the last existing entry in the `## Codeindex / MCP Integration` section. The current last entry in that section ends with:

```
...abort an autonomous factory run. <!-- issue:#159 date:2026-06-03 expires:2026-12-03 source:implement -->
```

Replace that closing portion with the same text plus the two new entries:

```markdown
...abort an autonomous factory run. <!-- issue:#159 date:2026-06-03 expires:2026-12-03 source:implement -->

- [AVOID] `codeindex symbols . --inline` embeds symbols into `codeindex.json` rather than producing a standalone file. Use `codeindex symbols . --output symbolindex.json` to generate the committed standalone symbol index. <!-- issue:#264 date:2026-06-10 expires:2026-12-10 source:implement -->

- [PATTERN] Write `codeindex high-blast` output via a temp file + `mv` (`codeindex high-blast > /tmp/hotspots.md && mv /tmp/hotspots.md docs/codeindex-hotspots.md`) rather than redirecting straight to the target. A direct `>` redirect truncates the target before the command runs, so a codeindex failure leaves an empty/corrupt committed file — the temp-file + atomic `mv` preserves the clean-on-failure guarantee. <!-- issue:#264 date:2026-06-10 expires:2026-12-10 source:implement -->
```

The full Edit replaces:

**old_string:**
```
- [PATTERN] Pre-commit hooks that invoke advisory/optional tools (e.g. `codeindex-blast`) must always exit 0 — use `|| true` or `; exit 0`. A non-zero exit from a pre-commit hook blocks the commit and will abort an autonomous factory run. <!-- issue:#159 date:2026-06-03 expires:2026-12-03 source:implement -->

## Docker Port Hardening
```

**new_string:**
```
- [PATTERN] Pre-commit hooks that invoke advisory/optional tools (e.g. `codeindex-blast`) must always exit 0 — use `|| true` or `; exit 0`. A non-zero exit from a pre-commit hook blocks the commit and will abort an autonomous factory run. <!-- issue:#159 date:2026-06-03 expires:2026-12-03 source:implement -->

- [AVOID] `codeindex symbols . --inline` embeds symbols into `codeindex.json` rather than producing a standalone file. Use `codeindex symbols . --output symbolindex.json` to generate the committed standalone symbol index. <!-- issue:#264 date:2026-06-10 expires:2026-12-10 source:implement -->

- [PATTERN] Write `codeindex high-blast` output via a temp file + `mv` (`codeindex high-blast > /tmp/hotspots.md && mv /tmp/hotspots.md docs/codeindex-hotspots.md`) rather than redirecting straight to the target. A direct `>` redirect truncates the target before the command runs, so a codeindex failure leaves an empty/corrupt committed file — the temp-file + atomic `mv` preserves the clean-on-failure guarantee. <!-- issue:#264 date:2026-06-10 expires:2026-12-10 source:implement -->

## Docker Port Hardening
```

- [ ] **Step 4: Verify entries are present and well-formed**

```bash
# Confirm both entries are present
grep -c "issue:#264" .archon/memory/dark-factory-ops.md
```
Expected: `2`

```bash
# Confirm both carry the required metadata tags
grep "issue:#264" .archon/memory/dark-factory-ops.md
```
Expected: two lines — one starting `- [AVOID]` and one starting `- [PATTERN]`.

```bash
# Confirm both carry expires:2026-12-10
grep "expires:2026-12-10" .archon/memory/dark-factory-ops.md
```
Expected: two matching lines.

```bash
# Confirm entries appear under the correct section header (not after ---)
awk '/^## Codeindex \/ MCP Integration/{found=1} /^---/{found=0} found && /issue:#264/' .archon/memory/dark-factory-ops.md
```
Expected: two matching lines (both entries are within the section, before the PROVISIONAL `---`).

- [ ] **Step 5: Commit**

```bash
git add .archon/memory/dark-factory-ops.md
git diff --cached --stat
```

Expected:
```
 .archon/memory/dark-factory-ops.md | 4 ++++
 1 file changed, 4 insertions(+)
```

```bash
git commit -m "$(cat <<'EOF'
docs: add codeindex ops lessons to factory memory (issue #264)

- [AVOID] codeindex symbols . --inline embeds into codeindex.json, not a standalone symbolindex.json
- [PATTERN] write codeindex high-blast via temp file + mv for atomic, clean-on-failure output

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

Expected: `[refine/issue-264-add-codeindex-ops-lessons-to-factory-mem <hash>] docs: add codeindex ops lessons...`
