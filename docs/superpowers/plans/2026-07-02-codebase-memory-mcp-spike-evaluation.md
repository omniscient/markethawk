# codebase-memory-mcp Evaluation Spike — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the codebase-memory-mcp evaluation spike safely inside the ephemeral dark-factory container, compare graph-guided context assembly against current grep/read exploration on three bench-suite issues, apply the decision tree, and post a tiered recommendation (`no-go | advisory-only | context-pack backend | gate-backed follow-up`) as a GitHub comment on #675 referencing #674. No source code, config, or doc files are committed.

**Architecture:** Pure-evaluation run, entirely ephemeral. All artifacts are written to `$ARTIFACTS_DIR` (blown away when the `--rm` container exits). No new Docker services added. No writes to `entrypoint.sh`, `.claude/settings.local.json`, `~/.claude/`, `~/.codex/`, or any agent config path — any installer that mutates these paths triggers an automatic downgrade per the supply-chain risk rule. Not installed to `~/.venvs/` (that pattern is for adopted tools used across sessions; this is a one-shot spike).

**Spec:** `docs/superpowers/specs/2026-06-28-codebase-memory-mcp-spike-design.md` · **Ticket:** #675 · **Future plan:** #674

**Tech Stack:** Bash, Python 3 (`pip`, `tiktoken` or `cl100k_base` proxy), `gh` CLI, `git`

---

## File Structure

| Path | Role | Committed? |
|---|---|---|
| `$ARTIFACTS_DIR/cbm-install/` | Ephemeral install root (pip `--target` or binary) | No |
| `$ARTIFACTS_DIR/cbm-cache/` | Index cache written by the tool | No |
| `$ARTIFACTS_DIR/cbm-queries.md` | Raw output for all 8 query types | No |
| `$ARTIFACTS_DIR/cbm-recommendation.md` | Final recommendation artifact | No |
| `$ARTIFACTS_DIR/index-log.txt` | Indexer stdout/stderr + timing | No |
| `$ARTIFACTS_DIR/config-snapshot-before.txt` | Agent-config file list before install | No |
| `$ARTIFACTS_DIR/config-snapshot-after.txt` | Agent-config file list after install | No |
| `$ARTIFACTS_DIR/context-graph-287.txt` | CBM-assembled context for issue #287 | No |
| `$ARTIFACTS_DIR/context-grep-287.txt` | Grep/read-assembled context for issue #287 | No |
| `$ARTIFACTS_DIR/context-graph-249.txt` | CBM-assembled context for issue #249 | No |
| `$ARTIFACTS_DIR/context-grep-249.txt` | Grep/read-assembled context for issue #249 | No |
| `$ARTIFACTS_DIR/context-graph-224.txt` | CBM-assembled context for issue #224 | No |
| `$ARTIFACTS_DIR/context-grep-224.txt` | Grep/read-assembled context for issue #224 | No |
| `$ARTIFACTS_DIR/token-counts.md` | Token counts (graph vs grep/read per issue) | No |

---

## Task 0: Environment Setup and Recommendation Document Init

**Files:** `$ARTIFACTS_DIR/cbm-recommendation.md` (create), `$ARTIFACTS_DIR/config-snapshot-before.txt` (create)

- [ ] **Step 1: Verify ARTIFACTS_DIR and create working directories**

```bash
[ -n "$ARTIFACTS_DIR" ] || { echo "ERROR: ARTIFACTS_DIR is not set"; exit 1; }
[ -d "$ARTIFACTS_DIR" ] || { echo "ERROR: ARTIFACTS_DIR does not exist: $ARTIFACTS_DIR"; exit 1; }
mkdir -p \
  "$ARTIFACTS_DIR/cbm-install/lib" \
  "$ARTIFACTS_DIR/cbm-install/node" \
  "$ARTIFACTS_DIR/cbm-cache"
echo "Working dirs created under $ARTIFACTS_DIR"
```

Expected output: `Working dirs created under /home/factory/.archon/workspaces/.../artifacts/runs/<run-id>`

- [ ] **Step 2: Initialize the recommendation document**

```bash
cat > "$ARTIFACTS_DIR/cbm-recommendation.md" << 'RECDOC'
# codebase-memory-mcp Evaluation — MarketHawk Dark Factory (#675)

**Issue:** https://github.com/omniscient/markethawk/issues/675
**Future plan:** https://github.com/omniscient/markethawk/issues/674
**Spec:** docs/superpowers/specs/2026-06-28-codebase-memory-mcp-spike-design.md

## Recommendation

**Tier:** (populated in Task 7)

## Evidence

- **Pinned version:** (populated in Task 1)
- **Checksum verified:** (populated in Task 1)
- **Installer config mutation risk:** (populated in Task 1)
- **Index time:** (populated in Task 2)
- **Cache size:** (populated in Task 2)
- **Query quality:** (populated in Task 3)
- **Token savings:** (populated in Tasks 4-6)
- **Failure modes:** (populated throughout)
- **Safety concerns:** (populated throughout)

## Next steps from #674

(populated in Task 7)
RECDOC
echo "cbm-recommendation.md initialized"
```

- [ ] **Step 3: Snapshot agent config files before any install (supply-chain pre-check)**

```bash
{
  find ~/.claude ~/.codex ~/.config -name "*.json" -o -name "*.yaml" -o -name "*.toml" 2>/dev/null | sort
} > "$ARTIFACTS_DIR/config-snapshot-before.txt" 2>/dev/null || true
echo "Pre-install snapshot: $(wc -l < "$ARTIFACTS_DIR/config-snapshot-before.txt") files recorded"
```

- [ ] **Step 4: Confirm current HEAD and save working SHA for later restore**

```bash
ORIGINAL_SHA=$(git -C /workspace/markethawk rev-parse HEAD)
ORIGINAL_BRANCH=$(git -C /workspace/markethawk branch --show-current)
echo "ORIGINAL_SHA=$ORIGINAL_SHA" > "$ARTIFACTS_DIR/git-state.txt"
echo "ORIGINAL_BRANCH=$ORIGINAL_BRANCH" >> "$ARTIFACTS_DIR/git-state.txt"
echo "Git state saved: $ORIGINAL_BRANCH @ $ORIGINAL_SHA"
```

---

## Task 1: Safe Installation, Pinned Version, and Supply-Chain Check

**Files:** `$ARTIFACTS_DIR/cbm-install/` (populate), `$ARTIFACTS_DIR/config-snapshot-after.txt` (create), `$ARTIFACTS_DIR/cbm-recommendation.md` (update)

Covers spec requirements 1 (safe install), 2 (pinned version), and 3 (supply-chain check).

- [ ] **Step 1: Identify install mechanism and latest stable release**

```bash
# Check PyPI first (Python package)
PYPI_VERSIONS=$(pip index versions codebase-memory-mcp 2>/dev/null || true)
echo "PyPI versions found: $PYPI_VERSIONS"

# Check GitHub releases (binary or source)
GH_RELEASES=$(gh release list --repo DeusData/codebase-memory-mcp --limit 5 2>/dev/null || true)
echo "GitHub releases found:"
echo "$GH_RELEASES"

# Check npm registry (MCP tools often ship as npm packages)
NPM_INFO=$(npm view codebase-memory-mcp version 2>/dev/null || true)
echo "npm version found: $NPM_INFO"
```

