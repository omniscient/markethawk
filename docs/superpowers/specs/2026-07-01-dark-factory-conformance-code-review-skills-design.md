# Dark Factory: Conformance & Code-Review Skills

**Issue:** #695  
**Date:** 2026-07-01  
**Status:** Pending review

---

## Overview

The Dark Factory conformance and code-review gates currently embed their reviewer prompts and rubrics inside `.claude/skills/refinement/` (shared with the refine/plan pipeline) and do not yet consume the ranked/compact diff artifacts being built by the #663 token-optimization epic. This spec extracts each gate into its own dedicated skill, wires up consumption of the `diff-ranking.json` artifact from #669, and adds an escalation path that lifts the diff cap for security/trading/auth/high-blast-radius changes.

---

## Problem Statement

1. **Orphaned prompts in the wrong skill.** `conformance-reviewer-prompt.md` and `code-review-reviewer-prompt.md` live in `.claude/skills/refinement/` alongside the brainstorming personas (`product-owner-prompt.md`, `architect-prompt.md`). These are unrelated concerns. The Dockerfile `COPY` bakes all five files into `/opt/refinement-skills/`; every scenario that calls `skill_prompts` loads them all, including the orchestrator prompt in a conformance run and the conformance rubric in a refine run.

2. **No diff-ranking consumption.** Both gate commands hard-truncate diffs at 1000 lines (`head -1000`) regardless of risk profile. The `diff-ranking.json` artifact planned in #669 (high-risk hunks first, docs/test-only summarized, token-budget-aware) has no consumer yet.

3. **No escalation path.** Security/auth/trading changes and high-blast-radius files get the same 1000-line cap as a one-line docstring fix. The `token_optimization.escalation.opus_only_for` list and `token_optimization.diff.max_review_tokens: 6000` config already define the vocabulary and ceiling; neither is wired into the gate commands.

---

## Requirements

1. **R1 — Two new skills** with dedicated directories:
   - `.claude/skills/dark-factory-conformance/` — conformance gate skill
   - `.claude/skills/dark-factory-code-review/` — code-review gate skill
   - Each has a concise `SKILL.md` (purpose, invocation, load order) and a `RUBRIC.md` (the full reviewer rubric that gets passed to the subagent).

2. **R2 — Prompt migration.** Move `conformance-reviewer-prompt.md` → `dark-factory-conformance/RUBRIC.md`; move `code-review-reviewer-prompt.md` → `dark-factory-code-review/RUBRIC.md`. The files in `.claude/skills/refinement/` are removed. Content is unchanged; only the location changes.

3. **R3 — Scenario-aware skill loading.** Update `dark-factory/scripts/context_budget.py` so the `skill_prompts` section is scenario-scoped: a conformance run loads only the conformance skill files; a code-review run loads only the code-review skill files; a refine/plan run loads only the brainstorming personas. The current single `_SKILL_PROMPT_DIR` / `_SKILL_PROMPT_FILES` pair becomes a per-scenario map.

4. **R4 — Dockerfile updates.** Add `COPY` lines for the two new skill directories (mirroring line 116 for refinement). Update the container mount paths referenced by `context_budget._SKILL_PROMPT_DIR` for each scenario.

5. **R5 — Diff-ranking consumption (when available).** In both gate commands, after the existing pre-triage step, check for `$ARTIFACTS_DIR/diff-ranking.json`. If present and parseable:
   - Build the reviewer's `$DIFF_CONTENT` / `### Diff` block from the ranked assembly (high-risk hunks in full and first, low-risk docs/test-only collapsed to one-line summary, total within the token cap).
   - **Do not alter** `review_diff.txt` (code-review) or `$TRIAGED_DIFF` (conformance) — the raw unified diff must remain intact for `code_review_payload.py`'s `changed_lines()` anchoring and conformance OOS parsing.
   - Log: `"[diff-ranking] consumed diff-ranking.json — N high-risk / M low-risk hunks"`
   - If absent or unparseable: fall back to exactly the existing logic (`git diff ... | head -1000` for code-review; `RAW_DIFF → fmt_hunk_filter.py → $TRIAGED_DIFF` for conformance). The fallback must be byte-identical to the current behavior.

