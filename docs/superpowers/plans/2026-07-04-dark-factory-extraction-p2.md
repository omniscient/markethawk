# Dark Factory Extraction — P2 Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Author MarketHawk's `.factory/` adapter (adapter.yaml + hooks + bench corpus + memory scoping), validate it in MarketHawk CI against the extracted factory image, run the replay bench suite through the **extracted** factory against MarketHawk and compare pass^k with an in-repo baseline (the P2 exit gate), and stage — but do not execute — the P3 cutover artifacts.

**Architecture:** Third phase of the extraction spec (`docs/superpowers/specs/2026-07-03-dark-factory-extraction-design.md`). P0+P1 delivered `omniscient/dark-factory` (checkout `C:\git\dark-factory`, image `ghcr.io/omniscient/dark-factory:latest`) with an instance-identity layer, a `.factory/adapter.yaml` loader whose `DEFAULTS` are MarketHawk's constants, and a hook runner (`scripts/hooks.sh`) with built-in defaults. P2 makes MarketHawk an **explicitly configured** target: every mirrored adapter value equals the corresponding default, so behavior is bit-identical — the adapter's job is to stop MarketHawk depending on those defaults surviving future factory releases. The in-repo factory keeps running throughout: it has no `run_hook`/adapter code, so `.factory/` is invisible to it; only the extracted image reads it. The strangler's two-sided state during P2 (spelled out so no task "fixes" it): archon workflows/commands and the workflow-invoked gate scripts still come from the **target clone** (`.archon/workflows/`, `dark-factory/scripts/` — the `TARGET-PATH` markers); the extracted machinery replaces only scheduler/entrypoint/baked-gates until P3.

**Tech Stack:** YAML + bash hooks (MarketHawk `.factory/`), bash + Python 3/pytest (dark-factory repo changes), GitHub Actions + GHCR (adapter CI validation), Docker + archon (bench parity runs).

## Global Constraints

- **NO CUTOVER.** MarketHawk's in-repo factory remains the production factory. Nothing in this plan modifies MarketHawk's `dark-factory/`, `.archon/workflows|commands`, or `.claude/skills/refinement/` (one exception: `dark-factory/bench/baseline.md` gets real baseline numbers in Task 7 — data, not machinery). Nothing repoints the scheduler image.
- **Mirror invariant:** every value in MarketHawk's `adapter.yaml` that mirrors `adapter_defaults.DEFAULTS` must be **equal** to the default (asserted in Task 1 Step 4 and continuously by Task 6 CI). A deliberate divergence is out of scope for P2 — file a ticket instead.
- **Additive-hooks invariant:** `.factory/hooks/*` must be no-behavior-change: the in-repo factory never discovers them; the extracted factory must behave identically on the green path with or without them. The only intentional difference is *where* the check code lives. Task 5 (factory-side smoke-gate check-only contract) must merge **before** any extracted-image run against a MarketHawk clone containing hooks (Task 7), otherwise a red main would bypass the sentinel/regression-ticket machinery.
- **`token_optimization` in adapter.yaml is declarative-only in P2.** No factory code reads the adapter's `token_optimization` key yet — `budget_enforce.py`/`diff_rank.py`/commands read `.claude/skills/refinement/config.yaml` from the clone, which stays present and authoritative until P3. Wiring config resolution to the adapter is a dark-factory follow-up ticket (Task 8 Step 4) that must land before P3 deletes the config from MarketHawk. Do not attempt that wiring in this plan.
- Two repos are touched: MarketHawk (Tasks 1–4, 6, plus baseline.md data in 7) and dark-factory (Tasks 5, 7-records, 8). MarketHawk changes ship as **one PR** (branch `feat/factory-adapter-p2`) so the adapter, hooks, and CI validation land atomically; dark-factory changes ship as their own PR(s) with CI green + image republished.
- Windows checkout hazards (P1 lesson, `docs/parity-p1.md` §2): hook files need the exec bit via `git update-index --chmod=+x` and LF endings enforced via `.gitattributes` before the first commit that adds them.
- Bench budget: one full suite ≈ 30 archon runs ≈ $7.50–$12 (or equivalent Max-plan window). P2 needs **two** full suites (baseline + extracted) plus shakedown singles: plan for ≈ $20–$28. Use `BENCH_TOKEN_BUDGET=12.00` per suite. Run outside US market pre-open hours so the production scheduler's Max window isn't starved.
- Bench runs use **throwaway clones only** — `run_suite.sh` does destructive `git checkout <sha>` on its target; never point it at `C:\git\trading\MarketHawk` or `C:\git\dark-factory` working copies.
- Archon `when:` clauses must never gain parentheses; `check_workflow_dag.py` must pass after any workflow edit (Task 8 does not edit workflows, but the reviewer should re-check if scope creeps).

## File Structure (end state of P2)

```
MarketHawk/
  .factory/
    README.md               # NEW — provenance + pointer to the adapter contract
    adapter.yaml            # NEW — explicit mirror of factory defaults + token_optimization values
    hooks/
      smoke-gate            # NEW — check-only: tsc + backend import (exit 0 green / 1 red)
      validate              # NEW — tsc --noEmit (deconflict-grade validation)
      preview-up            # NEW — port of the workflow preview-up node (not yet wired; see Task 3)
      preview-down          # NEW — per-issue preview teardown
    bench/
      suite.json            # NEW — copy of dark-factory/bench/suite.json (target-owned corpus)
  .github/workflows/ci.yml  # MODIFIED — + adapter-validate job
  .gitattributes            # MODIFIED — LF for .factory/hooks/*
  dark-factory/bench/baseline.md  # MODIFIED (Task 7) — real in-repo pass^k numbers

dark-factory/  (C:\git\dark-factory)
  scripts/hooks.sh          # MODIFIED — smoke-gate target hook = check-only, wrapped by _smoke_on_red/green
  entrypoint.sh             # MODIFIED — deconflict validate prefers .factory/hooks/validate
  bench/run_suite.sh        # MODIFIED — BENCH_TARGET_DIR override + shakedown fixes
  Dockerfile                # MODIFIED — COPY bench/ /opt/dark-factory/bench/
  README.md                 # MODIFIED — hook-contract table updates
  tests/test_hooks.sh       # MODIFIED — smoke-gate check-only cases
  docs/parity-p2.md         # NEW (Task 7) — P2 exit-gate evidence record
  deploy/instances/markethawk/instance.env   # NEW (Task 8) — cutover instance config minus secrets
  docs/cutover-markethawk.md                 # NEW (Task 8) — P3 runbook (prepare-only)
  .archon/memory/dark-factory-ops.md         # NEW (Task 4) — factory-scoped memory seed (copy)
```