Determine `INSTALL_MODE` from this output: prefer `binary` if a Linux binary asset exists in GH releases, then `pip` if on PyPI, then `npm`, then fail.

- [ ] **Step 2: Install to $ARTIFACTS_DIR (never to system paths)**

**Binary path** — if GH releases has a `linux-x64` or `linux_amd64` asset:
```bash
PINNED_TAG=$(gh release list --repo DeusData/codebase-memory-mcp --limit 1 --json tagName --jq '.[0].tagName' 2>/dev/null)
ASSET_URL=$(gh release view "$PINNED_TAG" --repo DeusData/codebase-memory-mcp --json assets \
  --jq '.assets[] | select(.name | test("linux")) | .url' 2>/dev/null | head -1)
curl -fsSL "$ASSET_URL" -o "$ARTIFACTS_DIR/cbm-install/cbm"
chmod +x "$ARTIFACTS_DIR/cbm-install/cbm"
CBM_CMD="$ARTIFACTS_DIR/cbm-install/cbm"
INSTALL_MODE="binary"
echo "Binary installed: $CBM_CMD"
```

**pip path** — if `codebase-memory-mcp` is on PyPI:
```bash
PINNED_VERSION=$(pip index versions codebase-memory-mcp 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
python3 -m pip install --quiet --target "$ARTIFACTS_DIR/cbm-install/lib" "codebase-memory-mcp==${PINNED_VERSION}"
export PYTHONPATH="$ARTIFACTS_DIR/cbm-install/lib:${PYTHONPATH:-}"
CBM_CMD="python3 -m codebase_memory_mcp"
INSTALL_MODE="pip"
PINNED_TAG="$PINNED_VERSION"
echo "pip installed to $ARTIFACTS_DIR/cbm-install/lib, PYTHONPATH updated"
```

**npm path** — if published to npm:
```bash
PINNED_VERSION=$(npm view codebase-memory-mcp version 2>/dev/null)
npm install --prefix "$ARTIFACTS_DIR/cbm-install/node" --save-exact "codebase-memory-mcp@${PINNED_VERSION}"
CBM_CMD="node $ARTIFACTS_DIR/cbm-install/node/node_modules/.bin/codebase-memory-mcp"
INSTALL_MODE="npm"
PINNED_TAG="$PINNED_VERSION"
echo "npm installed to $ARTIFACTS_DIR/cbm-install/node"
```

Set these variables and export them before proceeding:
```bash
echo "INSTALL_MODE=$INSTALL_MODE" >> "$ARTIFACTS_DIR/git-state.txt"
echo "PINNED_TAG=$PINNED_TAG" >> "$ARTIFACTS_DIR/git-state.txt"
echo "CBM_CMD=$CBM_CMD" >> "$ARTIFACTS_DIR/git-state.txt"
```

- [ ] **Step 3: Verify binary/package integrity (checksum if available)**

```bash
# For binary installs: try to fetch SHA256 from the release assets
SHA256_URL=$(gh release view "$PINNED_TAG" --repo DeusData/codebase-memory-mcp --json assets \
  --jq '.assets[] | select(.name | test("sha256|checksum|SHA256")) | .url' 2>/dev/null | head -1)
if [ -n "$SHA256_URL" ]; then
  EXPECTED_SHA=$(curl -fsSL "$SHA256_URL" | awk '{print $1}')
  ACTUAL_SHA=$(sha256sum "$ARTIFACTS_DIR/cbm-install/cbm" | awk '{print $1}')
  if [ "$EXPECTED_SHA" = "$ACTUAL_SHA" ]; then
    CHECKSUM_RESULT="verified (SHA256 match)"
  else
    CHECKSUM_RESULT="MISMATCH — expected $EXPECTED_SHA got $ACTUAL_SHA"
    echo "ERROR: checksum mismatch — aborting" && exit 1
  fi
else
  CHECKSUM_RESULT="no checksum asset published for this release"
fi
echo "Checksum: $CHECKSUM_RESULT"
```

For pip/npm installs, note whether the package publishes provenance attestations:
```bash
# pip: check for provenance
pip download --no-deps --dest "$ARTIFACTS_DIR/cbm-install/dist" "codebase-memory-mcp==${PINNED_TAG}" 2>/dev/null
WHEEL_FILE=$(ls "$ARTIFACTS_DIR/cbm-install/dist/"*.whl 2>/dev/null | head -1)
[ -n "$WHEEL_FILE" ] && CHECKSUM_RESULT="wheel hash: $(sha256sum "$WHEEL_FILE" | awk '{print $1}')" || true
```

- [ ] **Step 4: Supply-chain check — verify no agent config mutation**

```bash
{
  find ~/.claude ~/.codex ~/.config -name "*.json" -o -name "*.yaml" -o -name "*.toml" 2>/dev/null | sort
} > "$ARTIFACTS_DIR/config-snapshot-after.txt" 2>/dev/null || true

# Diff before vs after
NEW_FILES=$(comm -13 "$ARTIFACTS_DIR/config-snapshot-before.txt" "$ARTIFACTS_DIR/config-snapshot-after.txt" || true)
if [ -n "$NEW_FILES" ]; then
  MUTATION_RISK="HIGH — installer wrote to agent config paths: $NEW_FILES"
  echo "SUPPLY_CHAIN_RISK: $NEW_FILES"
else
  MUTATION_RISK="none — no agent config files created or modified by install"
  echo "Supply-chain check: clean"
fi
```

- [ ] **Step 5: Update recommendation document with supply-chain findings**

```bash
python3 - << 'PYEOF'
import re, os

REC = os.environ.get("ARTIFACTS_DIR") + "/cbm-recommendation.md"
content = open(REC).read()

PINNED_TAG  = open(os.environ["ARTIFACTS_DIR"] + "/git-state.txt").read()
PINNED_TAG  = dict(l.split("=",1) for l in PINNED_TAG.splitlines() if "=" in l).get("PINNED_TAG","UNKNOWN")
INSTALL_MODE = dict(l.split("=",1) for l in open(os.environ["ARTIFACTS_DIR"]+"/git-state.txt").read().splitlines() if "=" in l).get("INSTALL_MODE","UNKNOWN")

content = content.replace("(populated in Task 1) [version]", PINNED_TAG)
content = re.sub(r"\*\*Pinned version:\*\* \(populated in Task 1\)", f"**Pinned version:** {PINNED_TAG} ({INSTALL_MODE})", content)
open(REC, "w").write(content)
print("Recommendation doc updated with version info")
PYEOF

# Append supply-chain section
cat >> "$ARTIFACTS_DIR/cbm-recommendation.md" << SECTION

---
## Supply-Chain Details

- **Install mode:** $INSTALL_MODE
- **Pinned ref:** $PINNED_TAG
- **Checksum:** $CHECKSUM_RESULT
- **Agent config mutation:** $MUTATION_RISK
SECTION
echo "Supply-chain section written"
```

