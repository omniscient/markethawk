# Dark Factory Extraction — P0 Extract + P1 Generalize Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the Dark Factory machinery into `omniscient/dark-factory` (history-preserving) with green CI + published image, then de-hardcode it behind an instance-identity layer and a `.factory/` adapter loader whose defaults are MarketHawk's current values — bit-identical behavior with no adapter present.

**Architecture:** Two sequential phases from the spec (`docs/superpowers/specs/2026-07-03-dark-factory-extraction-design.md`). P0 is pure relocation: `git filter-repo` on a fresh clone, new-repo CI, image publish as `ghcr.io/omniscient/dark-factory`. P1 introduces exactly two indirection layers: (1) **instance identity** — owner/repo/board ids/branding via env with today's literals as defaults; (2) **adapter** — target knowledge (component→section map, safety paths/keywords, memory routing, hooks) read from the target clone's `.factory/`, defaulting to today's MarketHawk constants. MarketHawk's in-repo factory keeps running throughout; nothing in this plan touches the MarketHawk repo except the plan doc itself.

**Tech Stack:** git filter-repo, bash (scheduler/entrypoint), Python 3 stdlib + PyYAML (factory_core, adapter loader), pytest, GitHub Actions, GHCR, Docker.

## Global Constraints

- **Default-parity invariant:** with no `.factory/` adapter and no instance env overrides, every P1 change must be behavior-identical to today (defaults == current MarketHawk literals). Every de-hardcode task ends by running the full existing test suite.
- Work happens in the NEW repo after Task 1 (`~/git/dark-factory` checkout); the MarketHawk repo is read-only reference for this plan.
- New image name: `ghcr.io/omniscient/dark-factory`. Old image (`…/markethawk-dark-factory`) keeps publishing from MarketHawk until P3 cutover — do not touch MarketHawk CI in this plan.
- Python: stdlib + yaml only (no jsonschema dependency — hand-rolled validation, matches factory convention).
- Archon `when:` clauses must never gain parentheses; `check_workflow_dag.py` must pass after any workflow edit.
- Comment markers ("Posted by MarketHawk Dark Factory") are parsed by `comment_digest.py` and shell greps — the marker string must come from ONE source (identity layer) everywhere.
- The `.agents/` mirror tree in MarketHawk is untracked and is NOT extracted.
- Do not create the `factory init` target-provisioning command in this epic (P2 concern) — P1 only makes the machinery *capable* of serving a configured target.

## File Structure (new repo, end state of P1)

```
dark-factory/                      # repo root = today's dark-factory/ contents, promoted
  Dockerfile  entrypoint.sh  scheduler.sh  smoke_gate.sh
  docker-compose.preview.yml  seed/  bench/  evals/  tests/
  scripts/            (token-opt suite, gates, memory machinery)
  scripts/factory_core/
    identity.py       # NEW — single source of owner/repo/board/branding (env + defaults)
    adapter.py        # NEW — .factory/adapter.yaml loader + validation + defaults merge
    adapter_defaults.py  # NEW — MarketHawk's constants as the default adapter
  workflows/archon-dark-factory.yaml     # from .archon/workflows/
  commands/*.md                          # from .archon/commands/
  refinement-skills/                     # from .claude/skills/refinement/
  config/config.yaml                     # from refinement-skills (canonical location)
  deploy/
    docker-compose.yml   # NEW — scheduler + socket-proxy instance stack
    instance.env.example # NEW — TARGET_* identity + tokens template
  docs/                # memory-contract, triage-labels, domain, token-opt runbook
  .github/workflows/ci.yml   publish.yml  # NEW
```

---

## Task 1: Create `omniscient/dark-factory` via history-preserving extraction

**Files:**
- Create: new repo `omniscient/dark-factory` (private), local checkout at `~/git/dark-factory`

**Interfaces:**
- Produces: a pushed `main` whose tree is the extracted path set with full history; all later tasks work in this checkout.

- [ ] **Step 1: Fresh mirror clone of MarketHawk (never filter your working checkout)**

```bash
cd ~/git && git clone https://github.com/omniscient/markethawk.git df-extract --no-tags
cd df-extract && git checkout main && git pull
```

- [ ] **Step 2: Verify filter-repo is available**

Run: `pip install git-filter-repo -q && git filter-repo --version`
Expected: a version hash line.

- [ ] **Step 3: Filter to the factory path set, with renames to the new layout**

```bash
cd ~/git/df-extract
git filter-repo \
  --path dark-factory/ \
  --path .archon/workflows/ \
  --path .archon/commands/ \
  --path .archon/config.yaml \
  --path .claude/skills/refinement/ \
  --path docs/agents/dark-factory-memory-contract.md \
  --path docs/agents/triage-labels.md \
  --path docs/agents/domain.md \
  --path docs/agents/dark-factory-token-optimization.md \
  --path-rename dark-factory/: \
  --path-rename .archon/workflows/:workflows/ \
  --path-rename .archon/commands/:commands/ \
  --path-rename .archon/config.yaml:archon-config.yaml \
  --path-rename .claude/skills/refinement/:refinement-skills/ \
  --path-rename docs/agents/:docs/
```

Note: `docs/agents/issue-tracker.md` intentionally stays in MarketHawk (repo-bound doc).

- [ ] **Step 4: Sanity-check the extracted tree and history**

```bash
ls   # expect: Dockerfile entrypoint.sh scheduler.sh smoke_gate.sh scripts/ tests/ bench/ evals/ workflows/ commands/ refinement-skills/ docs/ seed/ archon-config.yaml docker-compose.preview.yml
git log --oneline -5 -- scheduler.sh   # expect real MarketHawk history (e.g. the #702 orphan-sweep fix)
git log --oneline | wc -l              # expect hundreds of commits, not 1
```

- [ ] **Step 5: Create the GitHub repo and push**

```bash
gh repo create omniscient/dark-factory --private --description "Autonomous development factory — scheduler, refinement pipeline, gates, token optimization. Targets any repo via .factory/ adapters."
git remote add origin https://github.com/omniscient/dark-factory.git
git push -u origin main
mv ~/git/df-extract ~/git/dark-factory
```