---

## Task 1: MarketHawk `.factory/adapter.yaml` — explicit mirror of the defaults

**Files:**
- Create: `.factory/adapter.yaml`, `.factory/README.md`
- Modify: `.gitattributes`

**Interfaces:**
- Produces: an adapter that `factory_core.adapter.load()` validates and deep-merges to a result **equal to the defaults** for every mirrored key. Consumed by every extracted-image run against a MarketHawk clone at current main, and by Task 6's CI job.

- [ ] **Step 1: Branch** — `git -C <markethawk-worktree> checkout -b feat/factory-adapter-p2 origin/main` (use a fresh worktree off origin/main; the primary checkout may be on another branch).

- [ ] **Step 2: Write `.factory/adapter.yaml`** — values transcribed from `dark-factory/scripts/factory_core/adapter_defaults.py` (components/safety/memory_routing/deconflict) and from MarketHawk's live `.claude/skills/refinement/config.yaml` `token_optimization:` block (verified identical to dark-factory `config/config.yaml` on 2026-07-04):

```yaml
# MarketHawk Dark Factory adapter (.factory/adapter.yaml)
#
# Explicit mirror of the extracted factory's built-in defaults
# (dark-factory: scripts/factory_core/adapter_defaults.py). Every mirrored value
# EQUALS the default — behavior is bit-identical; the point is that MarketHawk
# no longer depends on those defaults surviving future factory releases.
# Deep-merged over defaults at dispatch; validated by MarketHawk CI (adapter-validate)
# and at factory dispatch (fail-closed with a ticket comment on invalid).
#
# token_optimization is DECLARATIVE-ONLY until the factory re-points config
# resolution from .claude/skills/refinement/config.yaml to this adapter
# (dark-factory follow-up; must land before P3 deletes the config from this repo).
# Until then .claude/skills/refinement/config.yaml remains authoritative — keep
# the two in sync when calibrating budgets.
schema_version: 1

components:
  backend:
    - "Scan Execution Flow"
    - "Backend Module Map"
    - "Error Tracking System"
    - "Celery Task Architecture"
    - "Test Architecture"
  frontend:
    - "Frontend Architecture"
    - "Backend Module Map"
    - "Error Tracking System"
  dark-factory:
    - "Service Topology"
    - "Celery Task Architecture"
    - "Metrics and Observability"
  infrastructure:
    - "Service Topology"
    - "IB Gateway Integration"
    - "Live Scanner"
    - "Celery Task Architecture"
    - "Catch Up Feature (Universe Aggregate Backfill)"
    - "Metrics and Observability"

safety:
  sensitive_keywords: "trading|ibkr|live order|notional|authentication|authorization|authn|authz|jwt|oauth|rbac|/auth"
  hard_exclude_paths:
    - "dark-factory/"
    - ".archon/"
    - "scheduler.sh"
    - "factory_core/"
    - "app/services/trading"
    - "app/tasks/trading.py"
    - "app/core/auth"
    - "app/routers/auth"
  dispatch_ceiling_keywords: "migration|migrate|performance|perf|architectur|refactor"
  critical_diff_paths:
    - "^alembic/versions/"
    - "^backend/app/routers/auth"
    - "^backend/app/core/auth"
    - "app/services/trading"
    - "app/tasks/trading\\.py"
    - "^dark-factory/"
  migration_seed_auth_patterns:
    - "^alembic/versions/"
    - "^dark-factory/seed/"
    - "seed.*\\.sql$"
    - "^backend/app/routers/auth\\.py$"
  main_red_allowed_paths:
    - "backend/"
    - "frontend/"
    - "alembic/"
    - "dark-factory/smoke_gate.sh"

memory_routing:
  "backend/app/*": ".archon/memory/backend-patterns.md"
  "frontend/src/*": ".archon/memory/frontend-patterns.md"

deconflict:
  models_init: "backend/app/models/__init__.py"
  migrations_dir: "alembic/versions/"

token_optimization:
  enabled: true
  enforce_budgets: true       # NO env override — rollback is a git commit (see dark-factory README two-tier rollback)
  default_budget_tokens: 30000
  budgets:
    refine: 30000
    plan: 30000
    implement: 30000
    conformance: 22000        # provisional from T5 smoke run; recalibrate per runbook
    code-review: 22000        # provisional from T5 smoke run; recalibrate per runbook
  enforce:
    refine: true              # T3b enforcement live — #733 via #731 scorecard
    plan: true                # T3b enforcement live — #733 via #731 scorecard
    implement: false
    conformance: true         # T6 enforcement live
    code-review: true         # T6 enforcement live
  issue_context:
    reserve_tokens: 2000
  architecture:
    enabled: true
    mode: slice
    max_tokens: 5000
    min_tokens: 2500
  memory:
    enabled: true
    mode: top_k
    max_entries: 8
    max_tokens: 1500
    min_tokens: 750
  comments:
    enabled: true
    digest_after_factory_marker: true
    max_tokens: 2000
    min_tokens: 1000
  diff:
    enabled: true
    max_review_tokens: 6000
    min_review_tokens: 3000
  escalation:
    cheap_model_first: true
    opus_only_for:
      - security
      - trading
      - auth
      - high_blast_radius
      - material_conformance_uncertainty
```

Before committing, re-diff the `token_optimization` block against the live `.claude/skills/refinement/config.yaml` on origin/main — if calibration changed since 2026-07-04, the adapter takes the **live** values (the config file is authoritative until the P3 re-point).

- [ ] **Step 3: Write `.factory/README.md`** (short):