6. **R6 — Escalation predicate.** Before building `$DIFF_CONTENT`, detect whether the change is escalation-eligible:
   - Match changed file paths against `epic_autopilot.sensitive_keywords` (`trading|ibkr|live order|notional|authentication|authorization|authn|authz|jwt|oauth|rbac|/auth`) and `epic_autopilot.hard_exclude_paths`.
   - OR check if `gate_blast_radius.py` / `docs/codeindex-hotspots.md` flags any changed file above `blast_radius.hotspot_score_floor: 5.0`.
   - Reuse the existing `token_optimization.escalation.opus_only_for` vocabulary (security, trading, auth, high_blast_radius).
   - If escalated AND `diff-ranking.json` is absent: use `token_optimization.diff.max_review_tokens` (6000 tokens ≈ ~4000–5000 lines, estimated via `token_estimate.estimate_tokens()`) instead of `DIFF_LINE_CAP = 1000`. This is a raised cap, not unbounded.
   - If escalated AND `diff-ranking.json` is present: still use the ranking, but do not apply the low-risk summarization (include all hunks, bounded by `max_review_tokens`).
   - On escalation-detection error → fail-open to existing `head -1000` / current fallback path.
   - Do NOT switch the reviewer model — both gates already pin to Opus 4.8; escalation is purely a context-width change.

7. **R7 — Preserve output contract.** The emitted artifacts and gate semantics are unchanged:
   - `conformance.md`: `STATUS:`, `GATE_TYPE: conformance`, `VERDICT:`, `CYCLES:`, `OOS_EXCISED:`, `OOS_TICKETS:` header block.
   - `review.md`: `STATUS:`, `GATE_TYPE: code-review`, `BLOCKERS:`, `ADVISORY:`, `THRESHOLD:` header block.
   - `emit_verdict` calls, `scope_enforcement` / excision logic, `block_on_material`, `block_threshold`, `fail_open`, board status moves, `needs-discussion` labeling, memory writes — all unchanged.

8. **R8 — Fallback path explicit.** Every new code path (diff-ranking consumption, escalation predicate) must degrade gracefully to the current behavior on any error (missing file, parse failure, subprocess error). Gate the new behavior behind `if [ -f "$ARTIFACTS_DIR/diff-ranking.json" ]` and `if <escalation_check_succeeds>`.

---

## Approach

### Chosen: Extract-and-Dedicate (Two new skill directories)

Create dedicated skill directories for each gate, migrate the reviewer rubrics there, update the Dockerfile and `context_budget.py` to load scenario-specifically, then add diff-ranking consumption and escalation as layered changes to the existing `.archon/commands/` orchestration shells.

**Why this approach over alternatives:**
- The `.archon/commands/` orchestration shells own load-bearing behavior (board moves, reconcile loops, exit codes, scope enforcement). Absorbing them into skills would require tracking and preserving all that machinery in a different format — high risk for the "preserve existing contract" requirement.
- The "concise SKILL.md" phrasing in the AC targets the *skill* (what the reviewer should do), not the orchestration shell. Today, that content is the reviewer prompt; after this change, it's the rubric files in the skill directory.
- The `architecture-review` skill demonstrates the right pattern: `SKILL.md` (concise entry, no orchestration) + `RUBRIC.md` / `SECTIONS.md` / `ANALYSIS.md` (detailed content).

### Alternatives Considered

**Alt A: Merge into refinement skill (sub-directories under `.claude/skills/refinement/`)**  
Rejected — blurs the separation between planning personas (product owner, architect) and gate reviewers. The context_pack already loads the refinement skill for refine/plan scenarios; adding gate rubrics there continues the cross-contamination the issue was filed to fix.

