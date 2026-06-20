# Plan: Stop OOS Codeindex Hotspot Commits on Feature Branches

**Goal:** Prevent `docs/codeindex-hotspots.md` from being committed to feature branches by the dark factory; add a `post-merge-update-codeindex` DAG node that refreshes the file on `main` after each merge.

**Architecture:** Single-file YAML change to `.archon/workflows/archon-dark-factory.yaml`. Two node edits: remove the git commit block from `regen-codeindex`, add `post-merge-update-codeindex` after `close-preview`. No backend, frontend, or migration changes.

**Tech Stack:** Archon DAG YAML, bash, codeindex CLI.

**Issue:** #561 (scope spillover from #329)

---

## File Structure

| File | Change |
|------|--------|
| `.archon/workflows/archon-dark-factory.yaml` | Remove `git add + git commit` from `regen-codeindex`; add `post-merge-update-codeindex` node after `close-preview`; update `regen-codeindex` comment |

No other files change.

---

## Tasks

### Task 1 — Remove the git commit block from `regen-codeindex` and update its comment

**Files:**
- `.archon/workflows/archon-dark-factory.yaml`

**TDD Steps:**

1. **Write a failing static assertion.** Run the following grep to confirm the commit block currently exists (should exit 0 = present):
   ```bash
   grep -qF 'git add docs/codeindex-hotspots.md' .archon/workflows/archon-dark-factory.yaml \
     && echo "FAIL: commit block present — test correctly fails before change" \
     || echo "PASS: commit block absent"
   # Expected: FAIL (commit block present)
   ```

2. **Verify test fails.** The output must be `FAIL: commit block present — test correctly fails before change`.

3. **Implement.** Edit `.archon/workflows/archon-dark-factory.yaml`. Locate the `regen-codeindex` node (currently around line 358). Make two changes:

   **a) Replace the node comment** (currently lines 358–361):
   ```yaml
   # Old comment — replace:
   # Post-implement codeindex regeneration — refreshes the local index so the in-run MCP tools
   # (lookup_symbol / get_impact) see the final code. codeindex.json / symbolindex.json are
   # gitignored (regenerated on demand, see #343); only docs/codeindex-hotspots.md is committed.
   # Non-fatal: if codeindex is unavailable the run continues.
   ```
   Replace with:
   ```yaml
   # Post-implement codeindex regeneration — refreshes the local index so the in-run MCP tools
   # (lookup_symbol / get_impact) see the final code. codeindex.json / symbolindex.json are
   # gitignored (regenerated on demand, see #343). docs/codeindex-hotspots.md is generated
   # locally for in-run use but NOT committed to the feature branch — post-merge refresh
   # happens in the post-merge-update-codeindex node. Non-fatal: if codeindex is unavailable
   # the run continues.
   ```

   **b) Remove the git commit block** from `regen-codeindex`'s `bash:` section. The current node body is:
   ```bash
   if ! command -v codeindex &>/dev/null; then
     echo "WARNING: codeindex not available — skipping post-implement regeneration"
     exit 0
   fi
   echo "Regenerating codeindex (post-implement pass)..."
   codeindex analyze . 2>/dev/null || echo "WARNING: codeindex analyze failed"
   codeindex symbols . --inline 2>/dev/null || echo "WARNING: codeindex symbols failed"
   mkdir -p docs
   codeindex high-blast 2>/dev/null > docs/codeindex-hotspots.md || true
   # Commit only the small human-readable hotspots doc; the JSON indexes are gitignored.
   git add docs/codeindex-hotspots.md 2>/dev/null || true
   if ! git diff --staged --quiet 2>/dev/null; then
     git commit -m "chore: update codeindex hotspots (post-implement)"
     echo "codeindex hotspots committed"
   else
     echo "codeindex hotspots unchanged — no commit needed"
   fi
   ```

   Replace with (removing the git add/commit block and applying the atomic write pattern for `high-blast`):
   ```bash
   if ! command -v codeindex &>/dev/null; then
     echo "WARNING: codeindex not available — skipping post-implement regeneration"
     exit 0
   fi
   echo "Regenerating codeindex (post-implement pass)..."
   codeindex analyze . 2>/dev/null || echo "WARNING: codeindex analyze failed"
   codeindex symbols . --inline 2>/dev/null || echo "WARNING: codeindex symbols failed"
   mkdir -p docs
   codeindex high-blast 2>/dev/null > docs/codeindex-hotspots.md.tmp \
     && mv docs/codeindex-hotspots.md.tmp docs/codeindex-hotspots.md \
     || echo "WARNING: codeindex high-blast failed — hotspots file unchanged"
   echo "codeindex hotspots generated locally (not committed — post-merge refresh via post-merge-update-codeindex)"
   ```

   > **Memory pattern applied:** `[PATTERN]` from `dark-factory-ops.md`: Write `codeindex high-blast` output to a temp file then atomically rename to avoid zero-byte artifacts on crash. The spec's direct `>` redirect is corrected here to use `> .tmp && mv` per the accumulated lesson.

4. **Verify test passes.** Re-run the static assertion from step 1:
   ```bash
   grep -qF 'git add docs/codeindex-hotspots.md' .archon/workflows/archon-dark-factory.yaml \
     && echo "FAIL: commit block still present" \
     || echo "PASS: commit block absent"
   # Expected: PASS: commit block absent
   ```

5. **Run the existing test suite** to confirm no regressions:
   ```bash
   bash dark-factory/tests/test_codeindex_config.sh
   # Expected: all tests PASS, FAILED=0
   ```

6. **Run the DAG validator:**
   ```bash
   python dark-factory/scripts/check_workflow_dag.py .archon/workflows/archon-dark-factory.yaml
   # Expected: exits 0, no output (or "OK")
   ```