If `MUTATION_RISK` contains "HIGH", the recommendation tier is automatically `no-go`. Record and stop:
```bash
if echo "$MUTATION_RISK" | grep -q "^HIGH"; then
  echo "Recommendation: no-go" >> "$ARTIFACTS_DIR/cbm-recommendation.md"
  echo "Evidence: installer mutated agent config files" >> "$ARTIFACTS_DIR/cbm-recommendation.md"
  echo "AUTO NO-GO: installer mutated agent configs — skip to Task 7 (publish)"
fi
```

---

## Task 2: Index MarketHawk

**Files:** `$ARTIFACTS_DIR/index-log.txt` (create), `$ARTIFACTS_DIR/cbm-recommendation.md` (update)

Covers spec requirement 4 (index MarketHawk, record time + cache size).

- [ ] **Step 1: Verify CBM_CMD is set (load from saved state if needed)**

```bash
if [ -z "${CBM_CMD:-}" ]; then
  source <(grep -E '^(CBM_CMD|INSTALL_MODE|PINNED_TAG)=' "$ARTIFACTS_DIR/git-state.txt")
fi
echo "Using CBM_CMD: $CBM_CMD"
$CBM_CMD --version 2>&1 || $CBM_CMD version 2>&1 || echo "(--version flag not supported)"
```

- [ ] **Step 2: Run the indexer against /workspace/markethawk**

```bash
START_TS=$(date +%s)
$CBM_CMD index \
  --repo /workspace/markethawk \
  --cache-dir "$ARTIFACTS_DIR/cbm-cache" \
  2>&1 | tee "$ARTIFACTS_DIR/index-log.txt"
INDEX_EXIT=$?
END_TS=$(date +%s)
INDEX_TIME=$((END_TS - START_TS))
echo "Index exit code: $INDEX_EXIT, elapsed: ${INDEX_TIME}s"
```

Note: if `--cache-dir` is not a supported flag, try `--output` or `--index-dir`:
```bash
# Fallback flag names to try in order
for FLAG in "--cache-dir" "--output" "--index-dir" "--store"; do
  if $CBM_CMD index --help 2>&1 | grep -q "${FLAG#--}"; then
    echo "Index flag: $FLAG"
    break
  fi
done
```

- [ ] **Step 3: Record index time and cache size**

```bash
CACHE_SIZE=$(du -sh "$ARTIFACTS_DIR/cbm-cache" 2>/dev/null | awk '{print $1}' || echo "unknown")
echo "Index time: ${INDEX_TIME}s"
echo "Cache size: $CACHE_SIZE"

# Update recommendation doc
sed -i "s|(populated in Task 2) \[time\]|${INDEX_TIME}s|" "$ARTIFACTS_DIR/cbm-recommendation.md" 2>/dev/null || true
cat >> "$ARTIFACTS_DIR/cbm-recommendation.md" << SECTION

---
## Index Metrics

- **Index time:** ${INDEX_TIME}s
- **Cache size on disk:** $CACHE_SIZE
- **Exit code:** $INDEX_EXIT
- **Errors/warnings:** $(grep -ic "error\|warn" "$ARTIFACTS_DIR/index-log.txt" 2>/dev/null || echo 0) lines
SECTION
```

If `INDEX_EXIT != 0`, record as a failure mode and check if the tool requires network:
```bash
if [ "$INDEX_EXIT" != "0" ]; then
  echo "INDEX_FAILED: tool exited non-zero" | tee -a "$ARTIFACTS_DIR/cbm-recommendation.md"
  # Check if it attempted outbound network calls (cloud-API dependency → no-go)
  grep -iE "api\.|http|connect|timeout|network" "$ARTIFACTS_DIR/index-log.txt" \
    | tee -a "$ARTIFACTS_DIR/cbm-recommendation.md" || true
fi
```

- [ ] **Step 4: Smoke test — verify the index produced queryable output**

```bash
# Try a simple lookup to confirm the index is usable
TEST_OUT=$($CBM_CMD lookup --symbol ScannerService \
  --cache-dir "$ARTIFACTS_DIR/cbm-cache" 2>&1 || true)
echo "Smoke test output (first 5 lines):"
echo "$TEST_OUT" | head -5

# Record if the tool requires network at query time
if echo "$TEST_OUT" | grep -iE "api\.|connect|timeout|403|401|network"; then
  echo "NETWORK_REQUIRED_AT_QUERY_TIME=true" >> "$ARTIFACTS_DIR/git-state.txt"
  echo "AUTO NO-GO candidate: tool requires network to serve queries"
  cat >> "$ARTIFACTS_DIR/cbm-recommendation.md" << 'NOTE'

### ⚠️ Network dependency detected
The tool appears to require a cloud API call to serve queries (not just at index time).
Per the spec assumption, this is an automatic no-go for factory use.
NOTE
fi
```

---

## Task 3: Query Evaluation — All 8 Types

**Files:** `$ARTIFACTS_DIR/cbm-queries.md` (create)

Covers spec requirement 5 (exercise all query types from the evaluation checklist).

- [ ] **Step 1: Initialize query output doc and load CBM_CMD**

```bash
if [ -z "${CBM_CMD:-}" ]; then
  source <(grep -E '^(CBM_CMD|INSTALL_MODE|PINNED_TAG)=' "$ARTIFACTS_DIR/git-state.txt")
fi

cat > "$ARTIFACTS_DIR/cbm-queries.md" << 'HDR'
# codebase-memory-mcp Query Evaluation — MarketHawk (#675)

Precision scoring: 5=perfect (right file+line, no noise), 3=usable (right file, some noise), 1=poor (wrong or missing), 0=no output.
Recall note: "(missed X)" means grep finds X but CBM did not return it.

HDR
```

- [ ] **Step 2: Python/FastAPI symbol queries**

```bash
for QUERY in "ScannerService" "calculate_day_metrics"; do
  echo "## Query: Python/FastAPI — $QUERY" | tee -a "$ARTIFACTS_DIR/cbm-queries.md"
  RESULT=$($CBM_CMD lookup --symbol "$QUERY" --cache-dir "$ARTIFACTS_DIR/cbm-cache" 2>&1 \
    || $CBM_CMD search --query "$QUERY" --cache-dir "$ARTIFACTS_DIR/cbm-cache" 2>&1 \
    || echo "LOOKUP_FAILED")
  echo "$RESULT" | tee -a "$ARTIFACTS_DIR/cbm-queries.md"
  # Verify expected file appears in output
  if echo "$RESULT" | grep -q "scanner.py"; then
    echo "✅ Found expected file: backend/app/services/scanner.py" | tee -a "$ARTIFACTS_DIR/cbm-queries.md"
  else
    GREP_RESULT=$(grep -rn "$QUERY" /workspace/markethawk/backend/app/ --include="*.py" -l 2>/dev/null | head -3)
    echo "⚠️  grep finds: $GREP_RESULT" | tee -a "$ARTIFACTS_DIR/cbm-queries.md"
  fi
  echo "" >> "$ARTIFACTS_DIR/cbm-queries.md"
done
```

- [ ] **Step 3: SQLAlchemy model queries**