```markdown
# .factory/ — Dark Factory adapter for MarketHawk

Target-repo adapter read by the extracted Dark Factory
([omniscient/dark-factory](https://github.com/omniscient/dark-factory)) from its
fresh clone of this repo (clone-read: changes take effect on the next run, no
image rebuild). The in-repo factory (`dark-factory/`, pre-extraction) ignores
this directory entirely.

- `adapter.yaml` — data: components map, safety patterns, memory routing,
  deconflict paths, token-optimization budgets. Explicit mirror of the factory
  defaults; see the header comment for the sync rule.
- `hooks/` — behavior: `smoke-gate` (check-only gate), `validate`,
  `preview-up`/`preview-down`. Env contract and gate semantics:
  dark-factory `README.md` → "Adapter contract".
- `bench/suite.json` — replay-benchmark corpus for this target.

Spec: `docs/superpowers/specs/2026-07-03-dark-factory-extraction-design.md`.
Cutover status: P2 (parity) — in-repo factory still authoritative.
```

- [ ] **Step 4: Enforce LF + validate the adapter against the extracted image**

Append to `.gitattributes`:

```
.factory/hooks/* text eol=lf
```

Then validate (the mirror-equality assertion is the acceptance test for this task):

```bash
docker pull ghcr.io/omniscient/dark-factory:latest
docker run --rm -v "<markethawk-worktree>:/target:ro" \
  -e PYTHONPATH=/opt/dark-factory/scripts \
  --entrypoint python3 ghcr.io/omniscient/dark-factory:latest \
  -m factory_core.adapter --clone-dir /target --validate
# Expected: "adapter OK"

docker run --rm -v "<markethawk-worktree>:/target:ro" \
  --entrypoint python3 ghcr.io/omniscient/dark-factory:latest -c "
import sys; sys.path.insert(0, '/opt/dark-factory/scripts')
from factory_core import adapter, adapter_defaults
merged = adapter.load('/target')
for key in ('components', 'safety', 'memory_routing', 'deconflict'):
    assert merged[key] == adapter_defaults.DEFAULTS[key], f'MIRROR DRIFT in {key}'
print('MIRROR-EQUAL: adapter values == factory defaults')"
# Expected: MIRROR-EQUAL
```

- [ ] **Step 5: Commit** — `git add .factory/ .gitattributes && git commit -m "feat(factory-adapter): explicit .factory/adapter.yaml mirroring extracted-factory defaults (#738)"`

---

## Task 2: Hooks — `smoke-gate` (check-only) and `validate`

**Files:**
- Create: `.factory/hooks/smoke-gate`, `.factory/hooks/validate`

**Interfaces:**
- Consumes: hook env contract (`CLONE_DIR`, `ARTIFACTS_DIR`, `ISSUE_NUM`, `FACTORY_REPO_SLUG`) from dark-factory `scripts/hooks.sh`.
- Produces: `smoke-gate` — **check-only**: exit 0 = main green, non-zero = red; the factory wraps it with its sentinel/regression-ticket machinery (Task 5 establishes that contract factory-side). `validate` — exit 0/non-zero type-check result; entrypoint's deconflict flow calls it as a gate (Task 5).

- [ ] **Step 1: Write `.factory/hooks/smoke-gate`** — verbatim port of the checks in dark-factory `smoke_gate.sh::_smoke_check_main` (tsc + backend import graph with throwaway env; see #190 preview-env-contract and #415 REDIS_PASSWORD history):

```bash
#!/usr/bin/env bash
# MarketHawk smoke-gate hook — CHECK ONLY.
# Exit 0 = origin/main is green; non-zero = red.
# Red/green STATE handling (sentinel file, regression ticket, clean-halt exit 0)
# stays factory-side: dark-factory scripts/hooks.sh wraps this check with
# _smoke_on_red/_smoke_on_green. Do not add state handling here.
# Ported from dark-factory smoke_gate.sh _smoke_check_main.
set -uo pipefail

echo "[smoke-gate hook] Checking frontend TypeScript (tsc)..."
if ! (cd "${CLONE_DIR}/frontend" \
      && rm -f tsconfig.app.tsbuildinfo \
      && npx tsc -p tsconfig.app.json --noEmit 2>&1); then
  echo "[smoke-gate hook] tsc FAILED — main is red"
  exit 1
fi

echo "[smoke-gate hook] Checking backend Python import graph..."
# Throwaway values: the gate verifies the import graph compiles, NOT that config
# is real. Settings() instantiates at import time and requires DATABASE_URL /
# POLYGON_API_KEY / JWT_SECRET_KEY (>=32 chars) / REDIS_PASSWORD (>=16 chars).
if ! (cd "${CLONE_DIR}/backend" \
      && DATABASE_URL="postgresql://smoke:smoke@localhost:5432/smoke" \
         POLYGON_API_KEY="smoke-gate-only-not-a-real-key" \
         JWT_SECRET_KEY="smoke-gate-only-not-secret-0123456789abcdef" \
         REDIS_PASSWORD="smoke-gate-only-not-a-real-redis-password" \
         python -c "import app.main" 2>&1); then
  echo "[smoke-gate hook] python import FAILED — main is red"
  exit 1
fi

echo "[smoke-gate hook] main is green"
exit 0
```

- [ ] **Step 2: Write `.factory/hooks/validate`** — port of entrypoint.sh's inline deconflict tsc check (the P1 ledger's "entrypoint inline tsc validate deliberately not rewired; move to MH .factory/hooks/validate in P2" item):

```bash
#!/usr/bin/env bash
# MarketHawk validate hook — lightweight post-merge validation (no running DB).
# Called as a gate by the factory's deconflict flow; non-zero exit escalates
# the ticket to Blocked. Ported from entrypoint.sh's inline deconflict tsc check.
set -uo pipefail

echo "[validate hook] TypeScript type check..."
cd "${CLONE_DIR}/frontend" && npx tsc --noEmit
```

- [ ] **Step 3: Set exec bits (Windows) and verify**

```bash
git add .factory/hooks/smoke-gate .factory/hooks/validate
git update-index --chmod=+x .factory/hooks/smoke-gate .factory/hooks/validate
git ls-files -s .factory/hooks/   # expect mode 100755 on both
bash -n .factory/hooks/smoke-gate && bash -n .factory/hooks/validate && echo SYNTAX-OK
```

- [ ] **Step 4: Live-run both hooks inside the factory image against the worktree** (the image has node + python; backend deps install is part of the check's cd'd venv-less context — mirror how entrypoint prepares the clone: `pip install -r backend/requirements.txt` and `npm ci --prefix frontend` first):