7. **Commit:**
   ```bash
   git add .archon/workflows/archon-dark-factory.yaml
   git commit -m "fix(codeindex): remove hotspot commit from regen-codeindex node (#561)

   The regen-codeindex node was committing docs/codeindex-hotspots.md to
   feature branches, injecting whole-codebase blast-score refreshes unrelated
   to the issue being worked. Remove the git add + git commit block; keep
   local generation for in-run MCP freshness. Post-merge refresh will be
   handled by the new post-merge-update-codeindex node (next commit).

   Also apply atomic temp+mv write pattern for codeindex high-blast output
   per accumulated memory pattern."
   ```

---

### Task 2 — Add `post-merge-update-codeindex` node after `close-preview`

**Files:**
- `.archon/workflows/archon-dark-factory.yaml`

**TDD Steps:**

1. **Write a failing static assertion.** Confirm the new node does not yet exist:
   ```bash
   grep -qF 'post-merge-update-codeindex' .archon/workflows/archon-dark-factory.yaml \
     && echo "FAIL: node already present" \
     || echo "PASS: node absent — test correctly fails before change"
   # Expected: PASS: node absent — test correctly fails before change
   ```

2. **Verify test fails.** The output must be `PASS: node absent — test correctly fails before change`. (In this inverted-check pattern, "test fails" means the feature doesn't exist yet, which is confirmed by the PASS message here — the assertion on absence passes, meaning the feature is missing.)

3. **Implement.** In `.archon/workflows/archon-dark-factory.yaml`, locate the `close-preview` node and its closing line (currently around line 233 — ends with `timeout: 30000`). Insert the following new node block immediately after:

   ```yaml
     - id: post-merge-update-codeindex
       bash: |
         if ! command -v codeindex &>/dev/null; then
           echo "WARNING: codeindex not available — skipping post-merge hotspot update"
           exit 0
         fi
         ISSUE=$(jq -r '.resolved_number' "$ARTIFACTS_DIR/issue.json")
         echo "Refreshing codeindex hotspots on main (post-merge for issue #${ISSUE})..."
         git fetch origin main
         git checkout main
         git reset --hard origin/main
         codeindex analyze . 2>/dev/null || echo "WARNING: codeindex analyze failed"
         codeindex symbols . --output symbolindex.json 2>/dev/null || echo "WARNING: codeindex symbols failed"
         mkdir -p docs
         codeindex high-blast 2>/dev/null > docs/codeindex-hotspots.md.tmp \
           && mv docs/codeindex-hotspots.md.tmp docs/codeindex-hotspots.md \
           || echo "WARNING: codeindex high-blast failed — hotspots file unchanged"
         git add docs/codeindex-hotspots.md
         if ! git diff --staged --quiet; then
           git commit -m "chore: refresh codeindex hotspots (post-merge #${ISSUE})"
           git push origin main \
             || echo "WARNING: push to main failed — hotspots will be stale until next manual refresh"
         else
           echo "codeindex hotspots unchanged post-merge — no commit needed"
         fi
       depends_on: [close-preview]
       when: "$parse-intent.output.intent == 'close'"
       timeout: 120000
   ```

   > **Memory patterns applied:**
   > - `[AVOID]` from `dark-factory-ops.md`: `codeindex symbols . --inline` embeds symbols into `codeindex.json` — use `--output symbolindex.json` instead. The spec used `--inline`; this plan corrects it.
   > - `[PATTERN]` from `dark-factory-ops.md`: Atomic temp+mv for `codeindex high-blast` output.
   > - `[PATTERN]` from `dark-factory-ops.md` (Archon `when:` grammar): `when:` only supports simple equality — `"$parse-intent.output.intent == 'close'"` is a valid single-equality expression.
   > - `post-merge-update-codeindex` has exactly one upstream (`close-preview`) and is NOT an OR-join; do NOT add `trigger_rule`. The DAG sync tripwire in `check_workflow_dag.py` expects exactly `len(REQUIRED_OR_JOIN_NODES)` = 4 trigger_rule-bearing nodes; adding one here would fire the tripwire.

4. **Verify test passes.** Re-run the static assertion from step 1:
   ```bash
   grep -qF 'post-merge-update-codeindex' .archon/workflows/archon-dark-factory.yaml \
     && echo "PASS: node present" \
     || echo "FAIL: node absent"
   # Expected: PASS: node present
   ```

5. **Run the existing test suite:**
   ```bash
   bash dark-factory/tests/test_codeindex_config.sh
   # Expected: all tests PASS, FAILED=0
   ```

6. **Run the DAG validator:**
   ```bash
   python dark-factory/scripts/check_workflow_dag.py .archon/workflows/archon-dark-factory.yaml
   # Expected: exits 0, no errors
   # Verify trigger_rule count is still 4 (unchanged):
   grep -c 'trigger_rule' .archon/workflows/archon-dark-factory.yaml
   # Expected: 4
   ```

7. **Run the `when:` expression validator:**
   ```bash
   python dark-factory/scripts/check_workflow_when.py .archon/workflows/archon-dark-factory.yaml
   # Expected: exits 0, no errors
   ```

8. **Commit:**
   ```bash
   git add .archon/workflows/archon-dark-factory.yaml
   git commit -m "feat(codeindex): add post-merge-update-codeindex DAG node (#561)

   After close-preview merges the PR, this new node checks out main and
   regenerates docs/codeindex-hotspots.md with fresh blast scores reflecting
   the merged code. Commits and pushes to main if changed; non-blocking
   (codeindex unavailability and push failures are warnings only so the
   merge is never undone)."
   ```