```bash
for QUERY in "ScannerEvent" "StockUniverse"; do
  echo "## Query: SQLAlchemy model — $QUERY" | tee -a "$ARTIFACTS_DIR/cbm-queries.md"
  RESULT=$($CBM_CMD lookup --symbol "$QUERY" --cache-dir "$ARTIFACTS_DIR/cbm-cache" 2>&1 \
    || $CBM_CMD search --query "$QUERY" --cache-dir "$ARTIFACTS_DIR/cbm-cache" 2>&1 \
    || echo "LOOKUP_FAILED")
  echo "$RESULT" | tee -a "$ARTIFACTS_DIR/cbm-queries.md"
  if echo "$RESULT" | grep -qE "models/|scanner_event|stock_universe"; then
    echo "✅ Model definition found" | tee -a "$ARTIFACTS_DIR/cbm-queries.md"
  else
    echo "⚠️  grep finds: $(grep -rn "class $QUERY" /workspace/markethawk/backend/app/models/ -l 2>/dev/null)" \
      | tee -a "$ARTIFACTS_DIR/cbm-queries.md"
  fi
  echo "" >> "$ARTIFACTS_DIR/cbm-queries.md"
done
```

- [ ] **Step 4: Frontend/TypeScript symbol queries**

```bash
for QUERY in "UniverseFormModal" "useScannerState"; do
  echo "## Query: Frontend/TS — $QUERY" | tee -a "$ARTIFACTS_DIR/cbm-queries.md"
  RESULT=$($CBM_CMD lookup --symbol "$QUERY" --cache-dir "$ARTIFACTS_DIR/cbm-cache" 2>&1 \
    || $CBM_CMD search --query "$QUERY" --cache-dir "$ARTIFACTS_DIR/cbm-cache" 2>&1 \
    || echo "LOOKUP_FAILED")
  echo "$RESULT" | tee -a "$ARTIFACTS_DIR/cbm-queries.md"
  GREP_RESULT=$(grep -rn "$QUERY" /workspace/markethawk/frontend/src/ --include="*.ts" --include="*.tsx" -l 2>/dev/null | head -3)
  echo "grep baseline: $GREP_RESULT" | tee -a "$ARTIFACTS_DIR/cbm-queries.md"
  echo "" >> "$ARTIFACTS_DIR/cbm-queries.md"
done
```

- [ ] **Step 5: Docker/YAML infrastructure queries**

```bash
for QUERY in "docker-socket-proxy-factory" "celery-beat"; do
  echo "## Query: Docker/YAML — $QUERY" | tee -a "$ARTIFACTS_DIR/cbm-queries.md"
  RESULT=$($CBM_CMD lookup --symbol "$QUERY" --cache-dir "$ARTIFACTS_DIR/cbm-cache" 2>&1 \
    || $CBM_CMD search --query "$QUERY" --cache-dir "$ARTIFACTS_DIR/cbm-cache" 2>&1 \
    || echo "LOOKUP_FAILED")
  echo "$RESULT" | tee -a "$ARTIFACTS_DIR/cbm-queries.md"
  GREP_RESULT=$(grep -rn "$QUERY" /workspace/markethawk/ --include="*.yml" --include="*.yaml" -l 2>/dev/null | head -3)
  echo "grep baseline: $GREP_RESULT" | tee -a "$ARTIFACTS_DIR/cbm-queries.md"
  echo "" >> "$ARTIFACTS_DIR/cbm-queries.md"
done
```

- [ ] **Step 6: Structural search and architecture summary**

```bash
echo "## Query: Structural search — 'what services does the backend expose?'" \
  | tee -a "$ARTIFACTS_DIR/cbm-queries.md"
$CBM_CMD search \
  --query "what services does the backend expose" \
  --cache-dir "$ARTIFACTS_DIR/cbm-cache" 2>&1 \
  | tee -a "$ARTIFACTS_DIR/cbm-queries.md" || echo "SEARCH_FAILED" | tee -a "$ARTIFACTS_DIR/cbm-queries.md"
echo "" >> "$ARTIFACTS_DIR/cbm-queries.md"

echo "## Query: Architecture summary — 'summarize the scanner pipeline'" \
  | tee -a "$ARTIFACTS_DIR/cbm-queries.md"
$CBM_CMD search \
  --query "summarize the scanner pipeline" \
  --cache-dir "$ARTIFACTS_DIR/cbm-cache" 2>&1 \
  | tee -a "$ARTIFACTS_DIR/cbm-queries.md" || echo "SEARCH_FAILED" | tee -a "$ARTIFACTS_DIR/cbm-queries.md"
echo "" >> "$ARTIFACTS_DIR/cbm-queries.md"
```

- [ ] **Step 7: Changed-symbol impact query**

```bash
echo "## Query: Changed-symbol impact — base a662669 vs HEAD" \
  | tee -a "$ARTIFACTS_DIR/cbm-queries.md"
# Use the merge-base SHA for the impact query (spec uses a662669 as base)
$CBM_CMD impact \
  --base a662669 \
  --head HEAD \
  --cache-dir "$ARTIFACTS_DIR/cbm-cache" \
  --repo /workspace/markethawk 2>&1 \
  | tee -a "$ARTIFACTS_DIR/cbm-queries.md" \
  || $CBM_CMD diff \
       --from a662669 \
       --to HEAD \
       --cache-dir "$ARTIFACTS_DIR/cbm-cache" 2>&1 \
  | tee -a "$ARTIFACTS_DIR/cbm-queries.md" \
  || echo "IMPACT_QUERY_FAILED" | tee -a "$ARTIFACTS_DIR/cbm-queries.md"
echo "" >> "$ARTIFACTS_DIR/cbm-queries.md"
```

- [ ] **Step 8: Call-path / caller-callee tracing**

```bash
echo "## Query: Call-path — callers of ScannerService.calculate_day_metrics" \
  | tee -a "$ARTIFACTS_DIR/cbm-queries.md"
$CBM_CMD callers \
  --symbol "ScannerService.calculate_day_metrics" \
  --cache-dir "$ARTIFACTS_DIR/cbm-cache" 2>&1 \
  | tee -a "$ARTIFACTS_DIR/cbm-queries.md" \
  || $CBM_CMD call-graph \
       --symbol "calculate_day_metrics" \
       --cache-dir "$ARTIFACTS_DIR/cbm-cache" 2>&1 \
  | tee -a "$ARTIFACTS_DIR/cbm-queries.md" \
  || echo "CALL_PATH_FAILED" | tee -a "$ARTIFACTS_DIR/cbm-queries.md"

# grep baseline for comparison
echo "grep baseline callers:" | tee -a "$ARTIFACTS_DIR/cbm-queries.md"
grep -rn "calculate_day_metrics" /workspace/markethawk/backend/ --include="*.py" \
  | tee -a "$ARTIFACTS_DIR/cbm-queries.md"
echo "" >> "$ARTIFACTS_DIR/cbm-queries.md"
```

- [ ] **Step 9: Write query quality summary to recommendation doc**