- [ ] **Step 6: Commit marker — tag the extraction point**

```bash
cd ~/git/dark-factory && git tag extraction-point && git push origin extraction-point
```

---

## Task 2: Fix intra-repo path references broken by the layout promotion

The `dark-factory/` prefix is gone (contents promoted to root). Every self-reference must drop the prefix. The refinement-skills config also moves to a canonical `config/` home with a compat copy.

**Files:**
- Modify: `Dockerfile`, `entrypoint.sh`, `scheduler.sh`, `tests/*` (paths), `.github/workflows/` (created in Task 3), `bench/run_suite.sh`, `bench/baseline.md`
- Create: `config/` (canonical config home)

**Interfaces:**
- Produces: `pytest tests/` green from repo root with `PYTHONPATH=scripts`; `bash tests/test_scheduler.sh` green.

- [ ] **Step 1: Inventory every self-reference to the old prefix**

Run: `grep -rn "dark-factory/" --include="*.sh" --include="*.py" --include="*.yml" --include="*.yaml" --include="*.md" . | grep -v ".git/" | grep -vE "ghcr|markethawk-dark-factory|image:" > /tmp/prefix-hits.txt && wc -l /tmp/prefix-hits.txt`

Expected: ~60–100 hits. Known classes (from the coupling inventory):
- `Dockerfile` COPY lines: `COPY dark-factory/entrypoint.sh …` → `COPY entrypoint.sh …`; `COPY .claude/skills/refinement/ /opt/refinement-skills/` → `COPY refinement-skills/ /opt/refinement-skills/`; **delete** `COPY docker-compose.yml /opt/dark-factory/docker-compose.yml` (that baked the *MarketHawk app* compose — it is target material; the preview flow reads it from the target clone at `${CLONE_DIR}/docker-compose.yml` already, keep only that path)
- `scheduler.sh:22` `FACTORY_CORE_CLI` default `/workspace/project/dark-factory/scripts/factory_core/cli.py` → `/workspace/project/scripts/factory_core/cli.py`
- `scheduler.sh:31` config path `/workspace/project/.claude/skills/refinement/config.yaml` → `/workspace/project/config/config.yaml` (see Step 3)
- workflow/commands bash: `python3 "${CLONE_DIR}/dark-factory/scripts/…"` → **unchanged** — those run against the TARGET clone, which still has `dark-factory/` until P3. Mark them with `# TARGET-PATH` comments instead of editing (they become adapter-relative in Task 9). Distinguish by context: paths under `${CLONE_DIR}` are target paths; everything else is self.

- [ ] **Step 2: Apply the self-reference fixes (mechanical, per the classes above)**

Work through `/tmp/prefix-hits.txt` line by line; for each hit decide self vs target (rule: `${CLONE_DIR}`-anchored = target, leave + comment; otherwise self, fix). Commit checkpoint after `Dockerfile`, after `scheduler.sh`+`entrypoint.sh`, after `tests/`.

- [ ] **Step 3: Canonicalize config location with compat**

```bash
mkdir config && git mv refinement-skills/config.yaml config/config.yaml
ln -s ../config/config.yaml refinement-skills/config.yaml   # if symlinks undesirable: small loader shim
```

