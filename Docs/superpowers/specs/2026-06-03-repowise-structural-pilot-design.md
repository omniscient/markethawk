# Repowise Structural Pilot

> Tracking issue: [#177](https://github.com/omniscient/markethawk/issues/177)

**Component:** `scripts/`, `.repowise/`, `.gitignore`, `docs/`

## Goal

Evaluate [repowise](https://github.com/repowise-dev/repowise) as a potential replacement or augmentation for the existing `codeindex` tooling. Stand it up as a **disposable, fully-offline pilot** to produce real evaluation outputs that inform a replace-vs-augment-vs-drop decision.

Repowise is largely a superset of codeindex: same dependency graph + symbol lookup + blast radius + hotspots, plus git behavioral signals, 25-biomarker code-health scoring, dead-code detection, and an MCP server. The LLM/embedder layers (wiki, ADR mining, semantic search) are explicitly out of scope for the pilot.

## Decisions (from brainstorming)

- **Pilot/evaluate first** — no pipeline rewiring during the pilot; decide replace-vs-augment afterward with real outputs in hand.
- **Forego the LLM/embedder layers** — fully offline, zero cost, zero external exposure for a proprietary trading codebase. This parks wiki, mined-ADR prose, semantic search, and `get_answer`.
- **Footprint A** — host venv + a `scripts/repowise.sh` launcher mirroring the existing `scripts/codeindex.sh` precedent. No Docker container changes.
- **MCP in `.claude/settings.local.json` only** — untracked, interactive-session-only wiring. Not committed to the repo, not wired into the dark-factory baked image.

## Scope

### In scope (deterministic, no-LLM)

- Dependency graph analysis
- Git behavioral signals: hotspots, ownership, co-change, bus factor
- 25-biomarker code-health scoring
- Dead-code detection
- No-LLM MCP tools: `get_overview`, `get_context`, `get_risk`, `get_health`, `get_dead_code`, `get_symbol`
- CLI commands and local dashboard
- `docs/repowise-pilot-eval.md` — structured evaluation findings document committed to the repo

### Out of scope (phase-2 if pilot says "adopt")

- LLM/embedder layers, wiki, mined ADRs, semantic search, `get_answer`
- Rewiring the dark-factory Archon workflow to use repowise
- Replacing the `codeindex-blast` pre-commit hook
- Hosted Repowise GitHub App / SaaS
- Wiring repowise MCP into the dark-factory baked image

## Components

### 1. `scripts/repowise.sh` (new)

Launcher script mirroring `scripts/codeindex.sh`:
- Locates the host venv at `~/.venvs/repowise` (or `REPOWISE_VENV` env override)
- Prints install instructions if repowise is not found
- Runs `repowise analyze .` to regenerate indexes before serving
- Launches the local dashboard (`repowise serve` or `repowise dashboard`)

### 2. `.repowise/config.yaml` (new)

Curated offline configuration:
- `llm.enabled: false` — disable LLM/embedder layers entirely
- Git signals enabled: hotspots, ownership, co-change, bus factor
- Code-health analysis enabled (all 25 biomarkers)
- Dead-code detection enabled
- Output directory: `.repowise/index/` (gitignored)
- Exclude paths: `node_modules/`, `__pycache__/`, `.git/`, `frontend/dist/`, `frontend/node_modules/`

### 3. `.gitignore` update

Add entries to ignore generated repowise index artifacts:

```
# Repowise pilot (generated index — do not commit)
.repowise/index/
```

The `.repowise/config.yaml` itself IS committed; only the generated output directory is gitignored.

### 4. MCP wiring (`.claude/settings.local.json` — NOT committed)

`settings.local.json` is already in `.gitignore`. The pilot documents the MCP wiring pattern in `docs/repowise-pilot-eval.md` so developers can reproduce it:

```json
{
  "mcpServers": {
    "repowise": {
      "command": "/absolute/path/to/repowise-venv/bin/repowise",
      "args": ["mcp"],
      "env": {}
    }
  }
}
```

### 5. `docs/repowise-pilot-eval.md` (new)

Structured evaluation document. Contains:
- Setup instructions (venv install + MCP wiring)
- Results from each of the three evaluation scenarios
- A filled-in decision rubric with the verdict
- Next steps based on the verdict

## Evaluation Plan

Three scenarios, all documented in `docs/repowise-pilot-eval.md`:

### Scenario 1: Code-health / defect signal (primary)

Run `repowise health` and inspect the ~15 worst-scoring files. Assess face validity against:
- Known-complex files: `services/scanner.py`, `tasks/sync.py`, `providers/massive.py`
- Git churn/bugfix history for those files (`git log --oneline --follow`)
- Gut-check: do the flagged files feel genuinely risky?

Document: top-15 list, per-file health score, verdict on face validity.

### Scenario 2: AI-agent efficiency (MCP)

Run ~4 representative agent tasks via three paths:
1. Repowise MCP tools (`get_overview`, `get_context`, `get_risk`, `get_symbol`)
2. Codeindex MCP tools (`lookup_symbol`, `get_impact`)
3. Baseline grep

Sample tasks:
- "Where is `calculate_day_metrics` defined and what calls it?"
- "What is the blast radius of changing `ScannerEvent`?"
- "Which files are hotspots by churn and complexity?"
- "What's the health score of `services/scanner.py`?"

Document: tool-call count per path per task, context quality (qualitative), verdict.

### Scenario 3: PR-time review signal

Run `repowise risk` and `repowise health` on a recent `feat/*` branch (e.g. `feat/issue-159-*`). Compare output against:
- The factory's "Blast radius" PR section for that PR
- `archon-smart-pr-review` output

Document: signal overlap, unique signals, verdict.

## Decision Rubric

| Verdict | Criteria |
|---------|----------|
| **Replace codeindex** | Strong health face validity + MCP tools match-or-beat `lookup_symbol`/`get_impact` + runs reliably |
| **Adopt alongside** | Health/git/PR signals valuable, but MCP lookup no better than codeindex |
| **Drop** | Noisy / low-face-validity / Windows-flaky / not worth maintaining a second toolchain |

## Files Changed

| File | Change |
|------|--------|
| `scripts/repowise.sh` | New launcher script |
| `.repowise/config.yaml` | New offline pilot config |
| `.gitignore` | Add `.repowise/index/` to ignore list |
| `docs/repowise-pilot-eval.md` | New evaluation findings document |