```bash
# Count "FAILED" occurrences across query output
FAILED_COUNT=$(grep -c "FAILED" "$ARTIFACTS_DIR/cbm-queries.md" || echo 0)
TOTAL_QUERIES=8

cat >> "$ARTIFACTS_DIR/cbm-recommendation.md" << SECTION

---
## Query Quality Summary

- **Queries attempted:** $TOTAL_QUERIES
- **Queries with output:** $((TOTAL_QUERIES - FAILED_COUNT))
- **Queries that failed/returned nothing:** $FAILED_COUNT
- **Full query log:** \`\$ARTIFACTS_DIR/cbm-queries.md\`
- **Subjective assessment:** (see individual query sections in cbm-queries.md for precision/recall notes)
SECTION
echo "Query summary written"
```

---

## Task 4: Comparative Evaluation — Issue #287 (Backend Services, pre_pr_sha 9634dea)

**Files:** `$ARTIFACTS_DIR/context-graph-287.txt`, `$ARTIFACTS_DIR/context-grep-287.txt`, `$ARTIFACTS_DIR/token-counts.md` (create/update)

Covers spec requirement 6 for issue #287 (`test_stock_screener.py`, `test_futures_screener.py`, backend area).

- [ ] **Step 1: Check out at pre_pr_sha 9634dea and rebuild index**

```bash
# Reload env
if [ -z "${CBM_CMD:-}" ]; then
  source <(grep -E '^(CBM_CMD|INSTALL_MODE|PINNED_TAG)=' "$ARTIFACTS_DIR/git-state.txt")
fi

# Stash any uncommitted changes (should be none in factory)
git -C /workspace/markethawk stash 2>/dev/null || true

# Checkout the historical SHA
git -C /workspace/markethawk checkout 9634dea
echo "Checked out: $(git -C /workspace/markethawk rev-parse --short HEAD)"

# Rebuild index at this SHA
CACHE_287="$ARTIFACTS_DIR/cbm-cache-287"
mkdir -p "$CACHE_287"
$CBM_CMD index \
  --repo /workspace/markethawk \
  --cache-dir "$CACHE_287" \
  2>&1 | tail -5
echo "Index rebuilt at 9634dea"
```

- [ ] **Step 2: Fetch issue #287 body for context assembly**

```bash
ISSUE_287_BODY=$(gh issue view 287 --repo omniscient/markethawk --json body --jq '.body')
echo "$ISSUE_287_BODY" > "$ARTIFACTS_DIR/issue-287-body.txt"
echo "Issue #287 body fetched: $(wc -c < "$ARTIFACTS_DIR/issue-287-body.txt") chars"
```

- [ ] **Step 3: Assemble CBM context for issue #287**

```bash
# Ask codebase-memory-mcp for relevant context given the issue
$CBM_CMD context \
  --query "$ISSUE_287_BODY" \
  --cache-dir "$CACHE_287" \
  2>&1 > "$ARTIFACTS_DIR/context-graph-287.txt" \
|| $CBM_CMD search \
     --query "$(head -3 "$ARTIFACTS_DIR/issue-287-body.txt")" \
     --cache-dir "$CACHE_287" \
     2>&1 > "$ARTIFACTS_DIR/context-graph-287.txt" \
|| echo "GRAPH_CONTEXT_FAILED" > "$ARTIFACTS_DIR/context-graph-287.txt"
echo "CBM context: $(wc -c < "$ARTIFACTS_DIR/context-graph-287.txt") chars"
```

- [ ] **Step 4: Assemble grep/read baseline context for issue #287**

This simulates the current factory exploration: read CLAUDE.md + ARCHITECTURE.md, extract symbols from the issue body, grep for them, read the top matching files.

```bash
{
  cat /workspace/markethawk/CLAUDE.md
  cat /workspace/markethawk/ARCHITECTURE.md
  # Extract capitalized symbols from issue body
  SYMBOLS=$(grep -oE '\b[A-Z][a-zA-Z]{3,}(Service|Model|Router|Task|Handler|Event|Config|Schema)\b' \
    "$ARTIFACTS_DIR/issue-287-body.txt" | sort -u | head -10)
  echo "# Symbols extracted: $SYMBOLS"
  for SYM in $SYMBOLS; do
    FILES=$(grep -rn "$SYM" /workspace/markethawk/backend/app/ \
      --include="*.py" -l 2>/dev/null | head -3)
    for F in $FILES; do
      echo "# --- $F ---"
      head -150 "$F"
    done
  done
  # Always include the scanner service since issue #287 is "Backend services"
  head -200 /workspace/markethawk/backend/app/services/scanner.py 2>/dev/null || true
} > "$ARTIFACTS_DIR/context-grep-287.txt"
echo "Grep/read context: $(wc -c < "$ARTIFACTS_DIR/context-grep-287.txt") chars"
```

- [ ] **Step 5: Count tokens for both contexts**

```bash
python3 - << 'PYEOF'
import os, sys

ARTIFACTS = os.environ["ARTIFACTS_DIR"]

def count_tokens(path):
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(open(path).read()))
    except ImportError:
        # Fallback: ~4 chars per token
        return len(open(path).read()) // 4

graph_tokens = count_tokens(f"{ARTIFACTS}/context-graph-287.txt")
grep_tokens  = count_tokens(f"{ARTIFACTS}/context-grep-287.txt")
delta        = grep_tokens - graph_tokens
pct          = (delta / grep_tokens * 100) if grep_tokens > 0 else 0

print(f"Issue #287 — graph: {graph_tokens} tokens | grep/read: {grep_tokens} tokens | delta: {delta} ({pct:.1f}%)")

with open(f"{ARTIFACTS}/token-counts.md", "w") as f:
    f.write("# Token Counts: CBM vs Grep/Read\n\n")
    f.write(f"| Issue | CBM tokens | Grep/read tokens | Delta | % savings |\n")
    f.write(f"|---|---|---|---|---|\n")
    f.write(f"| #287 (backend) | {graph_tokens} | {grep_tokens} | {delta} | {pct:.1f}% |\n")
PYEOF
```

- [ ] **Step 6: Restore HEAD and record findings**

```bash
# Restore to original branch/SHA
git -C /workspace/markethawk checkout "$(cat "$ARTIFACTS_DIR/git-state.txt" | grep ORIGINAL_BRANCH | cut -d= -f2)" 2>/dev/null \
  || git -C /workspace/markethawk checkout "$(cat "$ARTIFACTS_DIR/git-state.txt" | grep ORIGINAL_SHA | cut -d= -f2)"
echo "Restored to: $(git -C /workspace/markethawk rev-parse --short HEAD)"

# Check if CBM missed any oracle test files
for ORACLE in test_stock_screener.py test_futures_screener.py; do
  if ! grep -q "$ORACLE" "$ARTIFACTS_DIR/context-graph-287.txt"; then
    echo "CONTEXT_GAP: CBM did not surface $ORACLE — safety-critical context missed" \
      | tee -a "$ARTIFACTS_DIR/cbm-recommendation.md"
  fi
done
```

---

## Task 5: Comparative Evaluation — Issue #249 (Frontend Indicators, pre_pr_sha e54e19a)

**Files:** `$ARTIFACTS_DIR/context-graph-249.txt`, `$ARTIFACTS_DIR/context-grep-249.txt`, `$ARTIFACTS_DIR/token-counts.md` (update)