Then update the two baked lookup paths: `Dockerfile` gains `COPY config/ /opt/dark-factory/config/`; `scheduler.sh` `CONFIG_YAML_PATHS` becomes `("/workspace/project/config/config.yaml" "/opt/dark-factory/config/config.yaml" "/opt/refinement-skills/config.yaml")` (old paths retained as fallbacks for the P2 transition when the factory reads the TARGET's config from its clone).

- [ ] **Step 4: Run the full test suite**

Run: `PYTHONPATH=scripts python -m pytest tests/ -q`
Expected: all pass (same count as MarketHawk's factory-tests job — currently ~200+ across the suite).
Run: `python scripts/check_workflow_dag.py workflows/archon-dark-factory.yaml`
Expected: `DAG trigger_rule check passed`.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "refactor: fix self-references after path promotion; canonicalize config/"
```

---

## Task 3: New-repo CI — tests + image build/publish

**Files:**
- Create: `.github/workflows/ci.yml`, `.github/workflows/publish.yml`

**Interfaces:**
- Produces: PR gate (`tests`, `dag-check`, `docker-build`) and on-main publish of `ghcr.io/omniscient/dark-factory:latest`.

- [ ] **Step 1: Write `ci.yml`** (mirrors MarketHawk's `factory-tests` + `docker-dark-factory` jobs, adapted paths)

```yaml
name: CI
on:
  pull_request:
    branches: [main]
jobs:
  tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install pytest pyyaml
      - run: PYTHONPATH=scripts python -m pytest tests/ -v
        env: { PYTHONPATH: scripts }
  dag-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install pyyaml
      - run: python scripts/check_workflow_dag.py workflows/archon-dark-factory.yaml
      - run: python scripts/check_workflow_when.py workflows/archon-dark-factory.yaml
  docker-build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker build -f Dockerfile -t dark-factory:pr .
```

- [ ] **Step 2: Write `publish.yml`** (mirrors MarketHawk's `build-dark-factory` job in `ci-publish.yml`, new image name)

```yaml
name: Publish
on:
  push:
    branches: [main]
  workflow_dispatch:
jobs:
  build-image:
    runs-on: ubuntu-latest
    permissions: { contents: read, packages: write }
    steps:
      - uses: actions/checkout@v4
      - uses: docker/login-action@v3
        with: { registry: ghcr.io, username: "${{ github.actor }}", password: "${{ secrets.GITHUB_TOKEN }}" }
      - uses: docker/metadata-action@v5
        id: meta
        with: { images: "ghcr.io/omniscient/dark-factory" }
      - uses: docker/build-push-action@v6
        with:
          context: .
          file: ./Dockerfile
          push: true
          tags: "${{ steps.meta.outputs.tags }}"
          labels: "${{ steps.meta.outputs.labels }}"
```

- [ ] **Step 3: Push a branch, open a PR, verify all three CI jobs green, merge, verify publish run pushes the image**

Run after merge: `docker pull ghcr.io/omniscient/dark-factory:latest && docker run --rm --entrypoint sh ghcr.io/omniscient/dark-factory:latest -c "which archon && python3 -c 'import yaml'"`
Expected: `/usr/local/bin/archon` + no import error.

- [ ] **Step 4: Set branch protection on main** (required checks: tests, dag-check, docker-build) — `gh api repos/omniscient/dark-factory/branches/main/protection` with the three contexts.

---

## Task 4: Instance identity — shell layer

Single source for owner/repo/board ids/branding across `scheduler.sh`, `entrypoint.sh`, `smoke_gate.sh`. Defaults = today's literals (parity invariant).

**Files:**
- Create: `scripts/identity.sh`, `deploy/instance.env.example`
- Modify: `scheduler.sh:12-21`, `entrypoint.sh:5-8,28-33`, `smoke_gate.sh:13,27,53,59,91`
- Test: `tests/test_identity.sh`

**Interfaces:**
- Produces (env contract, consumed by every later task):
  `FACTORY_OWNER` (default `omniscient`), `FACTORY_REPO` (default `markethawk`), `FACTORY_REPO_SLUG` (derived `owner/repo`), `FACTORY_PROJECT_ID` (default `PVT_kwHOAAFds84BWh4w`), `FACTORY_STATUS_FIELD` (default `PVTSSF_lAHOAAFds84BWh4wzhR1VaA`), `FACTORY_STATUS_READY=61e4505c`, `FACTORY_STATUS_IN_PROGRESS=47fc9ee4`, `FACTORY_STATUS_IN_REVIEW=df73e18b`, `FACTORY_STATUS_BLOCKED=93d87b2f`, `FACTORY_STATUS_DONE=98236657`, `FACTORY_STATUS_BACKLOG=f75ad846`, `FACTORY_STATUS_REFINED=0c79ebe5`, `FACTORY_PRODUCT_NAME` (default `MarketHawk`), `FACTORY_CLONE_DIR` (default `/workspace/markethawk`), `FACTORY_RUN_PREFIX` (default `markethawk-dark-factory-run-`), `FACTORY_IMAGE` (default `ghcr.io/omniscient/dark-factory:latest`).

- [ ] **Step 1: Write the failing test** — `tests/test_identity.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
# 1) defaults match today's literals
unset FACTORY_OWNER FACTORY_REPO FACTORY_PROJECT_ID FACTORY_PRODUCT_NAME || true
source scripts/identity.sh
[ "$FACTORY_OWNER" = "omniscient" ] || { echo "FAIL owner default"; exit 1; }
[ "$FACTORY_REPO" = "markethawk" ] || { echo "FAIL repo default"; exit 1; }
[ "$FACTORY_REPO_SLUG" = "omniscient/markethawk" ] || { echo "FAIL slug"; exit 1; }
[ "$FACTORY_STATUS_DONE" = "98236657" ] || { echo "FAIL status ids"; exit 1; }
[ "$FACTORY_PRODUCT_NAME" = "MarketHawk" ] || { echo "FAIL product name"; exit 1; }
# 2) env wins
FACTORY_OWNER=acme FACTORY_REPO=widgets bash -c '
  source scripts/identity.sh
  [ "$FACTORY_REPO_SLUG" = "acme/widgets" ] || exit 1'
# 3) no hardcoded slug remains in the three shell entrypoints outside identity defaults
! grep -n "omniscient/markethawk" scheduler.sh entrypoint.sh smoke_gate.sh || { echo "FAIL residual slug"; exit 1; }
echo PASS
```

- [ ] **Step 2: Run to verify it fails** — `bash tests/test_identity.sh` → FAIL (identity.sh missing).

- [ ] **Step 3: Implement `scripts/identity.sh`**

```bash
#!/usr/bin/env bash
# Instance identity — single source. Every value env-overridable; defaults = MarketHawk (parity).
export FACTORY_OWNER="${FACTORY_OWNER:-omniscient}"
export FACTORY_REPO="${FACTORY_REPO:-markethawk}"
export FACTORY_REPO_SLUG="${FACTORY_OWNER}/${FACTORY_REPO}"
export FACTORY_PROJECT_ID="${FACTORY_PROJECT_ID:-PVT_kwHOAAFds84BWh4w}"
export FACTORY_STATUS_FIELD="${FACTORY_STATUS_FIELD:-PVTSSF_lAHOAAFds84BWh4wzhR1VaA}"
export FACTORY_STATUS_READY="${FACTORY_STATUS_READY:-61e4505c}"
export FACTORY_STATUS_IN_PROGRESS="${FACTORY_STATUS_IN_PROGRESS:-47fc9ee4}"
export FACTORY_STATUS_IN_REVIEW="${FACTORY_STATUS_IN_REVIEW:-df73e18b}"
export FACTORY_STATUS_BLOCKED="${FACTORY_STATUS_BLOCKED:-93d87b2f}"
export FACTORY_STATUS_DONE="${FACTORY_STATUS_DONE:-98236657}"
export FACTORY_STATUS_BACKLOG="${FACTORY_STATUS_BACKLOG:-f75ad846}"
export FACTORY_STATUS_REFINED="${FACTORY_STATUS_REFINED:-0c79ebe5}"
export FACTORY_PRODUCT_NAME="${FACTORY_PRODUCT_NAME:-MarketHawk}"
export FACTORY_CLONE_DIR="${FACTORY_CLONE_DIR:-/workspace/${FACTORY_REPO}}"
export FACTORY_RUN_PREFIX="${FACTORY_RUN_PREFIX:-${FACTORY_REPO}-dark-factory-run-}"
export FACTORY_IMAGE="${FACTORY_IMAGE:-ghcr.io/omniscient/dark-factory:${IMAGE_TAG:-latest}}"
```

(Default `FACTORY_CLONE_DIR` derives to `/workspace/markethawk` and `FACTORY_RUN_PREFIX` to `markethawk-dark-factory-run-` — parity holds.)

- [ ] **Step 4: Rewire the three shell entrypoints** using the coupling inventory line numbers:
  - `scheduler.sh:12-21` → replace the nine constant lines with `source "$(dirname "$0")/scripts/identity.sh"` and rename all uses: `$OWNER`→`$FACTORY_OWNER`, `$PROJECT_ID`→`$FACTORY_PROJECT_ID`, `$STATUS_*`→`$FACTORY_STATUS_*`; every `--repo "${OWNER}/markethawk"` (19 sites: lines 306,326,328,344,361,363,384,401,432,492,505,518,628,641,665,849,914,1026,1029) → `--repo "$FACTORY_REPO_SLUG"`; `:171` container grep + `:768` image default → `$FACTORY_RUN_PREFIX` / drop (now in identity).
  - `entrypoint.sh:5-8` → `REPO_URL="https://${GH_TOKEN}@github.com/${FACTORY_REPO_SLUG}.git"`, `CLONE_DIR="$FACTORY_CLONE_DIR"`, `FACTORY_NAME="${FACTORY_PRODUCT_NAME} Factory"`, `FACTORY_EMAIL="factory@${FACTORY_REPO}"`; `:28-33` board constants → identity vars; `:95,:181` artifacts paths → `${HOME}/.archon/workspaces/${FACTORY_REPO_SLUG}/artifacts/runs`; `:107` grep → `$FACTORY_RUN_PREFIX`; all `repos/omniscient/markethawk` API paths (149,155,244,286,296,350,583) → `repos/${FACTORY_REPO_SLUG}`.
  - `smoke_gate.sh:13,27` → `${CLONE_DIR:-$FACTORY_CLONE_DIR}`; `:53,59,91` → `--repo "$FACTORY_REPO_SLUG"`. (The tsc/backend-import CHECKS stay hardcoded here — they become the default smoke hook in Task 9.)

- [ ] **Step 5: Run tests** — `bash tests/test_identity.sh` → PASS; `bash tests/test_scheduler.sh` → PASS (existing suite exercises dispatch paths); `PYTHONPATH=scripts python -m pytest tests/ -q` → all pass.

- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat: instance identity layer (shell) — env-overridable owner/repo/board/branding, MarketHawk defaults"`

---

## Task 5: Instance identity — Python layer (`factory_core/identity.py`)

**Files:**
- Create: `scripts/factory_core/identity.py`
- Modify: `scripts/factory_core/board.py:6-17`, `cli.py:18-24`, `breaker.py:62-63,100`, `epic_autopilot.py:247,265,274,286-287,344,373`, `main_red_fixer.py:128-129,185,240`, `deconflict.py:191`, `rescue.py:114`
- Test: `tests/test_factory_core_identity.py`

**Interfaces:**
- Produces: `identity.OWNER`, `identity.REPO`, `identity.SLUG`, `identity.PROJECT_ID`, `identity.STATUS_FIELD`, `identity.STATUS` (dict: ready/in_progress/in_review/blocked/done/backlog/refined → option ids), `identity.PRODUCT_NAME`, `identity.marker(kind: str) -> str` returning e.g. `"*Posted by MarketHawk Dark Factory*"` for `kind="factory"`, `"…Backlog Scheduler*"` for `"scheduler"`, `"…Refinement Pipeline*"` for `"refinement"`, `"…Epic Autopilot*"` for `"autopilot"`, `"*MarketHawk Main-Red Auto-Fix*"` for `"main_red"`.

- [ ] **Step 1: Write the failing test** — `tests/test_factory_core_identity.py`:

```python
import importlib, os, sys
sys.path.insert(0, "scripts")

def _fresh(monkeypatch, **env):
    for k in ("FACTORY_OWNER", "FACTORY_REPO", "FACTORY_PROJECT_ID", "FACTORY_PRODUCT_NAME"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import factory_core.identity as identity
    return importlib.reload(identity)

def test_defaults_are_markethawk(monkeypatch):
    ident = _fresh(monkeypatch)
    assert ident.SLUG == "omniscient/markethawk"
    assert ident.PROJECT_ID == "PVT_kwHOAAFds84BWh4w"
    assert ident.STATUS["done"] == "98236657"
    assert ident.marker("factory") == "*Posted by MarketHawk Dark Factory*"
    assert ident.marker("scheduler") == "*Posted by MarketHawk Backlog Scheduler*"

def test_env_overrides(monkeypatch):
    ident = _fresh(monkeypatch, FACTORY_OWNER="acme", FACTORY_REPO="widgets",
                   FACTORY_PRODUCT_NAME="Acme")
    assert ident.SLUG == "acme/widgets"
    assert ident.marker("factory") == "*Posted by Acme Dark Factory*"

def test_board_consumes_identity(monkeypatch):
    _fresh(monkeypatch, FACTORY_REPO="widgets")
    import factory_core.board as board
    importlib.reload(board)
    assert board.REPO == "widgets"
```

- [ ] **Step 2: Run to verify fail** — `PYTHONPATH=scripts python -m pytest tests/test_factory_core_identity.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement `scripts/factory_core/identity.py`**

```python
"""Instance identity — single Python source. Env-overridable; defaults = MarketHawk (parity)."""
import os

OWNER = os.environ.get("FACTORY_OWNER", "omniscient")
REPO = os.environ.get("FACTORY_REPO", "markethawk")
SLUG = f"{OWNER}/{REPO}"
PROJECT_ID = os.environ.get("FACTORY_PROJECT_ID", "PVT_kwHOAAFds84BWh4w")
STATUS_FIELD = os.environ.get("FACTORY_STATUS_FIELD", "PVTSSF_lAHOAAFds84BWh4wzhR1VaA")
STATUS = {
    "ready": os.environ.get("FACTORY_STATUS_READY", "61e4505c"),
    "in_progress": os.environ.get("FACTORY_STATUS_IN_PROGRESS", "47fc9ee4"),
    "in_review": os.environ.get("FACTORY_STATUS_IN_REVIEW", "df73e18b"),
    "blocked": os.environ.get("FACTORY_STATUS_BLOCKED", "93d87b2f"),
    "done": os.environ.get("FACTORY_STATUS_DONE", "98236657"),
    "backlog": os.environ.get("FACTORY_STATUS_BACKLOG", "f75ad846"),
    "refined": os.environ.get("FACTORY_STATUS_REFINED", "0c79ebe5"),
}
PRODUCT_NAME = os.environ.get("FACTORY_PRODUCT_NAME", "MarketHawk")
CLONE_DIR = os.environ.get("FACTORY_CLONE_DIR", os.environ.get("CLONE_DIR", f"/workspace/{REPO}"))

_MARKERS = {
    "factory": "*Posted by {} Dark Factory*",
    "scheduler": "*Posted by {} Backlog Scheduler*",
    "refinement": "*Posted by {} Refinement Pipeline*",
    "autopilot": "*Posted by {} Epic Autopilot*",
    "main_red": "*{} Main-Red Auto-Fix*",
}

def marker(kind: str) -> str:
    return _MARKERS[kind].format(PRODUCT_NAME)
```

- [ ] **Step 4: Rewire the six consumers** (inventory line numbers): `board.py:6-17` constants → `from . import identity` re-exports (`OWNER = identity.OWNER` etc. so existing importers keep working); `cli.py:18-24` defaults → identity; `breaker.py:62-63` parameter defaults → `identity.OWNER`/`identity.REPO`, `:100` marker → `identity.marker("scheduler")`; `epic_autopilot.py:286-287` → identity, `:344,:373` GraphQL owner/name → f-string from identity, markers `:247,:265,:274` → `identity.marker("autopilot")` (the `:290` hard-exclude paths move to the adapter in Task 8 — leave for now); `main_red_fixer.py:128-129` → identity, markers → `identity.marker("main_red")`; `deconflict.py:191` + `rescue.py:114` markers → identity.

- [ ] **Step 5: Run full suite** — `PYTHONPATH=scripts python -m pytest tests/ -q` → all pass (existing tests pin the default strings, which are unchanged).

- [ ] **Step 6: Commit** — `git commit -am "feat: factory_core identity module; board/breaker/autopilot/main-red/deconflict/rescue consume it"`

---

## Task 6: Marker parameterization in parsers and remaining shell

The markers are *written* via identity now; this task makes the *readers* agree.

**Files:**
- Modify: `scripts/comment_digest.py` (`_BOT_RE`, factory-boundary marker), `entrypoint.sh` marker literals (`:234,:342,:390,:408,:591`), `scheduler.sh` marker literals (15 sites from inventory), `tests/test_has_new_comment_after_report.sh` (parameterized fixtures)
- Test: extend `tests/test_comment_digest.py`

**Interfaces:**
- Consumes: `identity.marker()` / `$FACTORY_PRODUCT_NAME`.

- [ ] **Step 1: Failing test** — append to `tests/test_comment_digest.py`:

```python
def test_bot_markers_follow_product_name(monkeypatch):
    monkeypatch.setenv("FACTORY_PRODUCT_NAME", "Acme")
    import importlib, comment_digest as cd
    importlib.reload(cd)
    body = "---\n*Posted by Acme Dark Factory*"
    assert cd._BOT_RE.search(body), "marker regex must track FACTORY_PRODUCT_NAME"
```

- [ ] **Step 2: Verify fail**, then implement: `comment_digest.py` builds `_BOT_RE` from `os.environ.get("FACTORY_PRODUCT_NAME", "MarketHawk")` interpolated into the existing alternation (`Posted by {P} Refinement Pipeline|Posted by {P} Backlog Scheduler|Posted by {P} Dark Factory`), with `re.escape` on the name. Shell writers: replace each literal `MarketHawk` in marker strings with `${FACTORY_PRODUCT_NAME}`.

- [ ] **Step 3: Full suite + commit** — `git commit -am "feat: comment markers parameterized by FACTORY_PRODUCT_NAME end-to-end"`

---

## Task 7: Workflow + command prompts — interpolate identity

**Files:**
- Modify: `workflows/archon-dark-factory.yaml` (slug/board id sites: 107,200,219,223,225,226,342,359,749,879,917,921,923,924,1100), `commands/dark-factory-{refine,plan,implement,conformance,code-review,validate,revise-advisory}.md`, `commands/ceiling-revisit.md`
- Test: `tests/test_command_identity.py` (new), existing `tests/test_code_review_command.py` (update)

**Interfaces:**
- Consumes: the Task-4 env contract (Archon bash nodes and command bash blocks inherit the container env, which `entrypoint.sh` exports after sourcing identity).

- [ ] **Step 1: Failing test** — `tests/test_command_identity.py`:

```python
from pathlib import Path
FILES = list(Path("commands").glob("dark-factory-*.md")) + [
    Path("commands/ceiling-revisit.md"), Path("workflows/archon-dark-factory.yaml")]

def test_no_hardcoded_slug():
    for f in FILES:
        assert "omniscient/markethawk" not in f.read_text(encoding="utf-8"), f
def test_no_hardcoded_project_id():
    for f in FILES:
        t = f.read_text(encoding="utf-8")
        assert "PVT_kwHOAAFds84BWh4w" not in t, f
        assert "PVTSSF_lAHOAAFds84BWh4wzhR1VaA" not in t, f
```

- [ ] **Step 2: Verify fail**, then mechanically replace in bash blocks: `--repo omniscient/markethawk` → `--repo "$FACTORY_REPO_SLUG"`; `repos/omniscient/markethawk/…` → `repos/${FACTORY_REPO_SLUG}/…`; `gh project item-list 1 --owner omniscient` → `--owner "$FACTORY_OWNER"` with project number from `$FACTORY_PROJECT_NUMBER` (add to identity, default `1`); `--project-id PVT_…` → `--project-id "$FACTORY_PROJECT_ID"`; `--field-id PVTSSF_…` → `--field-id "$FACTORY_STATUS_FIELD"`; `--single-select-option-id 93d87b2f` → `"$FACTORY_STATUS_BLOCKED"` (match each id to its named var: 98236657→DONE, df73e18b→IN_REVIEW). Prose links `https://github.com/omniscient/markethawk/...` → `https://github.com/${FACTORY_REPO_SLUG}/...`. Update `tests/test_code_review_command.py:17-18` to assert the *variable names* are present instead of raw ids.
  MarketHawk-specific *content* in commands (alembic steps, `cd backend`, curl health checks, memory-routing tables in `dark-factory-plan.md:68-69`) is **left alone** — that is P2 adapter material and behavior must stay identical.

- [ ] **Step 3: DAG + when validators** — `python scripts/check_workflow_dag.py workflows/archon-dark-factory.yaml && python scripts/check_workflow_when.py workflows/archon-dark-factory.yaml` → both pass (no `when:` strings were touched).

- [ ] **Step 4: Full suite + commit** — `git commit -am "feat: workflow/commands consume identity env instead of hardcoded slug/board ids"`

---

## Task 8: Adapter loader — `factory_core/adapter.py` + defaults

**Files:**
- Create: `scripts/factory_core/adapter_defaults.py`, `scripts/factory_core/adapter.py`
- Test: `tests/test_adapter.py`

**Interfaces:**
- Produces:
  - `adapter.load(clone_dir: str) -> dict` — reads `<clone_dir>/.factory/adapter.yaml` if present, validates, deep-merges over `adapter_defaults.DEFAULTS`, returns the merged dict. Missing file → pure defaults. Invalid file → raises `AdapterError(msg)` with a one-line human message (dispatch layer turns this into ticket comment + skip).
  - `adapter.get(clone_dir, "safety.sensitive_keywords")` — dotted-path convenience.
  - CLI: `python -m factory_core.adapter --clone-dir X --get safety.sensitive_keywords` (shell consumers), and `--validate` (exit 0/1 + message).
- Consumed by: Task 9 rewires; P2 authors MarketHawk's real adapter against this schema.

- [ ] **Step 1: Write `adapter_defaults.py`** — today's MarketHawk constants, verbatim from main (values below are the live ones as of 2026-07-03, including this week's #731 cap raise):

```python
"""Default adapter = MarketHawk's current constants. Parity: no adapter file == today."""
DEFAULTS = {
    "schema_version": 1,
    "components": {
        # COMPONENT_SECTION_MAP from scripts/architecture_slice.py — copy verbatim at implementation
        # time from the extracted file (backend/frontend/dark-factory/infrastructure → section lists)
    },
    "safety": {
        "sensitive_keywords": "trading|ibkr|live order|notional|authentication|authorization|authn|authz|jwt|oauth|rbac|/auth",
        "hard_exclude_paths": [
            "dark-factory/", ".archon/", "scheduler.sh", "factory_core/",
            "app/services/trading", "app/tasks/trading.py", "app/core/auth", "app/routers/auth",
        ],
        "dispatch_ceiling_keywords": "migration|migrate|performance|perf|architectur|refactor",
        "critical_diff_paths": [],   # copy diff_rank.py critical-tier regex list verbatim at implementation time
        "migration_seed_auth_patterns": [
            r"^alembic/versions/", r"^dark-factory/seed/", r"seed.*\.sql$",
            r"^backend/app/routers/auth\.py$",
        ],
        "main_red_allowed_paths": ["backend/", "frontend/", "alembic/", "dark-factory/smoke_gate.sh"],
    },
    "memory_routing": {
        "backend/app/*": ".archon/memory/backend-patterns.md",
        "frontend/src/*": ".archon/memory/frontend-patterns.md",
    },
    "deconflict": {
        "models_init": "backend/app/models/__init__.py",
        "migrations_dir": "alembic/versions/",
    },
}
```

(The two "copy verbatim" entries are filled by the implementer from the extracted files in the same commit — they are code moves, not new content; the tests in Step 3 pin them equal to the source constants.)

- [ ] **Step 2: Write failing tests** — `tests/test_adapter.py`:

```python
import sys
sys.path.insert(0, "scripts")
import pytest
from factory_core import adapter, adapter_defaults

def test_no_adapter_file_returns_defaults(tmp_path):
    merged = adapter.load(str(tmp_path))
    assert merged == adapter_defaults.DEFAULTS

def test_adapter_overrides_deep_merge(tmp_path):
    d = tmp_path / ".factory"; d.mkdir()
    (d / "adapter.yaml").write_text(
        "schema_version: 1\nsafety:\n  sensitive_keywords: 'payments|pii'\n")
    merged = adapter.load(str(tmp_path))
    assert merged["safety"]["sensitive_keywords"] == "payments|pii"
    # untouched siblings survive the merge
    assert merged["safety"]["dispatch_ceiling_keywords"] == \
        adapter_defaults.DEFAULTS["safety"]["dispatch_ceiling_keywords"]

def test_invalid_yaml_raises_adapter_error(tmp_path):
    d = tmp_path / ".factory"; d.mkdir()
    (d / "adapter.yaml").write_text("{broken: [")
    with pytest.raises(adapter.AdapterError):
        adapter.load(str(tmp_path))

def test_wrong_type_raises_adapter_error(tmp_path):
    d = tmp_path / ".factory"; d.mkdir()
    (d / "adapter.yaml").write_text("schema_version: 1\nsafety: 'not-a-map'\n")
    with pytest.raises(adapter.AdapterError):
        adapter.load(str(tmp_path))

def test_unknown_keys_warn_not_fail(tmp_path, capsys):
    d = tmp_path / ".factory"; d.mkdir()
    (d / "adapter.yaml").write_text("schema_version: 1\nfuture_feature: {a: 1}\n")
    merged = adapter.load(str(tmp_path))
    assert "future_feature" in merged            # carried through
    assert "unknown adapter key" in capsys.readouterr().err

def test_dotted_get(tmp_path):
    assert adapter.get(str(tmp_path), "deconflict.migrations_dir") == "alembic/versions/"
```

- [ ] **Step 3: Verify fail, implement `adapter.py`**

```python
"""Load + validate <clone>/.factory/adapter.yaml, deep-merged over adapter_defaults.DEFAULTS."""
import argparse, copy, os, sys
from . import adapter_defaults

class AdapterError(Exception):
    pass

_KNOWN_TOP = {"schema_version", "components", "safety", "memory_routing", "deconflict",
              "token_optimization", "repo", "board", "labels"}
_MAP_KEYS = {"components", "safety", "memory_routing", "deconflict", "token_optimization",
             "board", "labels"}

def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out

def load(clone_dir: str) -> dict:
    path = os.path.join(clone_dir, ".factory", "adapter.yaml")
    if not os.path.isfile(path):
        return copy.deepcopy(adapter_defaults.DEFAULTS)
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as exc:
        raise AdapterError(f"adapter.yaml unreadable/unparseable: {exc}") from exc
    if not isinstance(data, dict):
        raise AdapterError("adapter.yaml top level must be a mapping")
    if not isinstance(data.get("schema_version", 1), int):
        raise AdapterError("schema_version must be an integer")
    for k, v in data.items():
        if k not in _KNOWN_TOP:
            print(f"adapter: warning — unknown adapter key '{k}' (carried through)", file=sys.stderr)
        if k in _MAP_KEYS and not isinstance(v, dict):
            raise AdapterError(f"adapter key '{k}' must be a mapping, got {type(v).__name__}")
    return _deep_merge(adapter_defaults.DEFAULTS, data)

def get(clone_dir: str, dotted: str):
    node = load(clone_dir)
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--clone-dir", default=os.environ.get("CLONE_DIR", "."))
    p.add_argument("--get")
    p.add_argument("--validate", action="store_true")
    args = p.parse_args()
    try:
        if args.get:
            val = get(args.clone_dir, args.get)
            print("" if val is None else val)
        elif args.validate:
            load(args.clone_dir)
            print("adapter OK")
    except AdapterError as exc:
        print(f"adapter INVALID: {exc}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Tests pass; full suite; commit** — `git commit -am "feat: .factory/adapter.yaml loader with MarketHawk defaults + validation"`

---

## Task 9: Route target knowledge through the adapter (default-parity)

**Files:**
- Modify: `scripts/architecture_slice.py` (COMPONENT_SECTION_MAP ← `adapter["components"]`), `scripts/diff_rank.py` (critical-tier patterns ← `adapter["safety"]["critical_diff_paths"]`), `scripts/gate_blast_radius.py:75-80` (← `migration_seed_auth_patterns`), `scripts/factory_core/epic_autopilot.py:290` (← `hard_exclude_paths` — keyword string already read from config; move both reads to adapter), `scripts/factory_core/main_red_fixer.py:258` (← `main_red_allowed_paths`), `scripts/gate_lib.sh:13-14` (← `python -m factory_core.adapter --get memory_routing…` lookup), `scripts/factory_core/deconflict.py:34,61` (← `deconflict.*`)
- Test: extend `tests/test_adapter.py` + touched files' suites

**Interfaces:**
- Consumes: `adapter.load(CLONE_DIR)`. Every consumer wraps in try/except → falls back to `adapter_defaults.DEFAULTS` (fail-open, identical to today).

- [ ] **Step 1: For each consumer, write one failing parity test + one override test.** Pattern (architecture_slice example — replicate for each consumer with its own key):

```python
def test_component_map_default_parity(tmp_path):
    import architecture_slice as a
    assert a._component_section_map(str(tmp_path)) == adapter_defaults.DEFAULTS["components"]

def test_component_map_adapter_override(tmp_path):
    d = tmp_path / ".factory"; d.mkdir()
    (d / "adapter.yaml").write_text(
        "components:\n  api: ['Overview', 'API Layer']\n")
    import architecture_slice as a
    m = a._component_section_map(str(tmp_path))
    assert m["api"] == ["Overview", "API Layer"]
    assert "backend" in m   # defaults still merged in
```

- [ ] **Step 2: Implement each consumer** as a small `_from_adapter(clone_dir, dotted, fallback)` helper call replacing the module constant at use-time (constants stay as the values inside `adapter_defaults` — moved, not duplicated). Shell consumer `gate_lib.sh` shells out: `python3 -m factory_core.adapter --clone-dir "$CLONE_DIR" --get "memory_routing" …` with the current case-statement as fallback when python fails.

- [ ] **Step 3: Full suite after each consumer; commit per consumer** (7 commits: arch-slice, diff-rank, blast-radius, autopilot, main-red, gate_lib, deconflict).

---

## Task 10: Hook runner

**Files:**
- Create: `scripts/hooks.sh`
- Modify: `entrypoint.sh` (smoke-gate + validate call sites), `smoke_gate.sh` (becomes the built-in default implementation)
- Test: `tests/test_hooks.sh`

**Interfaces:**
- Produces: `run_hook <name> [args…]` — if `${CLONE_DIR}/.factory/hooks/<name>` exists and is executable, run it with env `CLONE_DIR ARTIFACTS_DIR ISSUE_NUM FACTORY_REPO_SLUG`; else run the built-in default (`smoke-gate` → current `smoke_gate.sh` logic; `validate`/`preview-up`/`preview-down` → no-op exit 0 defaults until P2 moves MarketHawk's versions into its adapter). Gate semantics: `run_hook --gate smoke-gate` propagates non-zero; non-gate invocations are `|| true`.

- [ ] **Step 1: Failing test** — `tests/test_hooks.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
source scripts/hooks.sh
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
export CLONE_DIR="$TMP" ARTIFACTS_DIR="$TMP/art"; mkdir -p "$ARTIFACTS_DIR"
# 1) missing hook, non-gate → default no-op success
run_hook validate || { echo "FAIL: missing non-gate hook must succeed"; exit 1; }
# 2) target hook is discovered and runs with the env contract
mkdir -p "$TMP/.factory/hooks"
printf '#!/bin/sh\necho "$CLONE_DIR" > "$ARTIFACTS_DIR/hook-ran"\n' > "$TMP/.factory/hooks/validate"
chmod +x "$TMP/.factory/hooks/validate"
run_hook validate
grep -q "$TMP" "$ARTIFACTS_DIR/hook-ran" || { echo "FAIL: hook env"; exit 1; }
# 3) gate propagates failure
printf '#!/bin/sh\nexit 3\n' > "$TMP/.factory/hooks/smoke-gate"; chmod +x "$TMP/.factory/hooks/smoke-gate"
if run_hook --gate smoke-gate; then echo "FAIL: gate must propagate"; exit 1; fi
echo PASS
```

- [ ] **Step 2: Verify fail, implement `scripts/hooks.sh`**

```bash
#!/usr/bin/env bash
# run_hook [--gate] <name> [args…] — target hook > built-in default. Gate = propagate exit code.
run_hook() {
  local gate=0
  [ "$1" = "--gate" ] && { gate=1; shift; }
  local name="$1"; shift || true
  local hook="${CLONE_DIR}/.factory/hooks/${name}"
  local rc=0
  if [ -x "$hook" ]; then
    CLONE_DIR="$CLONE_DIR" ARTIFACTS_DIR="${ARTIFACTS_DIR:-}" ISSUE_NUM="${ISSUE_NUM:-}" \
      FACTORY_REPO_SLUG="${FACTORY_REPO_SLUG:-}" "$hook" "$@" || rc=$?
  else
    case "$name" in
      smoke-gate) _default_smoke_gate "$@" || rc=$? ;;   # provided by smoke_gate.sh
      *) rc=0 ;;                                          # no default → no-op
    esac
  fi
  if [ "$gate" = "1" ]; then return "$rc"; else return 0; fi
}
```

Rewire `entrypoint.sh` smoke/validate call sites to `run_hook --gate smoke-gate` / `run_hook validate`; wrap `smoke_gate.sh`'s body into `_default_smoke_gate()` sourced by `hooks.sh` (behavior unchanged: default = today's MarketHawk checks, per parity invariant — MarketHawk works with zero adapter until P2 relocates these into its `.factory/`).

- [ ] **Step 3: Tests + full suite + commit** — `git commit -am "feat: hook runner with target-hook discovery and built-in defaults"`

---

## Task 11: Deploy template + instance docs

**Files:**
- Create: `deploy/docker-compose.yml`, `deploy/instance.env.example`, `README.md` (top-level: what this is, quickstart, adapter contract summary, deploy walkthrough)

**Interfaces:**
- Consumes: Task 4 env contract. Produces: the artifact P3 uses to stand up MarketHawk's cutover instance.

- [ ] **Step 1: `deploy/docker-compose.yml`** — port of MarketHawk's `backlog-scheduler` + `docker-socket-proxy-scheduler` service definitions (from the app compose), image `ghcr.io/omniscient/dark-factory:${IMAGE_TAG:-latest}`, `env_file: instance.env`, named state volume for `/var/lib/dark-factory`. Copy the two service blocks verbatim from MarketHawk `docker-compose.yml`, renaming env_file and dropping app networks.

- [ ] **Step 2: `deploy/instance.env.example`** — every Task-4/5 identity var with the MarketHawk values as commented examples + `GH_TOKEN=`, `CLAUDE_CODE_OAUTH_TOKEN=`, `FACTORY_WIP_LIMIT=1`, `POLL_INTERVAL=60`. A header comment states: identity vars REQUIRED for any non-MarketHawk target; defaults exist only for parity.

- [ ] **Step 3: README** — sections: What/Why, Architecture (1 diagram of scheduler→dispatch→target clone→adapter), Quickstart (deploy dir + instance.env + compose up), Adapter contract (`adapter.yaml` keys table + hooks table with env contract), Rollback (git-based, clone-read semantics), Link to extraction spec in MarketHawk.

- [ ] **Step 4: Commit + PR + merge** (CI green).

---

## Task 12: End-to-end parity verification (P1 exit gate)

**Files:**
- Create: `docs/parity-p1.md` (results record)

- [ ] **Step 1: Full test suite in the published image**

```bash
docker pull ghcr.io/omniscient/dark-factory:latest
docker run --rm --entrypoint bash -v "$PWD:/repo" ghcr.io/omniscient/dark-factory:latest \
  -c "pip install pytest -q; cd /repo && PYTHONPATH=scripts python -m pytest tests/ -q"