**Alt B: Single `dark-factory-review` skill with conformance and code-review sub-directories**  
Rejected — the two gates have separate invocation paths, separate SKILL.md descriptions, separate Dockerfile mounts, and separate `_SECTION_REGISTRY` scenario keys. One skill containing both would require a sub-selector mechanism. Two dedicated skills are cleaner and match the acceptance criteria ("conformance skill" and "code-review skill" as separate line items).

---

## Architecture

### New files

```
.claude/skills/dark-factory-conformance/
  SKILL.md          — concise description: what this gate judges, how it is invoked, load order
  RUBRIC.md         — full reviewer rubric (migrated from refinement/conformance-reviewer-prompt.md)

.claude/skills/dark-factory-code-review/
  SKILL.md          — concise description: what this gate judges, how it is invoked, load order
  RUBRIC.md         — full reviewer rubric (migrated from refinement/code-review-reviewer-prompt.md)
```

### Deleted files

```
.claude/skills/refinement/conformance-reviewer-prompt.md   (content → dark-factory-conformance/RUBRIC.md)
.claude/skills/refinement/code-review-reviewer-prompt.md   (content → dark-factory-code-review/RUBRIC.md)
```

### Modified files

**`dark-factory/Dockerfile`** (after line 116):
```dockerfile
COPY .claude/skills/dark-factory-conformance/ /opt/dark-factory-conformance-skill/
COPY .claude/skills/dark-factory-code-review/ /opt/dark-factory-code-review-skill/
```
The existing line 116 (`COPY .claude/skills/refinement/ /opt/refinement-skills/`) stays; it still carries the brainstorming personas for refine/plan.

**`dark-factory/scripts/context_budget.py`**:
- Replace single `_SKILL_PROMPT_DIR` / `_SKILL_PROMPT_FILES` globals with a `_SKILL_PROMPT_SETS` dict keyed by scenario:
  ```python
  _SKILL_PROMPT_SETS: dict[str, tuple[str, list[str]]] = {
      "refine":       ("/opt/refinement-skills",              ["orchestrator-prompt.md", "product-owner-prompt.md"]),
      "plan":         ("/opt/refinement-skills",              ["architect-prompt.md"]),
      "conformance":  ("/opt/dark-factory-conformance-skill", ["SKILL.md", "RUBRIC.md"]),
      "code-review":  ("/opt/dark-factory-code-review-skill", ["SKILL.md", "RUBRIC.md"]),
  }
  ```
- Update `_read_skill_prompts()` to accept a `scenario` parameter and dispatch via `_SKILL_PROMPT_SETS`.

**`.archon/commands/dark-factory-conformance.md`** — Phase 3 changes:
- In Phase 1 LOAD, update the prompt-read path from `/opt/refinement-skills/conformance-reviewer-prompt.md` to `/opt/dark-factory-conformance-skill/RUBRIC.md`.
- After Step 3.0 (pre-triage), add:
  ```bash
  # Escalation check
  ESCALATED=false
  if grep -qiE 'trading|ibkr|live order|notional|authentication|authorization|authn|authz|jwt|oauth|rbac|/auth' \
    <(git diff main...HEAD --name-only 2>/dev/null); then
    ESCALATED=true
    echo "[conformance] escalated: security/trading/auth path detected"
  fi
  # Diff-ranking consumption
  DIFF_CONTENT="$TRIAGED_DIFF"
  if [ -f "$ARTIFACTS_DIR/diff-ranking.json" ] && python3 -c \
      "import json,sys; json.load(open(sys.argv[1]))" "$ARTIFACTS_DIR/diff-ranking.json" 2>/dev/null; then
    DIFF_CONTENT=$(python3 dark-factory/scripts/diff_rank.py --consume \
      --ranking "$ARTIFACTS_DIR/diff-ranking.json" \
      --raw-diff <(printf '%s' "$TRIAGED_DIFF") \
      ${ESCALATED:+--escalated} 2>/dev/null) \
      || DIFF_CONTENT="$TRIAGED_DIFF"   # fail-open
    echo "[conformance] diff-ranking consumed (escalated=$ESCALATED)"
  elif [ "$ESCALATED" = "true" ]; then
    MAX_REVIEW_TOKENS=$(yq '.token_optimization.diff.max_review_tokens // 6000' "$CONFIG_YAML" 2>/dev/null || echo 6000)
    RAW_LINES=$(git diff main...HEAD -- ':!*.lock' ':!*.md' ':!.archon/memory/**' \
      ':!codeindex.json' ':!symbolindex.json' ':!docs/codeindex-hotspots.md' ':!docs/database-schema.md' \
      2>/dev/null | wc -l)
    LINE_CAP=$(python3 -c "print(min($RAW_LINES, $MAX_REVIEW_TOKENS // 4))")
    DIFF_CONTENT=$(git diff main...HEAD -- ':!*.lock' ':!*.md' ':!.archon/memory/**' \
      ':!codeindex.json' ':!symbolindex.json' ':!docs/codeindex-hotspots.md' ':!docs/database-schema.md' \
      2>/dev/null | head -"$LINE_CAP")
    echo "[conformance] escalated: using expanded cap of $LINE_CAP lines (tokens≈$MAX_REVIEW_TOKENS)"
  fi
  ```