Covers spec requirement 6 for issue #249 (`indicators.test.ts`, frontend area).

- [ ] **Step 1: Check out at pre_pr_sha e54e19a and rebuild index**

```bash
if [ -z "${CBM_CMD:-}" ]; then
  source <(grep -E '^(CBM_CMD|INSTALL_MODE|PINNED_TAG)=' "$ARTIFACTS_DIR/git-state.txt")
fi

git -C /workspace/markethawk stash 2>/dev/null || true
git -C /workspace/markethawk checkout e54e19a
echo "Checked out: $(git -C /workspace/markethawk rev-parse --short HEAD)"

CACHE_249="$ARTIFACTS_DIR/cbm-cache-249"
mkdir -p "$CACHE_249"
$CBM_CMD index --repo /workspace/markethawk --cache-dir "$CACHE_249" 2>&1 | tail -5
echo "Index rebuilt at e54e19a"
```

- [ ] **Step 2: Fetch issue #249 body**

```bash
ISSUE_249_BODY=$(gh issue view 249 --repo omniscient/markethawk --json body --jq '.body')
echo "$ISSUE_249_BODY" > "$ARTIFACTS_DIR/issue-249-body.txt"
```

- [ ] **Step 3: Assemble CBM context for issue #249**

```bash
$CBM_CMD context \
  --query "$ISSUE_249_BODY" \
  --cache-dir "$CACHE_249" \
  2>&1 > "$ARTIFACTS_DIR/context-graph-249.txt" \
|| $CBM_CMD search \
     --query "$(head -3 "$ARTIFACTS_DIR/issue-249-body.txt")" \
     --cache-dir "$CACHE_249" \
     2>&1 > "$ARTIFACTS_DIR/context-graph-249.txt" \
|| echo "GRAPH_CONTEXT_FAILED" > "$ARTIFACTS_DIR/context-graph-249.txt"
```

- [ ] **Step 4: Assemble grep/read baseline for issue #249**

```bash
{
  cat /workspace/markethawk/CLAUDE.md
  cat /workspace/markethawk/ARCHITECTURE.md
  SYMBOLS=$(grep -oE '\b[A-Z][a-zA-Z]{3,}(Component|Hook|Modal|Form|Table|Chart|Panel)\b|\buse[A-Z][a-zA-Z]+\b' \
    "$ARTIFACTS_DIR/issue-249-body.txt" | sort -u | head -10)
  for SYM in $SYMBOLS; do
    FILES=$(grep -rn "$SYM" /workspace/markethawk/frontend/src/ \
      --include="*.ts" --include="*.tsx" -l 2>/dev/null | head -3)
    for F in $FILES; do
      echo "# --- $F ---"
      head -150 "$F"
    done
  done
  # Include chart_indicators.py since this is an indicators issue
  head -200 /workspace/markethawk/backend/app/services/chart_indicators.py 2>/dev/null || true
} > "$ARTIFACTS_DIR/context-grep-249.txt"
```

- [ ] **Step 5: Count tokens and update token-counts.md**

```bash
python3 - << 'PYEOF'
import os

ARTIFACTS = os.environ["ARTIFACTS_DIR"]

def count_tokens(path):
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(open(path).read()))
    except ImportError:
        return len(open(path).read()) // 4

graph_tokens = count_tokens(f"{ARTIFACTS}/context-graph-249.txt")
grep_tokens  = count_tokens(f"{ARTIFACTS}/context-grep-249.txt")
delta        = grep_tokens - graph_tokens
pct          = (delta / grep_tokens * 100) if grep_tokens > 0 else 0

print(f"Issue #249 — graph: {graph_tokens} tokens | grep/read: {grep_tokens} tokens | delta: {delta} ({pct:.1f}%)")

# Append to token-counts.md
with open(f"{ARTIFACTS}/token-counts.md", "a") as f:
    f.write(f"| #249 (frontend) | {graph_tokens} | {grep_tokens} | {delta} | {pct:.1f}% |\n")
PYEOF
```

- [ ] **Step 6: Restore HEAD and check for context gaps**

```bash
git -C /workspace/markethawk checkout "$(grep ORIGINAL_BRANCH "$ARTIFACTS_DIR/git-state.txt" | cut -d= -f2)" 2>/dev/null \
  || git -C /workspace/markethawk checkout "$(grep ORIGINAL_SHA "$ARTIFACTS_DIR/git-state.txt" | cut -d= -f2)"

# Oracle file check
if ! grep -q "indicators.test.ts\|chart_indicators" "$ARTIFACTS_DIR/context-graph-249.txt"; then
  echo "CONTEXT_GAP: CBM did not surface indicators files for issue #249" \
    | tee -a "$ARTIFACTS_DIR/cbm-recommendation.md"
fi
```

---

## Task 6: Comparative Evaluation — Issue #224 (Dark Factory Pipeline, pre_pr_sha a662669)

**Files:** `$ARTIFACTS_DIR/context-graph-224.txt`, `$ARTIFACTS_DIR/context-grep-224.txt`, `$ARTIFACTS_DIR/token-counts.md` (update)

Covers spec requirement 6 for issue #224 (`test_workflow_or_join.py`, dark-factory area).

- [ ] **Step 1: Check out at pre_pr_sha a662669 and rebuild index**

```bash
if [ -z "${CBM_CMD:-}" ]; then
  source <(grep -E '^(CBM_CMD|INSTALL_MODE|PINNED_TAG)=' "$ARTIFACTS_DIR/git-state.txt")
fi

git -C /workspace/markethawk stash 2>/dev/null || true
git -C /workspace/markethawk checkout a662669
echo "Checked out: $(git -C /workspace/markethawk rev-parse --short HEAD)"

CACHE_224="$ARTIFACTS_DIR/cbm-cache-224"
mkdir -p "$CACHE_224"
$CBM_CMD index --repo /workspace/markethawk --cache-dir "$CACHE_224" 2>&1 | tail -5
echo "Index rebuilt at a662669"
```

- [ ] **Step 2: Fetch issue #224 body**

```bash
ISSUE_224_BODY=$(gh issue view 224 --repo omniscient/markethawk --json body --jq '.body')
echo "$ISSUE_224_BODY" > "$ARTIFACTS_DIR/issue-224-body.txt"
```

- [ ] **Step 3: Assemble CBM context for issue #224**

```bash
$CBM_CMD context \
  --query "$ISSUE_224_BODY" \
  --cache-dir "$CACHE_224" \
  2>&1 > "$ARTIFACTS_DIR/context-graph-224.txt" \
|| $CBM_CMD search \
     --query "$(head -3 "$ARTIFACTS_DIR/issue-224-body.txt")" \
     --cache-dir "$CACHE_224" \
     2>&1 > "$ARTIFACTS_DIR/context-graph-224.txt" \
|| echo "GRAPH_CONTEXT_FAILED" > "$ARTIFACTS_DIR/context-graph-224.txt"
```

- [ ] **Step 4: Assemble grep/read baseline for issue #224**