```bash
docker run --rm -v "<markethawk-worktree>:/clone" -e CLONE_DIR=/clone \
  --entrypoint bash ghcr.io/omniscient/dark-factory:latest -c "
    pip install -q -r /clone/backend/requirements.txt 2>&1 | tail -2
    npm ci --prefix /clone/frontend --silent
    bash /clone/.factory/hooks/smoke-gate && bash /clone/.factory/hooks/validate"
# Expected: '[smoke-gate hook] main is green' then tsc exits 0
```

- [ ] **Step 5: Commit** — `git commit -m "feat(factory-adapter): smoke-gate (check-only) + validate hooks (#738)"`

---

## Task 3: Hooks — `preview-up` / `preview-down` (authored, not yet wired)

The preview machinery currently lives inline in the workflow's `preview-up` node and the `close-preview` node (MarketHawk `.archon/workflows/archon-dark-factory.yaml` — target-authoritative until P3). These hooks port that target knowledge into the adapter. **They are not called by any factory version yet** — the workflow nodes remain authoritative. Rewiring the nodes to `run_hook preview-up/preview-down` is a dark-factory follow-up filed in Task 8 Step 4, deliberately not done in P2 (the node is entangled with the E2BIG artifacts-file contract and `preview_env.sh` single-writer discipline; changing it is not needed for the parity gate, which runs `BENCH_MODE=stub`).

**Files:**
- Create: `.factory/hooks/preview-up`, `.factory/hooks/preview-down`

**Interfaces:**
- Consumes: hook env contract + `NEEDS_PREVIEW`/`PREVIEW_SKIP_REASON_IN` (preview-up inputs replacing archon node interpolations).
- Produces: `preview-up` writes `${ARTIFACTS_DIR}/preview_env.sh` (same single-writer contract as the node); `preview-down` tears down `mh-preview-${ISSUE_NUM}` and verifies no stale containers.

- [ ] **Step 1: Write `.factory/hooks/preview-down`** — port of the `close-preview` node's teardown + verification:

```bash
#!/usr/bin/env bash
# MarketHawk preview-down hook — tear down the per-issue preview stack.
# Port of the workflow close-preview node. NOT YET WIRED: the workflow node
# remains authoritative until the factory rewires it to run_hook (post-P2).
set -uo pipefail
: "${ISSUE_NUM:?preview-down requires ISSUE_NUM}"

echo "Tearing down mh-preview-${ISSUE_NUM}..."
docker compose -p "mh-preview-${ISSUE_NUM}" down -v 2>/dev/null || echo "No preview stack found"

STALE=$(docker ps -a --filter "label=com.docker.compose.project=mh-preview-${ISSUE_NUM}" \
  --format '{{.Names}}' 2>/dev/null || true)
if [ -n "$STALE" ]; then
  echo "ERROR: Stale preview containers remain after teardown:" >&2
  echo "$STALE" >&2
  exit 1
fi
echo "preview-down: teardown verified — no mh-preview-${ISSUE_NUM} containers remain"
```