- Replace the inline `$TRIAGED_DIFF` reference in `$ARTIFACT_CONTENT` with `$DIFF_CONTENT`.
- `$TRIAGED_DIFF` remains available and unchanged for OOS parsing.

**`.archon/commands/dark-factory-code-review.md`** — Phase 2 changes:
- Phase 1 LOAD: update prompt-read path to `/opt/dark-factory-code-review-skill/RUBRIC.md`.
- Phase 2 DIFF: add escalation check + diff-ranking consumption before writing `review_diff.txt`. The ranked `$DIFF_CONTENT` goes to the subagent prompt (Phase 3 step 3), but the full pre-triaged diff continues to be written to `$ARTIFACTS_DIR/review_diff.txt` for `code_review_payload.py`.

### Escalation keyword source (read from config, not hard-coded)

Both commands should read `epic_autopilot.sensitive_keywords` from `config.yaml` rather than duplicating the pattern string in the command file. Use `yq`:
```bash
ESC_KEYWORDS=$(yq '.epic_autopilot.sensitive_keywords' "$CONFIG_YAML" 2>/dev/null || echo "trading|auth|security")
```

---

## Open Questions (non-blocking)

1. **`diff_rank.py` consume interface.** The `--consume` mode of `diff_rank.py` is not yet specified by #669. The conformance/code-review commands in this spec use a placeholder interface (`--consume --ranking ... --raw-diff ... --escalated`). The implement agent should adapt to whatever #669 ships, or skip the ranking consumption code path entirely if #669 is not yet merged (the fallback handles this).

2. **Token-to-line estimation for escalated cap.** The spec divides `max_review_tokens` by 4 as a rough chars-per-token estimate. A tighter estimate using `token_estimate.estimate_tokens()` on a sample hunk would be more accurate but adds subprocess overhead. Mark as a follow-up.

---

## Assumptions

- **[ASSUMPTION]** `diff_rank.py` from #669 will ship a `--consume` (or equivalent) mode that reads `diff-ranking.json` and a raw diff and outputs a ranked assembly. If #669 ships a different interface, update the consume call in both gate commands.
- **[ASSUMPTION]** The reviewer subagent (`claude-opus-4-8`) stays pinned for both gates. Escalation is context-width only, not a model change.
- **[ASSUMPTION]** The existing `conformance-reviewer-prompt.md` and `code-review-reviewer-prompt.md` content is production-ready and requires no rubric changes as part of this issue; this work is structural only. If the rubrics need updating, that is a separate issue.
- **[ASSUMPTION]** `context_pack.py` / `context_budget.py` already have `conformance` and `code-review` as scenario keys in `_SECTION_REGISTRY` (confirmed at context_budget.py:31-32); only `_read_skill_prompts()` needs updating, not the scenario registry itself.