```bash
{
  cat /workspace/markethawk/CLAUDE.md
  cat /workspace/markethawk/ARCHITECTURE.md
  # Dark-factory issue: grep factory scripts and workflow YAML
  SYMBOLS=$(grep -oE '\b(OR.join|trigger_rule|dispatch|archon|workflow|dag|pipeline)\b' \
    "$ARTIFACTS_DIR/issue-224-body.txt" | sort -u | head -10)
  for SYM in $SYMBOLS; do
    FILES=$(grep -rn "$SYM" /workspace/markethawk/dark-factory/ -l 2>/dev/null | head -3)
    for F in $FILES; do
      echo "# --- $F ---"
      head -150 "$F"
    done
  done
  # Always include the workflow YAML since this is a DAG issue
  head -200 /workspace/markethawk/.archon/commands/archon-dark-factory.yaml 2>/dev/null || true
  head -100 /workspace/markethawk/dark-factory/scripts/check_workflow_dag.py 2>/dev/null || true
} > "$ARTIFACTS_DIR/context-grep-224.txt"
```

- [ ] **Step 5: Count tokens and update token-counts.md**

```bash
python3 - << 'PYEOF'
import os

ARTIFACTS = os.environ["ARTIFACTS_DIR"]

def count_tokens(path):
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(open(path).read()))
    except ImportError:
        return len(open(path).read()) // 4

graph_tokens = count_tokens(f"{ARTIFACTS}/context-graph-224.txt")
grep_tokens  = count_tokens(f"{ARTIFACTS}/context-grep-224.txt")
delta        = grep_tokens - graph_tokens
pct          = (delta / grep_tokens * 100) if grep_tokens > 0 else 0

print(f"Issue #224 — graph: {graph_tokens} tokens | grep/read: {grep_tokens} tokens | delta: {delta} ({pct:.1f}%)")

with open(f"{ARTIFACTS}/token-counts.md", "a") as f:
    f.write(f"| #224 (dark factory) | {graph_tokens} | {grep_tokens} | {delta} | {pct:.1f}% |\n")
PYEOF
```

- [ ] **Step 6: Restore HEAD and check for context gaps**

```bash
git -C /workspace/markethawk checkout "$(grep ORIGINAL_BRANCH "$ARTIFACTS_DIR/git-state.txt" | cut -d= -f2)" 2>/dev/null \
  || git -C /workspace/markethawk checkout "$(grep ORIGINAL_SHA "$ARTIFACTS_DIR/git-state.txt" | cut -d= -f2)"

if ! grep -q "workflow_or_join\|archon-dark-factory" "$ARTIFACTS_DIR/context-graph-224.txt"; then
  echo "CONTEXT_GAP: CBM did not surface DAG/workflow files for issue #224" \
    | tee -a "$ARTIFACTS_DIR/cbm-recommendation.md"
fi
```

---

## Task 7: Decision Tree, Recommendation, and Publish

**Files:** `$ARTIFACTS_DIR/cbm-recommendation.md` (finalize), GitHub comment on #675

Covers spec requirements 7 (recommendation) and 8 (no factory behavior change — verification).

- [ ] **Step 1: Read token-counts.md and determine if thresholds are met**

```bash
echo "=== Token counts ==="
cat "$ARTIFACTS_DIR/token-counts.md"

# Extract percentages and compute average
python3 - << 'PYEOF'
import re, os

tc = open(os.environ["ARTIFACTS_DIR"] + "/token-counts.md").read()
pcts = [float(m) for m in re.findall(r'\| ([\-\d.]+)% \|', tc)]
if pcts:
    avg = sum(pcts) / len(pcts)
    print(f"Average token savings: {avg:.1f}%")
    print(f"All issues >= 15%: {all(p >= 15 for p in pcts)}")
    print(f"All issues >= 10%: {all(p >= 10 for p in pcts)}")
    # Write for bash consumption
    with open(os.environ["ARTIFACTS_DIR"] + "/token-summary.txt", "w") as f:
        f.write(f"AVG_SAVINGS={avg:.1f}\n")
        f.write(f"ALL_GTE_15={'true' if all(p >= 15 for p in pcts) else 'false'}\n")
        f.write(f"ALL_GTE_10={'true' if all(p >= 10 for p in pcts) else 'false'}\n")
else:
    print("No token data parsed — defaulting to no-go")
    with open(os.environ["ARTIFACTS_DIR"] + "/token-summary.txt", "w") as f:
        f.write("AVG_SAVINGS=0\nALL_GTE_15=false\nALL_GTE_10=false\n")
PYEOF

source "$ARTIFACTS_DIR/token-summary.txt"
```

- [ ] **Step 2: Apply decision tree**

```bash
# Check preconditions
INDEX_FAILED=$(grep -c "INDEX_FAILED\|AUTO NO-GO" "$ARTIFACTS_DIR/cbm-recommendation.md" || echo 0)
MUTATION_HIGH=$(grep -c "^HIGH" "$ARTIFACTS_DIR/cbm-recommendation.md" 2>/dev/null \
  || grep -c "Installer config mutation risk:.*HIGH" "$ARTIFACTS_DIR/cbm-recommendation.md" || echo 0)
CONTEXT_GAPS=$(grep -c "CONTEXT_GAP" "$ARTIFACTS_DIR/cbm-recommendation.md" || echo 0)
FAILED_QUERIES=$(grep -c "FAILED" "$ARTIFACTS_DIR/cbm-queries.md" || echo 0)
NETWORK_REQUIRED=$(grep -c "NETWORK_REQUIRED_AT_QUERY_TIME=true" "$ARTIFACTS_DIR/git-state.txt" || echo 0)

source "$ARTIFACTS_DIR/token-summary.txt"

if [ "$INDEX_FAILED" -gt 0 ] || [ "$MUTATION_HIGH" -gt 0 ] || [ "$NETWORK_REQUIRED" -gt 0 ]; then
  TIER="no-go"
  TIER_REASON="Tool failed to install cleanly, installer mutated agent configs, or requires network for queries"
elif [ "$ALL_GTE_15" = "true" ] && [ "$CONTEXT_GAPS" -eq 0 ]; then
  # Check if impact/blast-radius signals are reliable
  IMPACT_FAILED=$(grep -c "IMPACT_QUERY_FAILED\|CALL_PATH_FAILED" "$ARTIFACTS_DIR/cbm-queries.md" || echo 0)
  if [ "$IMPACT_FAILED" -eq 0 ]; then
    TIER="gate-backed follow-up"
    TIER_REASON=">=15% token savings, no context gaps, and reliable blast-radius/impact signals"
  else
    TIER="context-pack backend"
    TIER_REASON=">=15% token savings and no context gaps, but impact/call-path queries unreliable"
  fi
elif [ "$ALL_GTE_10" = "false" ] || [ "$CONTEXT_GAPS" -gt 0 ]; then
  TIER="advisory-only"
  TIER_REASON="Token savings <10% across all issues, or safety-critical context gaps found"
elif [ "$ALL_GTE_15" = "false" ]; then
  TIER="advisory-only (borderline)"
  TIER_REASON="Savings in 10-15% range — document measured numbers; requires human judgment"
else
  TIER="context-pack backend"
  TIER_REASON=">=15% savings with no context gaps"
fi

echo "TIER=$TIER"
echo "TIER_REASON=$TIER_REASON"
```