- [ ] **Step 2: Write `.factory/hooks/preview-up`** — port of the workflow `preview-up` node body (the node between `- id: preview-up` and `- id: preview-up-resolve` in `.archon/workflows/archon-dark-factory.yaml`), copied **verbatim** except for these five substitutions (a code move, not new content — same convention as the P0+P1 plan's verbatim-copy entries):

| Node construct | Hook replacement |
|---|---|
| `ISSUE=$(jq -r '.resolved_number' "$ARTIFACTS_DIR/issue.json")` | `ISSUE="${ISSUE_NUM:?preview-up requires ISSUE_NUM}"` |
| `NEEDS_PREVIEW=$classify-preview.output.needs_preview` | `NEEDS_PREVIEW="${NEEDS_PREVIEW:-true}"` (default true = fail-safe direction) |
| `SKIP_REASON="$classify-preview.output.reason"` | `SKIP_REASON="${PREVIEW_SKIP_REASON_IN:-}"` |
| leading comment | header: check-only provenance note + "NOT YET WIRED" (mirror preview-down's) |
| trailing node-output `echo` lines (`PREVIEW_SKIPPED=…` stdout for archon) | keep — harmless on stdout, and identical output eases the eventual node→hook diff |

Everything else — `write_preview_env()`, `preview_fail()`, `BENCH_MODE=stub` short-circuit, slot allocation, remote-BuildKit build (`buildx --builder remote`), one-shot migrate, `docker inspect` health — is copied unchanged. The compose file path stays `dark-factory/docker-compose.preview.yml` relative to `$CLONE_DIR` (a `TARGET-PATH` that moves only at P3).

- [ ] **Step 3: Exec bits + syntax + teardown live-check**

```bash
git add .factory/hooks/preview-up .factory/hooks/preview-down
git update-index --chmod=+x .factory/hooks/preview-up .factory/hooks/preview-down
bash -n .factory/hooks/preview-up && bash -n .factory/hooks/preview-down && echo SYNTAX-OK
# Live check on the no-op path only (no stack running):
ISSUE_NUM=9999 bash .factory/hooks/preview-down
# Expected: "No preview stack found" then "teardown verified"
```

(Do not live-test preview-up in P2 — it would build a full preview stack; the port is protected by `bash -n`, review, and the fact that it is unwired.)

- [ ] **Step 4: Commit** — `git commit -m "feat(factory-adapter): preview-up/preview-down hooks (ported, unwired) (#738)"`

---

## Task 4: `.factory/bench/suite.json` + memory scoping

**Files:**
- Create: MarketHawk `.factory/bench/suite.json`
- Create: dark-factory `.archon/memory/dark-factory-ops.md` (seed copy)

**Decisions (recorded here; do not re-litigate during implementation):**
1. **Bench corpus: COPY, not pointer.** The spec places the per-target replay corpus in the adapter (`.factory/bench/suite.json`). Copy MarketHawk's `dark-factory/bench/suite.json` byte-identical. The extracted runner selects it via `--tasks` (Task 5 enables that). The in-repo copy keeps serving the in-repo baseline until P3 deletes it; dark-factory's own `bench/suite.json` (also a copy of the same MarketHawk tasks) becomes the no-adapter fallback and gets replaced by a dogfood corpus at P4.
2. **Memory stays physically at `.archon/memory/` through P2.** Relocating to `.factory/memory/` requires the factory's `MEMORY_DIR` generalization (`memory_maintain.py` hardcodes `Path(".archon/memory")` — the deferred "T2 MEMORY_DIR" item from the P1 final review) and would desync the two factories mid-strangler (the in-repo factory writes `.archon/memory/` on every run). The adapter's `memory_routing` (Task 1) therefore pins the current `.archon/memory/...` paths explicitly. Relocation is a P3 step, executed together with MEMORY_DIR generalization — listed in the Task 8 cutover runbook.
3. **Factory-scoped memory is COPIED (not moved) to the dark-factory repo now.** Per the memory contract's scoping matrix (`docs/agents/dark-factory-memory-contract.md` §4): `dark-factory-ops.md` entries about factory machinery (scheduler, gates, token-opt, workflow) are factory-scoped and belong with the factory; entries referencing MarketHawk app paths are target-scoped and stay. MarketHawk's copies remain untouched until P3 (the in-repo factory still reads them).

- [ ] **Step 1: Copy the corpus**

```bash
mkdir -p .factory/bench
git show origin/main:dark-factory/bench/suite.json > .factory/bench/suite.json
diff <(git show origin/main:dark-factory/bench/suite.json) .factory/bench/suite.json && echo IDENTICAL
git add .factory/bench/suite.json
```

Note: `oracle_tests` paths inside suite.json (`dark-factory/tests/...`, `backend/tests/...`) are paths **inside the MarketHawk tree at the pinned pre_pr_sha** — they stay as-is; do not "fix" them to `.factory/` paths.

- [ ] **Step 2: Seed the dark-factory repo's own memory** — in `C:\git\dark-factory`, create `.archon/memory/dark-factory-ops.md` containing the factory-scoped entries copied from MarketHawk `origin/main:.archon/memory/dark-factory-ops.md`. Triage rule per entry: keep if its `path:`/content references factory machinery (`scheduler.sh`, `dark-factory/scripts`, gates, workflow, token-opt); leave behind if it references MarketHawk app code. Preserve entry lines verbatim including `<!-- source:… date:… -->` tokens. Add a header line: `<!-- Seeded from omniscient/markethawk .archon/memory/dark-factory-ops.md at P2 (2026-07-XX); MarketHawk copies remain until P3. -->`

- [ ] **Step 3: Commit both repos** — MarketHawk: `git commit -m "feat(factory-adapter): target-owned bench corpus at .factory/bench/suite.json (#738)"`. dark-factory: `git add .archon/memory/ && git commit -m "chore: seed factory-scoped memory from MarketHawk dark-factory-ops (P2)"` (ships with the Task 5 PR).

---

## Task 5: dark-factory — hook-contract refinements + bench runner enablement

All changes in `C:\git\dark-factory`, branch `p2/hook-contract`, one PR, CI green, image republished. **Must merge before Task 7.**

**Files:**
- Modify: `scripts/hooks.sh`, `entrypoint.sh`, `bench/run_suite.sh`, `Dockerfile`, `README.md`
- Test: `tests/test_hooks.sh` (extend)

**Interfaces:**
- Produces: (a) smoke-gate target hooks are **check-only** — `run_hook` keeps `_smoke_on_red`/`_smoke_on_green` state machinery factory-side regardless of hook presence; (b) entrypoint deconflict validation prefers `.factory/hooks/validate`, falling back to the existing inline tsc (parity for hook-less targets); (c) `run_suite.sh` accepts `BENCH_TARGET_DIR` so the suite can run against a target clone from the baked image; (d) `bench/` is baked into the image.

- [ ] **Step 1: Failing tests first** — extend `tests/test_hooks.sh` (follow its existing tmp-dir + PATH-stub conventions; stub `gh` on PATH so `_smoke_on_red` cannot hit the network). Caution: `SMOKE_STATE_DIR` is bound from `SCHEDULER_STATE_DIR` when `hooks.sh` sources `smoke_gate.sh` — export `SCHEDULER_STATE_DIR` *before* the `source scripts/hooks.sh` line (or re-source in a subshell for these cases):

```bash
# 4) target smoke-gate hook is CHECK-ONLY: green path clears sentinel
#    (SCHEDULER_STATE_DIR exported before sourcing hooks.sh — see note above)
export SCHEDULER_STATE_DIR="$TMP/state"; mkdir -p "$SCHEDULER_STATE_DIR"
touch "$SCHEDULER_STATE_DIR/main-is-red"
printf '#!/bin/sh\nexit 0\n' > "$TMP/.factory/hooks/smoke-gate"
chmod +x "$TMP/.factory/hooks/smoke-gate"
run_hook --gate smoke-gate
[ ! -f "$SCHEDULER_STATE_DIR/main-is-red" ] || { echo "FAIL: green hook must clear sentinel"; exit 1; }
# 5) red hook routes through _smoke_on_red: sentinel written, clean halt (exit 0)
printf '#!/bin/sh\nexit 1\n' > "$TMP/.factory/hooks/smoke-gate"
( run_hook --gate smoke-gate )   # subshell: _smoke_on_red exits 0
RC=$?
[ "$RC" = "0" ] || { echo "FAIL: red smoke-gate must clean-halt with exit 0"; exit 1; }
[ -f "$SCHEDULER_STATE_DIR/main-is-red" ] || { echo "FAIL: red hook must write sentinel"; exit 1; }
```

Run `bash tests/test_hooks.sh` → FAIL (current code runs the hook raw and propagates exit 1).

- [ ] **Step 2: Implement in `scripts/hooks.sh`** — replace the `if [ -x "$hook" ]` branch body:

```bash
  if [ -x "$hook" ]; then
    if [ "$name" = "smoke-gate" ]; then
      # Target hook supplies the CHECK only (exit 0 green / non-zero red).
      # Red/green STATE machinery (sentinel, regression ticket, clean-halt
      # exit 0) stays factory-side — identical semantics to the built-in gate.
      if CLONE_DIR="$CLONE_DIR" ARTIFACTS_DIR="${ARTIFACTS_DIR:-}" ISSUE_NUM="${ISSUE_NUM:-}" \
           FACTORY_REPO_SLUG="${FACTORY_REPO_SLUG:-}" "$hook" "$@"; then
        _smoke_on_green
        rc=0
      else
        _smoke_on_red   # exits 0 (clean halt); unreachable after
      fi
    else
      CLONE_DIR="$CLONE_DIR" ARTIFACTS_DIR="${ARTIFACTS_DIR:-}" ISSUE_NUM="${ISSUE_NUM:-}" \
        FACTORY_REPO_SLUG="${FACTORY_REPO_SLUG:-}" "$hook" "$@" || rc=$?
    fi
  else
```

- [ ] **Step 3: Entrypoint deconflict validate → hook with inline fallback** — in `entrypoint.sh`, replace the deconflict TypeScript-validation block (`if ! (cd "$CLONE_DIR/frontend" && npx tsc --noEmit 2>&1); then …`) with:

```bash
  # --- Validate: target hook if present, else inline tsc (parity fallback) ---
  DECONFLICT_VALIDATION="PASS"
  if [ -x "$CLONE_DIR/.factory/hooks/validate" ]; then
    echo "[deconflict] Running .factory/hooks/validate..."
    if ! run_hook --gate validate; then
      DECONFLICT_VALIDATION="FAIL"
      echo "[deconflict] validate hook failed — escalating to Blocked."
      _conflict_escalate "Validation failed after merge (.factory/hooks/validate). Run the hook locally to see errors."
      exit 0
    fi
  else
    echo "[deconflict] Running TypeScript validation..."
    if ! (cd "$CLONE_DIR/frontend" && npx tsc --noEmit 2>&1); then
      DECONFLICT_VALIDATION="FAIL"
      echo "[deconflict] TypeScript validation failed — escalating to Blocked."
      _conflict_escalate "TypeScript type errors after merge. Run 'cd frontend && npx tsc --noEmit' to see them."
      exit 0
    fi
  fi
```

(`hooks.sh` is already sourced for the deconflict intent by the smoke-gate section; verify the source line executes before this block — it does, same intent list.)

- [ ] **Step 4: Bench runner enablement** — `bench/run_suite.sh` line 27: `REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"` → `REPO_ROOT="${BENCH_TARGET_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"` with a comment: `# BENCH_TARGET_DIR: run the suite against a target clone (extracted-factory parity runs)`. `Dockerfile`: add `COPY bench/ /opt/dark-factory/bench/` next to the existing `COPY scripts/`. `README.md`: update the hooks table — smoke-gate row becomes "check-only: exit 0 green / non-zero red; factory keeps sentinel + regression-ticket handling", validate row's default becomes "no-op (deconflict flow falls back to inline tsc)"; add a `Bench parity` subsection documenting `BENCH_TARGET_DIR` + `--tasks`.

- [ ] **Step 5: Full suite + ship** — `PYTHONPATH=scripts python -m pytest tests/ -q` all pass; `bash tests/test_hooks.sh` PASS; `bash tests/test_smoke_gate.sh` PASS (built-in path unchanged). Include the Task 4 Step 2 memory-seed commit. PR → CI green → merge → confirm the publish run pushes a fresh `ghcr.io/omniscient/dark-factory:latest` and `docker run --rm --entrypoint ls ghcr.io/omniscient/dark-factory:latest /opt/dark-factory/bench` shows `run_suite.sh suite.json`.

---

## Task 6: MarketHawk CI — adapter validation job

**Files:**
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `factory_core.adapter --validate` from the published image. Catches: schema breakage, YAML typos, mirror drift (via the equality assertion), missing exec bits, hook syntax errors — on every MarketHawk PR, cheaply (one image pull, no build).

- [ ] **Step 1: One-time prerequisite (manual, controller/Frank):** grant the `dark-factory` GHCR package Actions access to the `markethawk` repo — GitHub → Packages → `dark-factory` → Package settings → *Manage Actions access* → add repository `omniscient/markethawk` (read). Without this, `GITHUB_TOKEN` cannot pull the private image. Record completion in the PR description.

- [ ] **Step 2: Add the job to `ci.yml`** (sibling of `factory-tests`):

```yaml
  adapter-validate:
    name: Factory adapter validation
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - name: Schema-validate .factory/adapter.yaml against the extracted factory
        run: |
          docker run --rm -v "$PWD:/target:ro" \
            -e PYTHONPATH=/opt/dark-factory/scripts \
            --entrypoint python3 ghcr.io/omniscient/dark-factory:latest \
            -m factory_core.adapter --clone-dir /target --validate
      - name: Assert mirrored values equal factory defaults
        run: |
          docker run --rm -v "$PWD:/target:ro" \
            --entrypoint python3 ghcr.io/omniscient/dark-factory:latest -c "
          import sys; sys.path.insert(0, '/opt/dark-factory/scripts')
          from factory_core import adapter, adapter_defaults
          merged = adapter.load('/target')
          for key in ('components', 'safety', 'memory_routing', 'deconflict'):
              assert merged[key] == adapter_defaults.DEFAULTS[key], f'MIRROR DRIFT in {key}'
          print('MIRROR-EQUAL')"
      - name: Hooks are executable and parse
        run: |
          for h in .factory/hooks/*; do
            [ -x "$h" ] || { echo "not executable: $h" >&2; exit 1; }
            bash -n "$h"
          done
```

Note on the mirror assertion: it is intentionally strict for P2 (Global Constraint "mirror invariant"). When a deliberate divergence is ever introduced post-P2, this step is *edited in the same PR* to exempt the diverged key — that edit is the review signal.

- [ ] **Step 3: Open the MarketHawk PR** (`feat/factory-adapter-p2`, Tasks 1–4+6, title `feat: MarketHawk .factory/ adapter for the extracted Dark Factory`, body references #738 with `--body-file`). Verify all required checks plus the new `adapter-validate` job pass. Do **not** add `adapter-validate` to the required-checks list yet — propose it to the controller after it has run green on a few PRs (branch-protection edits need admin).

- [ ] **Step 4: Merge** once green and reviewed.

---

## Task 7: Bench parity run — the P2 exit gate

**Files:**
- Modify: MarketHawk `dark-factory/bench/baseline.md` (real numbers — data-only change, separate small PR)
- Create: dark-factory `docs/parity-p2.md` (evidence record)

**Context the implementer must hold:** the committed baseline is a **stub** — `pass^k` has never been measured (baseline.md: "no runs executed yet"). P2 therefore establishes the in-repo baseline first, then runs the extracted image, then compares. Expect the first runs to flush out bench-harness bugs; that is in scope. Known suspects to check during shakedown (fix in MarketHawk's `dark-factory/bench/run_suite.sh` and mirror the same fix to the extracted repo's `bench/run_suite.sh` so both runs use identical harness logic):
- `REPO_ROOT` resolves to `<repo>/dark-factory`, not the repo root, when the script lives at `dark-factory/bench/` (`dirname $0/..`) — `git -C` tolerates it, but the `bash` oracle path join (`bash "$REPO_ROOT/$t"` with `t=dark-factory/tests/...`) double-prefixes, and pytest/jest oracle cwd assumptions may not hold.
- Oracle deps: backend pytest oracles need `pip install -r backend/requirements.txt` in the run env; the jest oracle needs `npm ci` in `frontend/`.
- `archon workflow cost --last --json` may be unavailable → cost falls back to 0 (acceptable; note it).
- The `ALL_RESULTS_RAW` env aggregation across the `while` subshell boundary (bash pipelines run loop bodies in subshells — `ALL_RESULTS` may be empty at aggregation time).

Also hold: bench replays check out **historical pre_pr_sha** commits, which predate `.factory/` — so replay runs exercise the defaults path, not the adapter. Adapter-present parity is covered by (a) Task 1/6's mirror-equality assertion (adapter == defaults ⇒ same inputs) and (b) Step 5's dispatch smoke at current main. State this in `parity-p2.md` so the evidence is honest.

- [ ] **Step 1: Throwaway clone + dry runs**

```bash
git clone https://github.com/omniscient/markethawk.git /c/git/bench-mh
# In-repo harness dry run:
docker run --rm --entrypoint bash -v "C:/git/bench-mh:/workspace/markethawk" \
  ghcr.io/omniscient/markethawk-dark-factory:latest \
  -c "cd /workspace/markethawk && bash dark-factory/bench/run_suite.sh --dry-run"
# Extracted harness dry run (baked bench from Task 5):
docker run --rm --entrypoint bash -v "C:/git/bench-mh:/workspace/markethawk" \
  ghcr.io/omniscient/dark-factory:latest \
  -c "cd /workspace/markethawk && BENCH_TARGET_DIR=/workspace/markethawk \
      bash /opt/dark-factory/bench/run_suite.sh --tasks /workspace/markethawk/.factory/bench/suite.json --dry-run"
```

Expected: both print the same 10-task plan. Fix path/manifest issues before spending tokens.

- [ ] **Step 2: Shakedown single** — run one S task once through each harness (`--issues 224 --n 1`, with `GH_TOKEN` + `CLAUDE_CODE_OAUTH_TOKEN` + `BENCH_MODE=stub` in env). Debug the run loop and oracle execution until both produce a scored result JSON. Commit harness fixes (MarketHawk bench PR + dark-factory bench PR, mirrored).

- [ ] **Step 3: In-repo baseline (full)** — `--n 3` full suite via `ghcr.io/omniscient/markethawk-dark-factory:latest`, `BENCH_TOKEN_BUDGET=12.00`, `BENCH_MODE=stub`. Copy the results JSON out of the container mount; update MarketHawk `dark-factory/bench/baseline.md` pass^k tables with the real per-bucket and per-task numbers (small data-only PR).

- [ ] **Step 4: Extracted run (full)** — same suite, same throwaway clone (re-`git fetch && git checkout main` first), via `ghcr.io/omniscient/dark-factory:latest` with `BENCH_TARGET_DIR` + `--tasks /workspace/markethawk/.factory/bench/suite.json`, same budget/mode.

- [ ] **Step 5: Dispatch smoke through the full extracted entrypoint path** (covers what bench bypasses: scheduler-style invocation, identity env, clone, **hook discovery**):

```bash
docker run --rm -e GH_TOKEN -e CLAUDE_CODE_OAUTH_TOKEN \
  ghcr.io/omniscient/dark-factory:latest "Recheck main"
```

Expected in the log, in order: fresh clone of `omniscient/markethawk`; `[smoke-gate hook]` lines (proof the **target hook** ran, not the built-in `[smoke_gate]` prefix); `[recheck] main is green — sentinel cleared; done.` Capture the log excerpt for the evidence record. If main is red at the time, defer until green (do not gate P2 on an unrelated red).

- [ ] **Step 6: Compare and verdict.** Gate criteria (pin these in `parity-p2.md` before looking at the numbers):
  1. **Per size bucket:** extracted aggregate passes `c_ext ≥ c_base − 1` (one flipped run of noise tolerance at n=3), and extracted `pass^k` within that implied bound.
  2. **Hard fail:** any task with `c=0` extracted but `c=n` baseline → investigate before any verdict (root-cause per the systematic-debugging skill; a harness artifact is not a parity failure, a machinery divergence is).
  3. Step 5's dispatch smoke shows the target hook executed and the run clean-halted correctly.
  4. If the **baseline itself** is pathological (≥ half the tasks 0/3), the harness — not parity — is the problem: fix and re-run before comparing.

- [ ] **Step 7: Record + report.** Write dark-factory `docs/parity-p2.md` (same structure as `docs/parity-p1.md`: commands, raw outputs, per-gate verdict table, image digests for both images). Commit to dark-factory main via PR. Post a completion summary to MarketHawk issue **#738**: baseline vs extracted pass^k table, dispatch-smoke evidence, gate verdict, and that P3 (cutover) is unblocked/blocked accordingly.

---

## Task 8: P3 prepare-only artifacts (DO NOT CUT OVER)

All in `C:\git\dark-factory`, branch `p2/cutover-prep`, one PR.

**Files:**
- Create: `deploy/instances/markethawk/instance.env`, `docs/cutover-markethawk.md`
- Modify: `deploy/.gitignore` handling if needed (see Step 1), `README.md` (one pointer line)

- [ ] **Step 1: `deploy/instances/markethawk/instance.env`** — the MarketHawk instance config, secrets blank. Check `.gitignore` first: if `deploy/instance.env` is ignored by a broad pattern, ensure `deploy/instances/**` is exempted (`!deploy/instances/**/instance.env`) — this file is committable because it contains no secrets.

```bash
# MarketHawk production instance — Dark Factory cutover (P3)
# PREPARED AT P2; DO NOT DEPLOY until docs/cutover-markethawk.md preconditions hold.
# Secrets are filled at cutover time on the host, never committed.

GH_TOKEN=                      # fill at cutover: needs repo+project+workflow scope
CLAUDE_CODE_OAUTH_TOKEN=       # fill at cutover: Max-plan OAuth token

FACTORY_OWNER=omniscient
FACTORY_REPO=markethawk
FACTORY_PROJECT_ID=PVT_kwHOAAFds84BWh4w
FACTORY_PROJECT_NUMBER=1
FACTORY_STATUS_FIELD=PVTSSF_lAHOAAFds84BWh4wzhR1VaA
FACTORY_STATUS_READY=61e4505c
FACTORY_STATUS_IN_PROGRESS=47fc9ee4
FACTORY_STATUS_IN_REVIEW=df73e18b
FACTORY_STATUS_BLOCKED=93d87b2f
FACTORY_STATUS_DONE=98236657
FACTORY_STATUS_BACKLOG=f75ad846
FACTORY_STATUS_REFINED=0c79ebe5
FACTORY_PRODUCT_NAME=MarketHawk
FACTORY_CLONE_DIR=/workspace/markethawk
FACTORY_RUN_PREFIX=markethawk-dark-factory-run-

FACTORY_WIP_LIMIT=1
POLL_INTERVAL=60
# IMAGE_TAG=latest             # pin a digest here at cutover for deterministic rollback
```

- [ ] **Step 2: `docs/cutover-markethawk.md`** — the P3 runbook, sections:
  1. **Preconditions:** `docs/parity-p2.md` verdict = PASS; MarketHawk board quiet (no In progress/In review items); main green; controller go-ahead on #738.
  2. **Cutover:** stop the in-repo scheduler (`docker compose stop backlog-scheduler` in the MarketHawk stack — do NOT `down` the app stack); copy `deploy/instances/markethawk/instance.env` to the live deploy dir, fill secrets, pin `IMAGE_TAG` to the parity-verified digest from parity-p2.md; `PROJECT_DIR=<markethawk-checkout> docker compose -f deploy/docker-compose.yml up -d`; run one "Recheck main" dispatch smoke; then observe 2–3 real tickets end-to-end.
  3. **Rollback (trivial until cleanup):** `docker compose -f deploy/docker-compose.yml down`; restart the in-repo scheduler. Nothing in MarketHawk changed, so rollback = flipping which scheduler runs.
  4. **P3 cleanup (only after observation):** delete from MarketHawk `dark-factory/`, `.archon/workflows/`, `.archon/commands/`, `.claude/skills/refinement/`; drop the `docker-dark-factory` job/required check from MarketHawk CI (it moved to the factory repo); re-point the workflow/command `TARGET-PATH` references factory-side first. **Blockers to clear before cleanup:** (a) token_optimization config re-point (Step 4 ticket) — deleting `.claude/skills/refinement/config.yaml` before it lands silently reverts budgets to baked defaults; (b) memory relocation `.archon/memory/` → `.factory/memory/` together with MEMORY_DIR generalization; (c) scheduler `Depends on:` / board-machinery spot-checks per the triage-label vocabulary.
  5. **Explicit banner at top:** `Status: PREPARED (P2). Not executed. Executing this document IS P3.`

- [ ] **Step 3: README pointer** — add one line to dark-factory `README.md` deploy section: `Per-instance configs live under deploy/instances/ (markethawk: see docs/cutover-markethawk.md).`

- [ ] **Step 4: File the two follow-up tickets on omniscient/dark-factory** (use `--body-file`): (a) "Config resolution: read token_optimization (and target-tunable blocks) from .factory/adapter.yaml before .claude/skills/refinement/config.yaml — P3 blocker"; (b) "Rewire workflow preview-up/close-preview nodes to run_hook preview-up/preview-down with inline body as built-in default — post-P3". Cross-reference both from #738.

- [ ] **Step 5: PR, CI green, merge.** Post a P2-complete summary comment on #738 linking parity-p2.md, the MarketHawk adapter PR, and both follow-up tickets.

---

## Self-review notes

- **Spec coverage:** spec P2 = "Author MarketHawk's `.factory/` adapter + run the replay bench suite through the extracted factory and compare pass^k with the in-repo baseline" → Tasks 1–4 (adapter: yaml, hooks, bench corpus, memory scoping), Task 5 (factory-side contract the hooks need), Task 7 (bench parity = exit gate). Prompt extras: CI adapter validation (Task 6), P3 prepare-only artifacts (Task 8). The "adapter contract" section's `bench/suite.json` and `memory/` entries are both resolved with recorded decisions (Task 4). `factory init` remains out of scope (P2 configures an existing target; provisioning is untested spec-optional).
- **Placeholders:** two verbatim-copy instructions (Task 3 preview-up node port with a 5-row substitution table; Task 4 memory-seed triage) are code/content moves from named sources — same convention the P0+P1 plan used and declared. `2026-07-XX` in the Task 4 seed header is filled with the actual date at implementation. No other TBDs.
- **Type/name consistency:** hook names (`smoke-gate`, `validate`, `preview-up`, `preview-down`) match `hooks.sh` discovery and the README table; env contract (`CLONE_DIR`, `ARTIFACTS_DIR`, `ISSUE_NUM`, `FACTORY_REPO_SLUG`) matches P1 Task 10; adapter keys match `_KNOWN_TOP`/`_MAP_KEYS` in `adapter.py`; `BENCH_TARGET_DIR`, `--tasks`, `BENCH_MODE`, `BENCH_TOKEN_BUDGET` consistent across Tasks 5 and 7; image names distinguish in-repo (`markethawk-dark-factory`) vs extracted (`dark-factory`) everywhere.
- **Honesty checks baked in:** bench replays at pre_pr_sha exercise the defaults path, not the adapter — compensated by mirror-equality + dispatch smoke, and stated in the evidence record (Task 7). `token_optimization` is declared inert in P2 in three places (constraint, adapter comment, P3-blocker ticket) so nobody assumes budget overrides work via the adapter yet.
