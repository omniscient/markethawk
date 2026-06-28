# Spike: Evaluate codebase-memory-mcp as Dark Factory Code-Memory Backend

**Status:** design
**Date:** 2026-06-28
**Issue:** #675
**Epic:** #663 (Dark Factory token optimization)
**Future plan:** #674 (full integration layers, parked until this spike resolves)
**Build constraint:** This spike produces **no committed code or config changes** — only ephemeral evaluation artifacts and an issue comment. The factory run is self-contained.

---

## Problem

Dark Factory agents spend significant tokens on exploratory reads — loading `ARCHITECTURE.md` in full, grepping broadly for symbols, reading entire service files to find relevant context. `codebase-memory-mcp` is a candidate structural code-graph backend that might let agents query a pre-indexed graph instead, reducing exploratory token load and improving targeted context assembly (architecture slicing, changed-symbol impact, caller/callee tracing).

Before any integration work starts (#674), we need a go/no-go recommendation grounded in measurable data — installation safety, index quality, and actual token-savings estimates against real historical issues.

---

## Requirements

1. **Safe installation**: Install codebase-memory-mcp only inside the ephemeral `--rm` dark-factory container, to a non-PATH path scoped to `$ARTIFACTS_DIR`. No system-level `pip install`, no writes to `~/.claude`, `~/.codex`, `~/.config`, or `.claude/settings.local.json`. No `curl | bash`.
2. **Pinned version**: Use an exact pinned release (tag or commit SHA); document the pinned ref and any checksum or hash verification steps.
3. **Supply-chain check**: Document whether the package has a checksum/integrity mechanism and whether its installer auto-registers hooks.
4. **Index MarketHawk**: Run the indexer against the cloned repo and record index time and cache size.
5. **Query evaluation**: Exercise all the query types from the evaluation checklist (Python/FastAPI symbol lookup, SQLAlchemy lookup, TS/TSX frontend lookup, Docker/YAML lookup, structural search, architecture summary, changed-symbol impact, call-path tracing).
6. **Comparative evaluation on 3 bench issues**: For each of three issues from `dark-factory/bench/baseline.md` (at their pinned `pre_pr_sha`), compare the context assembled by current grep/read exploration against context assembled via codebase-memory-mcp queries. Measure token counts for each.
7. **Recommendation**: Emit a single-tier recommendation (`no-go | advisory-only | context-pack backend | gate-backed follow-up`) with supporting evidence. Post it as a GitHub comment on #675 and reference #674 for next steps.
8. **No factory behavior change**: The spike adds no new commands, no new wired-in scripts, and no config changes. All outputs go to `$ARTIFACTS_DIR`.

---

## Approach

### Phase 1 — Installation isolation

Install codebase-memory-mcp to a throw-away location inside the ephemeral factory container:

```bash
# Preferred: binary release (no pip side effects)
PINNED_VERSION="v<X.Y.Z>"   # implementer: pin to the latest stable release tag found at https://github.com/DeusData/codebase-memory-mcp/releases; document the exact ref in cbm-recommendation.md
CBM_DIR="$ARTIFACTS_DIR/cbm-install"
mkdir -p "$CBM_DIR"

# Option A: pip install --target (no system site-packages mutation)
python3 -m pip install --target "$CBM_DIR/lib" "codebase-memory-mcp==${PINNED_VERSION#v}"
export PYTHONPATH="$CBM_DIR/lib:$PYTHONPATH"

# Option B: download a pinned binary (if released as a standalone)
curl -fsSL "https://github.com/DeusData/codebase-memory-mcp/releases/download/${PINNED_VERSION}/codebase-memory-mcp-linux-x64" \
  -o "$CBM_DIR/codebase-memory-mcp"
chmod +x "$CBM_DIR/codebase-memory-mcp"
```

**Safety rules (hard constraints):**
- Do NOT add `$CBM_DIR` to `~/.bashrc`, `~/.profile`, or any persistent PATH
- Do NOT run the package's own installer/setup script if it prompts to configure agent hooks
- If the installer writes to `~/.claude/`, `~/.codex/`, or similar, record this as a **supply-chain risk** and downgrade the recommendation by at least one tier

### Phase 2 — Index MarketHawk

```bash
CBM="$CBM_DIR/codebase-memory-mcp"  # or python3 -m codebase_memory_mcp
CACHE_DIR="$ARTIFACTS_DIR/cbm-cache"
mkdir -p "$CACHE_DIR"

time $CBM index --repo /workspace/markethawk --cache-dir "$CACHE_DIR"
```

Record: wall-clock time, disk bytes used by `$CACHE_DIR`, any errors.

### Phase 3 — Query evaluation

Run the following query types, capturing outputs to `$ARTIFACTS_DIR/cbm-queries.md`:

| Query type | Sample queries |
|---|---|
| Python/FastAPI symbol | `ScannerService`, `calculate_day_metrics` |
| SQLAlchemy model | `ScannerEvent`, `StockUniverse` |
| Frontend/TS symbol | `UniverseFormModal`, `useScanner` |
| Docker/YAML | `docker-socket-proxy-factory`, `celery-beat` |
| Structural search | "what services does the backend expose?" |
| Architecture summary | "summarize the scanner pipeline" |
| Changed-symbol impact | `--base a662669 --head HEAD` (or equivalent) |
| Call-path tracing | callers of `ScannerService.calculate_day_metrics` |

For each query: record the raw output, subjectively score precision (did it find the right files/lines?) and recall (did it miss anything a grep would have caught?).

### Phase 4 — Comparative evaluation against 3 bench issues

Use three issues from `dark-factory/bench/baseline.md` chosen to cover different discovery patterns:

| Issue | Area | pre_pr_sha | Oracle test |
|---|---|---|---|
| #287 | Backend services (stock screener) | `9634dea` | `test_stock_screener.py`, `test_futures_screener.py` |
| #249 | Frontend (indicators) | `e54e19a` | `indicators.test.ts` |
| #224 | Dark Factory pipeline (workflow OR join) | `a662669` | `test_workflow_or_join.py` |

For each issue:
1. Check out the repo at `pre_pr_sha` (`git checkout <sha>`)
2. Rebuild the cbm index at that SHA
3. Run the issue body through codebase-memory-mcp to assemble context (same task as a factory `refine` or `plan` run)
4. Run the same context assembly using current grep/read exploration (simulate what the factory currently does)
5. Count tokens in each context assembly (use `tiktoken` or Claude's token counter)
6. Record: token count (graph), token count (grep/read), delta, and any context missed by graph vs. grep/read

### Phase 5 — Recommendation

Apply the following decision tree:

| Condition | Tier |
|---|---|
| Fails to install cleanly OR installer mutates agent configs OR index produces no usable output | **no-go** |
| Installs cleanly but token delta < 10% across all 3 issues, OR `pass^k` would regress on bench tasks based on context gaps | **advisory-only** |
| ≥ 15% token reduction across all 3 issues with no safety-critical context gaps | **context-pack backend** |
| Meets context-pack bar AND blast-radius/changed-symbol impact is reliable enough to back a merge gate | **gate-backed follow-up** |

For borderline cases (10–15% range): document the measured numbers and note that the call requires human judgment. The threshold is a decision aid, not a hard gate.

### Phase 6 — Output

Write the recommendation document to `$ARTIFACTS_DIR/cbm-recommendation.md`:

```text
Recommendation: <tier>

Evidence:
- Pinned version: <ref>
- Checksum verified: yes/no
- Installer config mutation risk: none/low/high — <details>
- Index time: <N> seconds
- Cache size: <N> MB
- Query quality: <summary per query type>
- Token savings: <issue #287: X%> / <issue #249: Y%> / <issue #224: Z%>
- Failure modes: <list>
- Safety concerns: <list>

Next steps from #674:
- <list layers to activate or reason to halt>
```

Post the full document as a GitHub comment on #675.

---

## Alternatives Considered

### A: Run evaluation in a separate Docker container

Spin up a clean Docker container with only codebase-memory-mcp installed, evaluate from outside the factory environment. **Rejected**: adds Docker-in-Docker complexity; the factory container is already ephemeral (`--rm`) and has the full toolchain. The isolation requirement is met by `--target` install or a temp venv, not by an outer container.

### B: Follow the Repowise persistent venv pattern (`~/.venvs/cbm/`)

Install to a named persistent venv like Repowise uses for repeated local use. **Rejected**: Repowise is an adopted tool used across sessions; codebase-memory-mcp is explicitly a one-shot spike. A persistent venv implies adoption — the spike must not assume adoption. Use the ephemeral container instead.

### C: Inline ad-hoc evaluation (no script)

Have the factory agent run one-off commands interactively with no structured script. **Rejected**: not reproducible; evaluation results are impossible to audit or re-run. A structured evaluation procedure (even if not a committed script) ensures the recommendation is evidence-backed.

---

## Delivery

The implement phase produces:
1. A completed evaluation run with `$ARTIFACTS_DIR/cbm-recommendation.md`
2. A GitHub comment on #675 with the full recommendation including evidence
3. **No committed code, config, or docs changes** (the spec itself, committed here, is the only committed artifact of this spike)

The comment must explicitly reference #674 with the recommended next layers (or a halt recommendation).

---

## Open Questions

- codebase-memory-mcp's exact release mechanism (binary? Python package? npm?) is not determined until the implementer inspects the repo. If it ships as an npm package rather than Python, the installation path changes (use `npm pack` + install to a temp `node_modules`); the safety rules (no agent config mutation, no global install) remain identical.
- Token counting methodology: use `tiktoken cl100k_base` for a consistent proxy, or use the Anthropic token-counting API (`/v1/messages/count_tokens`). Either is acceptable; document which was used.

---

## Assumptions

- **[flagged]** The evaluation assumes codebase-memory-mcp can run without network access after the initial install (factory containers may have restricted outbound). If the tool requires a cloud API call to serve queries, the recommendation is automatically **no-go** for factory use.
- **[flagged]** Token savings are estimated by comparing static context sizes, not by measuring actual factory runs end-to-end. The 15% threshold is a decision aid for this spike; actual savings in production may vary.
- The three bench issues (#287, #249, #224) are representative of the factory's primary scenarios; other scenario types (conformance, review) are excluded from the comparative evaluation for size reasons and will be assessed qualitatively.