- [ ] **Step 3: Finalize cbm-recommendation.md**

```bash
# Read current token counts table
TOKEN_TABLE=$(cat "$ARTIFACTS_DIR/token-counts.md")
SUPPLY_CHAIN_SECTION=$(grep -A 5 "## Supply-Chain Details" "$ARTIFACTS_DIR/cbm-recommendation.md" || true)

cat > "$ARTIFACTS_DIR/cbm-recommendation.md" << RECDOC
# codebase-memory-mcp Evaluation — MarketHawk Dark Factory (#675)

**Issue:** https://github.com/omniscient/markethawk/issues/675
**Future plan:** https://github.com/omniscient/markethawk/issues/674
**Spec:** docs/superpowers/specs/2026-06-28-codebase-memory-mcp-spike-design.md

## Recommendation: $TIER

**Reason:** $TIER_REASON

## Evidence

$SUPPLY_CHAIN_SECTION

### Index Metrics
$(grep -A 5 "## Index Metrics" "$ARTIFACTS_DIR/cbm-recommendation.md" 2>/dev/null || echo "(see index-log.txt)")

### Token Savings
$TOKEN_TABLE

### Query Quality Summary
$(grep -A 5 "## Query Quality Summary" "$ARTIFACTS_DIR/cbm-recommendation.md" 2>/dev/null || cat "$ARTIFACTS_DIR/cbm-queries.md" | grep "✅\|⚠️" | head -20)

### Failure Modes
$(grep "FAILED\|CONTEXT_GAP\|ERROR" "$ARTIFACTS_DIR/cbm-recommendation.md" | sort -u | head -20 || echo "None")

### Safety Concerns
$(grep "SUPPLY_CHAIN_RISK\|NETWORK_REQUIRED\|MUTATION" "$ARTIFACTS_DIR/cbm-recommendation.md" | sort -u || echo "None")

## Next Steps from #674

$(if [ "$TIER" = "no-go" ]; then
  echo "Halt. Do not proceed to #674. Risks documented above prevent safe adoption."
elif [ "$TIER" = "advisory-only" ]; then
  echo "Adopt as advisory context only. Do not wire into gates. Revisit if token savings improve."
elif [ "$TIER" = "context-pack backend" ]; then
  echo "Proceed to #674 Layer 1 (context-pack assembly). Do not enable gate-backed layers until blast-radius signal is verified."
elif echo "$TIER" | grep -q "gate-backed"; then
  echo "Proceed to #674 all layers including gate-backed follow-up. Start with Layer 1 (context-pack), then Layer 2 (blast-radius gate)."
fi)
RECDOC

echo "Final recommendation document written"
```

- [ ] **Step 4: Verify no factory behavior changes were made (acceptance criterion 3)**

```bash
# Check that no entrypoint.sh, settings.local.json, or ~/.claude paths were modified
MODIFIED_CONFIGS=$(git -C /workspace/markethawk diff --name-only HEAD 2>/dev/null \
  | grep -E "entrypoint\.sh|settings\.local\.json|\.claude/|\.codex/" || true)
if [ -n "$MODIFIED_CONFIGS" ]; then
  echo "OOS WARNING: factory config files modified — must revert: $MODIFIED_CONFIGS"
  git -C /workspace/markethawk checkout HEAD -- $MODIFIED_CONFIGS
fi

# Confirm ARTIFACTS_DIR is the only write location
echo "Verification: no committed file changes from spike"
git -C /workspace/markethawk status --short | grep -v "^??" || echo "Working tree clean — ✅"
```

- [ ] **Step 5: Post recommendation as GitHub comment on #675**

```bash
REC_CONTENT=$(cat "$ARTIFACTS_DIR/cbm-recommendation.md")
TOKEN_TABLE_MD=$(cat "$ARTIFACTS_DIR/token-counts.md")

gh issue comment 675 --repo omniscient/markethawk --body "$(cat << COMMENT
## codebase-memory-mcp Evaluation — Spike Complete (#675)

**Recommendation: $TIER**

$TIER_REASON

### Evidence

$REC_CONTENT

### Token Savings

$TOKEN_TABLE_MD

### Full artifacts

All raw outputs (\`cbm-queries.md\`, context files, index log) are in:
\`$ARTIFACTS_DIR\` (ephemeral — available only during this container run).

### Future plan

Next steps: https://github.com/omniscient/markethawk/issues/674

---
*Posted by MarketHawk Dark Factory spike run*
COMMENT
)"
echo "GitHub comment posted on #675"
```

- [ ] **Step 6: Write status file for the workflow runner**

```bash
TASK_COUNT=8
STEP_COUNT=48

cat > "/home/factory/.archon/workspaces/omniscient/markethawk/artifacts/runs/136aea948276fdf09496e2910039e9bd/spike-status.md" << STATUS
STATUS: SPIKE_COMPLETE
TIER: $TIER
RECOMMENDATION: $TIER_REASON
ARTIFACTS_DIR: $ARTIFACTS_DIR
GITHUB_COMMENT: posted to #675
STATUS
echo "Status file written"
```

- [ ] **Step 7: Handle no-go or advisory-only — qualitative assessment of non-quantified scenarios**

```bash
# Per spec: conformance and review scenarios assessed qualitatively (not in bench comparison)
cat >> "$ARTIFACTS_DIR/cbm-recommendation.md" << QUAL

## Qualitative Assessment — Conformance and Review Scenarios

These scenarios were not in the bench comparison (per spec) and are assessed qualitatively
from query evaluation results:

- **Conformance:** If the tool reliably surfaces changed symbols and their callers,
  it could reduce the context needed for the conformance gate. Quality depends on
  call-path tracing reliability (see Task 3, Step 8 output).

- **Review (code-review gate):** The code-review gate reads diffs, not graph context.
  CBM would primarily help the review gate by providing blast-radius context for
  changed functions. Gate-backed tier is prerequisite.

- **Plan generation:** Plan context is dominated by ARCHITECTURE.md, CLAUDE.md, and
  the spec. CBM could replace broad file reads with targeted symbol lookups. Likely
  scenario for the context-pack backend tier.
QUAL
```

- [ ] **Step 8: Final cleanup — confirm no uncommitted factory file changes**

```bash
# Final safety check per spec requirement 8
UNCOMMITTED=$(git -C /workspace/markethawk status --short 2>/dev/null | grep -v "^??" || true)
if [ -n "$UNCOMMITTED" ]; then
  echo "WARNING: uncommitted changes detected:"
  echo "$UNCOMMITTED"
  # Revert anything that isn't $ARTIFACTS_DIR
  git -C /workspace/markethawk checkout -- . 2>/dev/null || true
fi

echo ""
echo "=== SPIKE COMPLETE ==="
echo "Recommendation: $TIER"
echo "GitHub comment posted: https://github.com/omniscient/markethawk/issues/675"
echo "All artifacts in: $ARTIFACTS_DIR"
echo "Future plan: https://github.com/omniscient/markethawk/issues/674"
```
