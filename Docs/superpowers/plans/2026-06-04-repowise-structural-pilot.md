# Repowise Structural Pilot — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up repowise as a disposable, fully-offline pilot alongside the existing `codeindex` tooling, run three evaluation scenarios, and commit a structured findings document that informs a replace-vs-augment-vs-drop decision.

**Architecture:** Host venv install + `scripts/repowise.sh` launcher (mirrors `scripts/codeindex.sh`) + `.repowise/config.yaml` (offline, no-LLM) + `.gitignore` update + `docs/repowise-pilot-eval.md` findings report. MCP wiring is documented but lives in the untracked `.claude/settings.local.json`.

**Tech Stack:** Python (repowise pip package), Bash (launcher script), YAML (config), Markdown (evaluation doc)

---

## File Structure

| File | Responsibility |
|------|---------------|
| `scripts/repowise.sh` | Launcher — checks install, regenerates index, serves dashboard |
| `.repowise/config.yaml` | Offline pilot config — no LLM/embedder layers |
| `.gitignore` | Ignores `.repowise/index/` generated artifacts |
| `docs/repowise-pilot-eval.md` | Structured evaluation findings committed to repo |

---

### Task 1: Install repowise and create offline config

Install repowise in a dedicated host venv and write the offline config that disables LLM/embedder layers.

**Files:**
- Create: `.repowise/config.yaml`

- [ ] **Step 1: Install repowise in a dedicated venv**

```bash
# Create a dedicated venv (not shared with backend requirements)
python3 -m venv ~/.venvs/repowise
~/.venvs/repowise/bin/pip install --upgrade pip

# Install repowise from PyPI (or from GitHub if the PyPI package name differs)
~/.venvs/repowise/bin/pip install repowise

# Verify install — if this fails, check https://github.com/repowise-dev/repowise
# for the correct install command and use that before continuing
~/.venvs/repowise/bin/repowise --version
```

Expected output: `repowise x.y.z`. If the command returns an error or the wrong package, run:

```bash
~/.venvs/repowise/bin/pip uninstall -y repowise
# Then follow the install instructions from the GitHub README
```

- [ ] **Step 2: Probe the CLI to discover the actual config schema**

```bash
cd /workspace/markethawk
~/.venvs/repowise/bin/repowise --help
~/.venvs/repowise/bin/repowise config --help 2>/dev/null || true
~/.venvs/repowise/bin/repowise init --dry-run 2>/dev/null || true
```

Read the output and note:
- The config file name/location (likely `.repowise/config.yaml` or `repowise.yaml`)
- The key to disable LLM/embedder layers
- The subcommand to regenerate the index (likely `analyze` but may differ)
- The subcommand to launch the dashboard (likely `serve` or `dashboard`)
- The default port for the dashboard

If the actual config schema differs from what Step 3 assumes, adjust Step 3 accordingly before writing the file.

- [ ] **Step 3: Write `.repowise/config.yaml`**

```yaml
# .repowise/config.yaml
# Offline pilot config — no LLM/embedder layers.
# Key names are based on the repowise README schema; adjust if Step 2 reveals different keys.

llm:
  enabled: false          # disable wiki, ADR mining, semantic search, get_answer

analysis:
  git: true               # hotspots, ownership, co-change, bus factor
  health: true            # 25-biomarker code-health scoring
  dead_code: true         # dead-code detection

output:
  directory: .repowise/index

exclude:
  - node_modules/
  - __pycache__/
  - .git/
  - frontend/dist/
  - frontend/node_modules/
  - .venv/
  - venv/
```

After writing, validate the config is accepted:

```bash
~/.venvs/repowise/bin/repowise validate-config 2>/dev/null \
  || ~/.venvs/repowise/bin/repowise config validate 2>/dev/null \
  || echo "No config validation command — proceed to Step 4 to validate via analyze"
```

- [ ] **Step 4: Run `repowise analyze` to confirm the config works**

First confirm the analyze subcommand name (from Step 2 output):

```bash
~/.venvs/repowise/bin/repowise analyze --help 2>/dev/null \
  || echo "subcommand may differ — check --help output"
```

Then run the analysis:

```bash
cd /workspace/markethawk
~/.venvs/repowise/bin/repowise analyze . 2>&1
if [ $? -ne 0 ]; then
  echo "ERROR: repowise analyze failed. Check the error above."
  echo "Common causes: wrong config key names, missing dependencies, wrong subcommand name."
  echo "Fix .repowise/config.yaml or the install, then re-run this step."
  exit 1
fi
```

Confirm the index landed in the expected location:

```bash
ls .repowise/
```

Expected: an `index/` directory (or similar) containing generated files.

- [ ] **Step 5: Commit the config**

```bash
git add .repowise/config.yaml
git commit -m "feat(#177): add .repowise/config.yaml — offline pilot, no LLM layers

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 2: Create the launcher script and update .gitignore

Create `scripts/repowise.sh` mirroring `scripts/codeindex.sh`, and add the generated index directory to `.gitignore`.

**Files:**
- Create: `scripts/repowise.sh`
- Modify: `.gitignore`

- [ ] **Step 1: Write `scripts/repowise.sh`**

The launcher probes at runtime for the dashboard subcommand (tries `serve`, `dashboard`, `ui` in order) so the committed script is not broken if the discovered name differs.

```bash
#!/usr/bin/env bash
# Launch repowise local dashboard
# Install first: python3 -m venv ~/.venvs/repowise && ~/.venvs/repowise/bin/pip install repowise
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Allow override via env (useful if venv lives elsewhere)
REPOWISE_VENV="${REPOWISE_VENV:-$HOME/.venvs/repowise}"
REPOWISE="${REPOWISE_VENV}/bin/repowise"

if [ ! -f "$REPOWISE" ]; then
  echo "ERROR: repowise not found at $REPOWISE" >&2
  echo "Install:" >&2
  echo "  python3 -m venv ~/.venvs/repowise" >&2
  echo "  ~/.venvs/repowise/bin/pip install repowise" >&2
  echo "Or set REPOWISE_VENV to the path of an existing venv that has repowise." >&2
  exit 1
fi

echo "Regenerating repowise index..."
"$REPOWISE" analyze .

# Probe for the dashboard subcommand (varies across repowise versions)
SERVE_CMD=""
for candidate in serve dashboard ui; do
  if "$REPOWISE" "$candidate" --help &>/dev/null 2>&1; then
    SERVE_CMD="$candidate"
    break
  fi
done
if [ -z "$SERVE_CMD" ]; then
  echo "ERROR: could not find dashboard subcommand (tried: serve, dashboard, ui)" >&2
  echo "Run: $REPOWISE --help  to find the correct subcommand and update this script." >&2
  exit 1
fi

echo ""
echo "Launching repowise dashboard via '$SERVE_CMD' (Ctrl+C to stop)"
"$REPOWISE" "$SERVE_CMD"
```

Make executable:
```bash
chmod +x scripts/repowise.sh
```

Verify the script is syntactically valid and the error path works:
```bash
bash -n scripts/repowise.sh && echo "Syntax OK"
REPOWISE_VENV=/nonexistent bash scripts/repowise.sh 2>&1 | grep "ERROR:"
```

Expected second line output: `ERROR: repowise not found at /nonexistent/bin/repowise`

- [ ] **Step 2: Update `.gitignore`**

Append the repowise index entry to `.gitignore`:

```bash
printf '\n# Repowise pilot (generated index — do not commit)\n.repowise/index/\n' >> .gitignore
```

Verify the entry was added:
```bash
grep -n "repowise" .gitignore
```

Expected: two lines — the comment and `.repowise/index/`.

- [ ] **Step 3: Commit launcher and gitignore**

```bash
git add scripts/repowise.sh .gitignore
git commit -m "feat(#177): add scripts/repowise.sh launcher and .gitignore entry

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Create the evaluation document scaffold

Create `docs/repowise-pilot-eval.md` with the full structure — setup instructions, scenario tables, and the decision rubric. The findings cells will be filled in during Tasks 4–6.

**Files:**
- Create: `docs/repowise-pilot-eval.md`

- [ ] **Step 1: Write `docs/repowise-pilot-eval.md`**

Write the following content verbatim to `docs/repowise-pilot-eval.md`. Where the content includes shell code, it is presented as indented text below — write it as fenced code blocks in the actual file.

The file has six top-level sections:

**Section 1 — Header and tracking**

    # Repowise Structural Pilot — Evaluation Findings

    > Tracking issue: [#177](https://github.com/omniscient/markethawk/issues/177)
    > Date: 2026-06-04
    > Branch: refine/issue-177-pilot--evaluate-repowise-structural-laye

**Section 2 — Setup instructions**

    ## Setup

    ### Install repowise

    (fenced bash block)
    python3 -m venv ~/.venvs/repowise
    ~/.venvs/repowise/bin/pip install repowise
    (end block)

    ### Run the launcher

    (fenced bash block)
    bash scripts/repowise.sh        # regenerates index + opens dashboard
    (end block)

    ### Wire MCP (interactive sessions — NOT committed)

    Add to `.claude/settings.local.json` (already gitignored). **Merge** with existing entries —
    do not overwrite the file. The JSON below shows only the repowise entry to add:

    (fenced json block)
    {
      "mcpServers": {
        "repowise": {
          "command": "/absolute/path/to/.venvs/repowise/bin/repowise",
          "args": ["mcp"],
          "env": {}
        }
      }
    }
    (end block)

    Replace `/absolute/path/to/` with the absolute path: run `echo ~/.venvs/repowise/bin/repowise`
    to get the correct path.

**Section 3 — Scenario 1**

    ## Scenario 1: Code-health / defect signal

    **Command:** `repowise health`

    **Top-15 worst files (by health score):**

    | Rank | File | Health Score | Notes |
    |------|------|-------------|-------|
    | 1 | | | |
    | 2 | | | |
    | 3 | | | |
    | 4 | | | |
    | 5 | | | |
    | 6 | | | |
    | 7 | | | |
    | 8 | | | |
    | 9 | | | |
    | 10 | | | |
    | 11 | | | |
    | 12 | | | |
    | 13 | | | |
    | 14 | | | |
    | 15 | | | |

    **Face validity check — known-complex files in top-15?**

    - `services/scanner.py`: rank __, score __
    - `tasks/sync.py`: rank __, score __
    - `providers/massive.py`: rank __, score __

    **Git churn cross-check (top-5 churned files by commit count):**

    (fenced bash block)
    git log --oneline --name-only -- backend/app/ | grep "\.py$" | sort | uniq -c | sort -rn | head -5
    (end block)

    Output:
    (fenced block)
    (fill in)
    (end block)

    Overlap with repowise top-15: __/5

    **Verdict (Scenario 1):** [ ] Strong face validity  [ ] Partial  [ ] Noisy/poor

    Notes:

**Section 4 — Scenario 2**

    ## Scenario 2: AI-agent efficiency (MCP)

    Tasks run in a Claude Code session with both repowise MCP and codeindex MCP wired.
    "Tool calls" = number of MCP tool invocations needed to fully answer the question.

    | Task | Repowise MCP calls | Codeindex MCP calls | Grep calls | Repowise quality | Codeindex quality |
    |------|--------------------|---------------------|------------|-----------------|-------------------|
    | Where is `calculate_day_metrics` defined and what calls it? | | | | | |
    | Blast radius of changing `ScannerEvent`? | | | | | |
    | Which files are hotspots by churn + complexity? | | | | | |
    | Health score of `services/scanner.py`? | | | | | |

    **Notes:**

    **Verdict (Scenario 2):** [ ] Repowise MCP matches/beats codeindex  [ ] Comparable  [ ] Worse

**Section 5 — Scenario 3**

    ## Scenario 3: PR-time review signal

    **Branch tested:** (filled in during Task 6)

    **Repowise output (summarized):**
    (fenced block)
    (fill in)
    (end block)

    **Factory "Blast radius" section from that PR:**
    (fenced block)
    (fill in)
    (end block)

    **Signal overlap:** __% of repowise flags matched factory/archon output

    **Unique repowise signals (not caught by factory/archon):**
    -

    **Signals missed by repowise (caught by factory/archon):**
    -

    **Verdict (Scenario 3):** [ ] Adds meaningful signal  [ ] Redundant  [ ] Noisier

**Section 6 — Decision + cleanup**

    ## Decision

    | Criterion | Verdict |
    |-----------|---------|
    | Code-health face validity | |
    | MCP tool efficiency vs codeindex | |
    | PR-time review signal | |
    | Install / setup friction | |

    **Overall verdict:** [ ] Replace codeindex  [ ] Adopt alongside  [ ] Drop

    **Rationale:**

    **Recommended next steps:**

    ---

    ## Cleanup (if verdict is Drop)

    (fenced bash block)
    rm -rf ~/.venvs/repowise
    rm -rf .repowise/
    rm scripts/repowise.sh
    # Remove the .repowise/index/ line from .gitignore
    # Remove this file
    (end block)

- [ ] **Step 2: Verify the file was written correctly**

```bash
wc -l docs/repowise-pilot-eval.md
grep -c "Scenario" docs/repowise-pilot-eval.md
grep -c "Verdict" docs/repowise-pilot-eval.md
```

Expected: 3 scenario sections, 4 verdict lines.

- [ ] **Step 3: Commit the evaluation scaffold**

```bash
git add docs/repowise-pilot-eval.md
git commit -m "feat(#177): add repowise evaluation findings document scaffold

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 4: Run Scenario 1 — code-health signal

Run `repowise health`, capture the top-15 worst files, cross-check with git churn, fill in `docs/repowise-pilot-eval.md`.

**Files:**
- Modify: `docs/repowise-pilot-eval.md`

- [ ] **Step 1: Run `repowise health`**

```bash
cd /workspace/markethawk
~/.venvs/repowise/bin/repowise health 2>&1 | head -80
```

If the `health` subcommand name differs (check `repowise --help`), use the correct name. Capture the top-15 worst files and their health scores from the output.

- [ ] **Step 2: Check known-complex files specifically**

```bash
# Try per-file health if the subcommand supports it
~/.venvs/repowise/bin/repowise health backend/app/services/scanner.py 2>/dev/null \
  || ~/.venvs/repowise/bin/repowise health --file backend/app/services/scanner.py 2>/dev/null \
  || echo "Per-file health not supported — use rank from Step 1 output"
```

- [ ] **Step 3: Run git churn cross-check**

```bash
git log --oneline --name-only -- backend/app/ | grep "\.py$" | sort | uniq -c | sort -rn | head -10
```

Note which high-churn files appear in the repowise top-15.

- [ ] **Step 4: Fill in Scenario 1 section of `docs/repowise-pilot-eval.md`**

Edit the file to fill in:
- The top-15 table (file paths, health scores)
- The known-complex file ranks and scores
- The git churn output
- The overlap count
- The Verdict checkbox and Notes

- [ ] **Step 5: Commit Scenario 1 findings**

```bash
git add docs/repowise-pilot-eval.md
git commit -m "feat(#177): scenario 1 — code-health signal findings

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 5: Run Scenario 2 — MCP efficiency

Wire the repowise MCP server into `.claude/settings.local.json` (merge, do not overwrite) and run four representative tasks in-session via each path.

**Files:**
- Modify: `docs/repowise-pilot-eval.md`
- Modify: `.claude/settings.local.json` (untracked — do not commit)

- [ ] **Step 1: Probe the MCP subcommand name before writing settings**

The correct MCP subcommand must be known before writing `settings.local.json`. Probe first:

```bash
REPOWISE_BIN="$(realpath ~/.venvs/repowise/bin/repowise)"

# Probe for MCP subcommand
MCP_CMD=""
for candidate in mcp serve-mcp mcp-server; do
  if "$REPOWISE_BIN" "$candidate" --help &>/dev/null 2>&1; then
    MCP_CMD="$candidate"
    break
  fi
done
if [ -z "$MCP_CMD" ]; then
  echo "ERROR: could not find MCP subcommand (tried: mcp, serve-mcp, mcp-server)" >&2
  echo "Run: $REPOWISE_BIN --help  to find the correct subcommand" >&2
  exit 1
fi
echo "MCP subcommand: $MCP_CMD"
echo "Binary: $REPOWISE_BIN"
```

- [ ] **Step 2: Wire the repowise MCP server (read-merge-write — do NOT overwrite)**

Use Python with a quoted heredoc (`<<'PYEOF'`) and env vars to avoid bash expansion inside the Python source. Pass `REPOWISE_BIN` and `MCP_CMD` via the environment:

```bash
REPOWISE_BIN="$REPOWISE_BIN" MCP_CMD="$MCP_CMD" python3 - <<'PYEOF'
import json, os

settings_path = ".claude/settings.local.json"
try:
    with open(settings_path) as f:
        data = json.load(f)
except FileNotFoundError:
    data = {}

data.setdefault("mcpServers", {})
data["mcpServers"]["repowise"] = {
    "command": os.environ["REPOWISE_BIN"],
    "args": [os.environ["MCP_CMD"]],
    "env": {}
}

with open(settings_path, "w") as f:
    json.dump(data, f, indent=2)

print("Merged successfully. MCP servers:", list(data.get("mcpServers", {}).keys()))
PYEOF
```

Verify the repowise entry is present and existing entries were preserved:
```bash
python3 -m json.tool .claude/settings.local.json
```

Expected: `codeindex` entry (if present) and new `repowise` entry both appear.

- [ ] **Step 3: Run four tasks via repowise MCP (in this Claude Code session)**

**Important:** Claude Code reads `settings.local.json` at startup. If this is an autonomous dark factory run, the MCP server will be available immediately since the session started after the file was written. If this is an interactive session that was already running when Step 2 ran, restart Claude Code (`/exit` then reopen) to pick up the new MCP entry before proceeding.

Confirm the MCP tools are available:
```bash
# Smoke test: send a tools/list request to the MCP server
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  | "$REPOWISE_BIN" "$MCP_CMD" 2>&1 | head -20
```

Expected: a JSON response listing tool names (e.g. `get_symbol`, `get_health`, `get_risk`). If the server errors, check the subcommand name and binary path.

For each task below, invoke the relevant MCP tool directly in this Claude Code session, count the calls needed, and note output quality:

**Task A — symbol lookup:**
Use the `get_symbol` MCP tool with argument `calculate_day_metrics`. Record:
- How many tool calls were needed to fully answer "Where is this defined and what calls it?"
- Quality: did the answer include caller locations and definition site?

**Task B — blast radius:**
Use the `get_risk` MCP tool with argument `backend/app/models/scanner.py`. Record:
- How many tool calls were needed to identify all files affected by a change to `ScannerEvent`?
- Quality: completeness vs. `get_impact` from codeindex.

**Task C — hotspot identification:**
Use the `get_overview` or `get_health` MCP tool (no arguments). Record:
- How many tool calls were needed to identify the top churn+complexity hotspots?
- Quality: does the result include both churn signals and complexity scores?

**Task D — file health:**
Use the `get_health` MCP tool with argument `backend/app/services/scanner.py`. Record:
- How many tool calls were needed to retrieve the health score?
- Quality: is the score meaningful and explainable?

- [ ] **Step 4: Run same four tasks via codeindex MCP (in this Claude Code session)**

Verify codeindex is available before running the comparison:

```bash
# Check if codeindex is on PATH
command -v codeindex && codeindex --version \
  || echo "codeindex not on PATH — check if it is registered as an MCP server only"
```

If codeindex is only available as an MCP server (not on PATH), use it via the `lookup_symbol` and `get_impact` MCP tools in session. If it is not wired at all, skip this step and note "codeindex MCP not available in this session — comparison skipped" in the doc.

For each of the four tasks from Step 3, use the codeindex MCP tools:
- Task A: `lookup_symbol("calculate_day_metrics")`
- Task B: `get_impact("backend/app/models/scanner.py")`
- Task C: `get_impact` on multiple files (this is the closest codeindex equivalent to an overview)
- Task D: codeindex does not have a health-score tool — note "N/A" for this task

Record call counts and quality.

- [ ] **Step 5: Run same tasks via grep baseline**

```bash
# Task A — find definition and callers
grep -rn "def calculate_day_metrics" backend/app/ --include="*.py"
grep -rn "calculate_day_metrics" backend/app/ --include="*.py" | grep -v "def "

# Task B — find all ScannerEvent references
grep -rn "ScannerEvent" backend/app/ --include="*.py" | wc -l
grep -rn "ScannerEvent" backend/app/ --include="*.py" | awk -F: '{print $1}' | sort -u

# Task C — hotspots via git (churn proxy)
git log --oneline --name-only -- backend/app/ | grep "\.py$" | sort | uniq -c | sort -rn | head -10

# Task D — no grep equivalent for health score; note "N/A"
```

Count how many grep commands were needed to fully answer each question.

- [ ] **Step 6: Fill in Scenario 2 table in `docs/repowise-pilot-eval.md`**

Fill in the tool-call counts and context quality columns for all four tasks. Enter the Verdict and Notes.

- [ ] **Step 7: Commit Scenario 2 findings**

```bash
git add docs/repowise-pilot-eval.md
git commit -m "feat(#177): scenario 2 — MCP efficiency comparison findings

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 6: Run Scenario 3 — PR-time review signal

Run repowise risk/health on a historical feat branch and compare against the factory's blast-radius and archon-smart-pr-review signals.

**Files:**
- Modify: `docs/repowise-pilot-eval.md`

- [ ] **Step 1: Select and check out the comparison branch**

Try the primary candidate first:

```bash
git fetch origin feat/issue-159-integrate-codeindex-into-the-dark-factor 2>/dev/null \
  && COMPARE_BRANCH="feat/issue-159-integrate-codeindex-into-the-dark-factor" \
  || COMPARE_BRANCH=""
```

If not found, pick the most recent merged feat/* branch:

```bash
if [ -z "$COMPARE_BRANCH" ]; then
  COMPARE_BRANCH=$(git branch -a | grep "remotes/origin/feat/" | sed 's|.*remotes/origin/||' | head -1)
  echo "Falling back to branch: $COMPARE_BRANCH"
  git fetch origin "$COMPARE_BRANCH"
fi

echo "Using branch: $COMPARE_BRANCH"
git checkout "$COMPARE_BRANCH"
```

Save the branch name for use in Steps 2–3.

- [ ] **Step 2: Run repowise risk and health on the branch**

Use a subshell so the branch checkout is automatically unwound even if a step fails:

```bash
(
  # Already on $COMPARE_BRANCH from Step 1
  REPOWISE=~/.venvs/repowise/bin/repowise

  echo "=== repowise risk ==="
  "$REPOWISE" risk 2>&1 || echo "risk subcommand not found — check --help"

  echo ""
  echo "=== repowise health (diff vs main) ==="
  # Try --diff flag first; fall back to full health if not supported
  "$REPOWISE" health --diff main 2>&1 \
    || "$REPOWISE" health 2>&1

  echo ""
  echo "=== changed files ==="
  git diff main...HEAD --name-only | head -20
)
```

Capture the summarized output (key files flagged, risk scores, health signals).

- [ ] **Step 3: Retrieve the factory's blast-radius section for the comparison PR**

Run from the refine branch after returning to it. Use the branch name captured in Step 1:

```bash
git checkout refine/issue-177-pilot--evaluate-repowise-structural-laye

# Look up the merged PR for the comparison branch
PR_NUMBER=$(gh pr list \
  --repo omniscient/markethawk \
  --state merged \
  --head "$COMPARE_BRANCH" \
  --json number \
  --jq '.[0].number' 2>/dev/null)

if [ -n "$PR_NUMBER" ] && [ "$PR_NUMBER" != "null" ]; then
  echo "PR #$PR_NUMBER"
  gh pr view "$PR_NUMBER" --repo omniscient/markethawk --json body --jq '.body' \
    | grep -A 30 -i "blast radius" || echo "No 'Blast radius' section found in PR body"
else
  echo "No merged PR found for $COMPARE_BRANCH — check manually"
fi
```

- [ ] **Step 4: Fill in Scenario 3 section of `docs/repowise-pilot-eval.md`**

Fill in:
- The branch name tested (`$COMPARE_BRANCH`)
- Repowise output from Step 2 (summarized)
- Factory blast-radius section from Step 3
- Signal overlap percentage (qualitative estimate)
- Unique repowise signals not seen in factory output
- Signals factory caught that repowise missed
- Verdict checkbox and notes

- [ ] **Step 5: Fill in the overall Decision section**

Based on the three scenario verdicts, fill in the Decision table and overall verdict:
- If Scenario 1 is "Strong face validity" and Scenario 2 is "Matches/beats codeindex" → consider Replace
- If Scenario 1 is good but Scenario 2 is "Comparable" → consider Adopt alongside
- If any scenario is "Noisy/poor" or "Worse" → lean toward Drop

Fill in:
- The Decision table rows
- The Overall verdict checkbox
- Rationale (2–4 sentences)
- Recommended next steps

- [ ] **Step 6: Commit Scenario 3 and final decision**

```bash
git add docs/repowise-pilot-eval.md
git commit -m "feat(#177): scenario 3 + final decision — repowise pilot evaluation complete

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```
