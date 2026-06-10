# Evidence-Gathering Playbook

Run §1 (agents) and §2 (live commands) in parallel where possible. Everything feeds the scoring
pass; nothing is scored without an artifact (file:line, command output, or agent finding you
spot-checked).

## §0 Baseline extraction

1. Read `docs/architecture-reviews/README.md` and the latest `*-report-vN.html`.
2. Extract into working notes: 16 scorecard scores, 11 §3.x scores, the 13 reliability and 10 security sub-scores, risk register (IDs, severity, status), god-module line counts, roadmap items.
3. `gh issue list --label architecture-audit-vN --state all --json number,title,state,labels --limit 100` — what got ticketed, what closed.
4. `git rev-parse --short HEAD` and `git rev-list --count HEAD` for the header; `git log --oneline <prior-commit>..HEAD | Measure-Object -Line` for commits-since-prior.

## §1 Parallel Explore agents

Dispatch in ONE message (they're independent). Each prompt should demand file:line evidence and explicitly forbid relying on docs/commit messages.

1. **Architecture & layering** — routers/services/providers/models boundary violations; service-to-service imports and circular deps; HTTPException (or other web concerns) raised from services; dependency direction; registry/string couplings in `main.py`/`celery_app.py`. Map to §3.1–3.4.
2. **Security** — auth middleware coverage incl. WebSocket scopes; secrets defaults + validators in `core/config.py`; CORS/rate-limit/CSRF state; cookie flags; Docker socket mounts, root containers, port bindings in `docker-compose.yml`. Map to §3.10 + §7. (For staged-changes-only audits there is a separate `security-audit-staged` agent; this one reviews the tree.)
3. **Reliability & observability** — metrics/tracing wiring END-TO-END (who writes, who scrapes, does the dashboard have data); retry/timeout/circuit-breaker presence; backup automation; health-check depth. Map to §3.9, §6.
4. **Complexity & duplication** — top-complexity functions (branches, length, nesting) in backend services/routers/tasks AND frontend pages/components; duplication patterns with occurrence counts (track the standing ones: UTC normalization, 404 handlers, Redis JSON ops, modal state, toggle arrays). Map to §4 + §11.
5. **Testing & CI** — test file/function counts per tier; coverage config honesty (exclusions, pinned includes, thresholds); CI workflow inventory and whether each gate can actually fail (`|| true` hunting). Map to §5 + DevX.
6. **Data & API** — eager-loading coverage, N+1 candidates, pagination-with-joinedload bugs, JSONB usage, API versioning consistency, schema drift between frontend api/*.ts and backend schemas. Map to §3.5–3.6, §9.

## §2 Live verification commands (record exit codes)

```powershell
# Frontend gates — run these, never trust the README
cd frontend; npx tsc --noEmit; npx eslint src --max-warnings 0; npm run build
# Backend gates
cd backend; ruff check .; python -m pytest --collect-only -q | Select-Object -Last 3
# Type/any drift
# (count ': any' occurrences)  rg ": any" frontend/src -c | Measure-Object -Line
# Counts for §2 metrics table
# LOC: rg --files backend/app -g '*.py' | excl. alembic → wc; same for frontend/src
# Audits (advisory unless CI blocks them)
pip-audit 2>$null; npm audit --omit dev 2>$null
```

Also: `docker-compose config --services | Measure-Object -Line` (service count), `ls docs/adr` (ADR count), `ls backend/app/alembic/versions` (migrations), model/router/service file counts via Glob.

Optional enrichers when available (per CLAUDE.md): `~/.venvs/repowise/bin/repowise health` (worst-health files for §11), codeindex MCP `get_impact` (blast radius of refactor candidates).

## §3 Scoring pass

For each scored item: prior score → evidence → does the anchor for prior+1 / prior-1 fit better? Write the "caps the score" sentence first; if you can't name what caps it, the score is probably a 5 or you're missing evidence. Compute headline numbers with RUBRIC.md formulas and sanity-check against the calibration table.

## §4 DORA derivation (window: prior review date → today)

```powershell
$since = "2026-06-03"  # prior review date
# Deployment frequency proxy: merges to main per week
git log --merges --since=$since --format="%ad" --date=short main
# Lead time: PR created → merged (median)
gh pr list --state merged --search "merged:>$since" --json number,createdAt,mergedAt,additions,deletions,author --limit 200
# Change failure proxy: fix/revert commits in window vs merged PRs
git log --since=$since --format="%h %s" main  # count subjects matching ^fix|^revert|hotfix
# MTTR proxy: bug-labeled issues closed in window
gh issue list --label bug --state closed --search "closed:>$since" --json createdAt,closedAt --limit 100
# Factory vs human share
git log --since=$since --format="%an" main  # group + count
```

Compute medians yourself (don't eyeball). Present each metric with: value, window, prior-window value, the proxy definition, and the DORA band it would map to *if* the proxy were the real thing. If `gh` data is sparse (<10 PRs), say so and widen the window rather than reporting noise.

## §5 Render & verify

1. Copy `assets/report-shell.html` content as the base; fill placeholders section-by-section per SECTIONS.md. Update the `dims` array in the scorebar script with real numbers.
2. Write to `docs/architecture-reviews/YYYY-MM-DD-architecture-quality-report-vN.html`.
3. `Start-Process <path>` — visually confirm: scorebars render, Mermaid diagrams render, no raw `{{placeholder}}` left (grep the file for `{{` before opening).
4. Update README.md: table row, headline movement, follow-up label pointer.