```
Expected: all pass.

- [ ] **Step 2: Identity-override smoke** — run the scheduler's dry parts with a fake identity and confirm zero `omniscient/markethawk` literals reach the wire:

```bash
FACTORY_OWNER=acme FACTORY_REPO=widgets bash -c '
  source scripts/identity.sh
  bash -n scheduler.sh && bash -n entrypoint.sh
  grep -RIn "omniscient/markethawk" scheduler.sh entrypoint.sh smoke_gate.sh scripts/factory_core/*.py commands/ workflows/ && exit 1 || echo NO-RESIDUAL-SLUG'
```
Expected: `NO-RESIDUAL-SLUG`.

- [ ] **Step 3: Default-parity assertion** — with no env and no adapter: `python -c` comparing `adapter.load(".")` deep-equals `adapter_defaults.DEFAULTS`, and `identity.SLUG == "omniscient/markethawk"`.

- [ ] **Step 4: Record results in `docs/parity-p1.md`, commit, and post a completion summary to MarketHawk issue #738** (this plan's epic ticket): what was extracted, CI/image links, parity evidence, and that P2 (MarketHawk adapter + bench parity run) is next.

---

## Self-review notes

- **Spec coverage:** P0 = Tasks 1–3 (extract, self-refs, CI/publish). P1 = Tasks 4–10 (identity shell/python, markers, workflow/commands, adapter loader, adapter consumers, hooks) + 11 (deploy template, spec "Runtime" section) + 12 (exit gate). `factory init`, MarketHawk's real `.factory/`, bench parity run, cutover, dogfood = P2–P4, explicitly out of scope per Global Constraints.
- **Placeholders:** the two "copy verbatim at implementation time" entries in Task 8 Step 1 are deliberate code-moves from files that exist in the extracted tree (exact sources named); pinned by parity tests. No TBDs otherwise.
- **Type consistency:** env var names in Tasks 4/5/7/10/11/12 all match the Task-4 contract table; `adapter.load/get/AdapterError` signatures consistent across Tasks 8/9/10.
