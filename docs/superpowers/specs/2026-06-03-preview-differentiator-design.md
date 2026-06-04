# Preview Environment Differentiator

> Tracking issue: [#178](https://github.com/omniscient/markethawk/issues/178)

## Goal

Not every issue the dark factory implements needs a full preview environment. A
docs-only change (e.g. issue #168 — four markdown files) spins up postgres, redis,
backend, frontend, and a celery worker, runs migrations, and waits up to 180s for
health — all to let a human review prose that the running stack never touches.

This adds a **differentiator step**: an LLM classifier that inspects the branch's
changeset and decides whether a preview environment is warranted. When it isn't,
`preview-up` no-ops, and the validate / PR / report steps adapt. Code-affecting
changes are unaffected — they still get a full preview.

## Scope

In scope:
- A new classifier node in `archon-dark-factory.yaml` that gates the preview.
- `preview-up` becomes a gated executor (always runs; no-ops when told to skip).
- `validate`, `push-and-pr`, and `report` adapt to a skipped preview.
- A `preview:` config block in `.claude/skills/refinement/config.yaml` with a
  kill-switch.

Out of scope (YAGNI):
- Label-based overrides (`needs-preview` / `skip-preview`).
- A deterministic path-rule fallback alongside the classifier.
- Auto-teardown of an already-running preview when a `continue` run turns docs-only.

## Architecture

### Where it sits in the workflow

The classifier runs after the implementation and codeindex regeneration are
complete (so the full branch diff is known), and before the preview is built:

```
implement
  → regen-codeindex
  → preview-changeset      ← NEW (bash: gather the diff)
  → classify-preview       ← NEW (LLM: decide needs_preview)
  → preview-up             ← MODIFIED (gated executor)
  → validate               ← MODIFIED (skips endpoint tests when no preview)
  → conformance            (unchanged)
  → push-and-pr            ← MODIFIED (PR body notes skipped preview)
  → status-in-review       (unchanged)
  → report                 ← MODIFIED (report notes skipped preview)
```

### Design decision: gated executor, not a conditional node

The classifier decision could be wired two ways:

- **Conditional node** — give `preview-up` a `when: ... && needs_preview == true`
  so it is genuinely skipped. But `validate → conformance → push-and-pr` all
  transitively depend on `preview-up`. The current workflow never exercises the
  case of "a node whose dependency was skipped, but whose own `when` is true," so
  Archon's skip-propagation behavior here is unverified — risk of skipping the
  entire tail (no PR).

- **Gated executor (chosen)** — `preview-up` *always runs* and reads the
  classifier's decision. When `needs_preview` is false it writes a skip marker and
  exits 0 without building. **Every existing dependency edge stays intact** — no
  node ever depends on a conditionally-skipped node. Easy to reason about and
  debug.

We choose the gated executor.

## Components

### 1. `preview-changeset` (new, bash)

- `depends_on: [regen-codeindex, fetch-issue]`
- `when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"`
- Emits the curated changeset the classifier will judge:
  - `git diff main...HEAD --name-only` — the changed-file list
  - `git diff main...HEAD --stat` — per-file line counts
- Rationale: feeding the classifier a fixed, pre-computed changeset keeps its input
  deterministic and cheap, rather than letting it roam git on its own.

### 2. `classify-preview` (new, LLM)

- `model: haiku`
- `depends_on: [preview-changeset, fetch-issue]`
- `when: "$parse-intent.output.intent == 'new' || $parse-intent.output.intent == 'continue'"`
- Input: the changeset from `preview-changeset`, plus the issue title and labels
  from `fetch-issue` (secondary signal only).
- `output_format` (structured JSON):

  ```json
  {
    "needs_preview": true,
    "category": "code|docs|config|tests|ci|mixed",
    "reason": "<one sentence>"
  }
  ```

  required: `needs_preview`, `category`, `reason`

#### Classifier rubric

Set `needs_preview = false` **only if every changed file** falls into one of these
non-runtime-affecting categories:

| Category | Matches |
|----------|---------|
| Documentation | `*.md`, `*.mdx`, anything under `docs/` or `Docs/`, `LICENSE` |
| Agent/workflow config | `.archon/**`, `.claude/**`, workflow YAML (not `docker-compose*` or app config) |
| Tests | `backend/tests/**`, `**/*.test.ts(x)`, `**/*.spec.ts(x)`, `conftest.py`, `**/*_test.py`, `dark-factory/tests/**` |
| CI / repo meta | `.github/**`, `.gitignore`, `.pre-commit-config.yaml`, lint/format config (`.eslintrc*`, `.prettierrc*`, ruff/flake8/mypy config), `.editorconfig` |

Force `needs_preview = true` if the diff touches **anything that affects the running
app**, in particular: `backend/app/**`, `alembic/versions/**`, `requirements.txt`,
`frontend/src/**`, `package.json` / `package-lock.json`, `Dockerfile*`,
`docker-compose*`, `.env*`, or preview seed SQL (`dark-factory/seed/**`).

**Fail-safe defaults:** an empty changeset, a mix that is not clearly skip-only, or
any uncertainty → `needs_preview = true`. A wasted preview costs minutes; a wrongly
skipped preview means a code change ships without live endpoint validation. The diff
is authoritative — a `documentation`-labeled issue that nonetheless touches
`backend/app/**` still gets a preview.

If `preview.enabled` is `false` in config, the classifier short-circuits to
`needs_preview = true` (always build).

### 3. `preview-up` (modified — gated executor)

- `depends_on` changes from `[regen-codeindex]` to `[classify-preview]`.
- New guard at the top of the bash body, before slot allocation:

  ```bash
  ISSUE=$(echo $fetch-issue.output | jq -r '.resolved_number')
  NEEDS_PREVIEW=$classify-preview.output.needs_preview
  SKIP_REASON="$classify-preview.output.reason"

  # Skip ONLY on an explicit "false". Any other value (including a garbled or
  # errored classifier output) falls through to building the preview — the
  # fail-safe direction.
  if [ "$NEEDS_PREVIEW" = "false" ]; then
    echo "Preview differentiator: skipping preview for issue #${ISSUE}"
    echo "Reason: ${SKIP_REASON}"
    mkdir -p "$ARTIFACTS_DIR"
    {
      echo "export PREVIEW_SKIPPED=true"
      echo "export PREVIEW_SKIP_REASON=\"${SKIP_REASON}\""
      echo "export PREVIEW_FRONTEND=\"\""
      echo "export PREVIEW_BACKEND=\"\""
      echo "export PREVIEW_NET=\"\""
    } > "$ARTIFACTS_DIR/preview_env.sh"
    echo "PREVIEW_SKIPPED=true"
    echo "PREVIEW_SKIP_REASON=${SKIP_REASON}"
    exit 0
  fi
  ```

- The existing build path is unchanged except that it also writes
  `export PREVIEW_SKIPPED=false` into `preview_env.sh`, so downstream steps can rely
  on the variable always being defined.

### 4. `dark-factory-validate` (modified command)

After sourcing `$ARTIFACTS_DIR/preview_env.sh`, branch on the marker:

- **`PREVIEW_SKIPPED=true`:**
  - Run backend `pytest` and (if frontend changed) `tsc` — these run inside the
    factory container and need no stack.
  - **Skip** the endpoint curl tests and the network-disconnect cleanup (no network
    was connected).
  - Write `validation.md` recording pytest/tsc results plus a line:
    `Endpoint tests skipped — no preview environment (<reason>)`.
- **`PREVIEW_SKIPPED=false` (or unset):** behave exactly as today.

### 5. `push-and-pr` (modified node)

Detect a skipped preview from `$preview-up.output` (`grep '^PREVIEW_SKIPPED=true'`).

- **Skipped:** the PR body `## Preview` section becomes:
  > _No preview environment — this change does not affect the running app
  > (`<reason>`)._
- **Not skipped:** the existing `## Preview` section with frontend/backend URLs.

### 6. `report` (modified node)

Same detection. When skipped, the "Preview Environment" table is replaced with the
same one-line note. The iterate/teardown command block is unchanged (the `Continue`
and `Close` commands remain valid — `Close` on a never-created preview is already a
no-op via `docker compose down -v ... || echo "No preview stack found"`).

### 7. Config — new `preview:` block

In `.claude/skills/refinement/config.yaml`:

```yaml
preview:
  enabled: true   # false = always build the preview (pre-differentiator behavior) — kill-switch
  model: haiku
```

`classify-preview` reads `preview.enabled`; when false it short-circuits to
`needs_preview = true`. This mirrors the existing `conformance.enabled` pattern and
lets the differentiator be disabled without reverting code.

## Data Flow

```
preview-changeset  ──(file list + stat)──►  classify-preview
                                                  │
                                   {needs_preview, category, reason}
                                                  │
                                                  ▼
                                            preview-up
                                       ┌──────────┴───────────┐
                            needs_preview=false        needs_preview=true
                                       │                      │
                       writes PREVIEW_SKIPPED=true      builds stack,
                       to preview_env.sh, exit 0        writes PREVIEW_SKIPPED=false
                                       │                      │
                                       └──────────┬───────────┘
                                                  ▼
                              validate / push-and-pr / report
                              read PREVIEW_SKIPPED and adapt
```

`preview_env.sh` is the single source of truth for downstream steps; `preview-up`'s
stdout (`PREVIEW_SKIPPED=...`) is the source for the two nodes that parse step output
rather than sourcing the file.

## Error Handling

- **Classifier failure / malformed output:** structured `output_format` forces a
  retry on schema mismatch (same mechanism as `parse-intent`). As a second line of
  defense, `preview-up`'s guard (§3) skips **only** on an explicit `false`; any
  other value — including a garbled or errored classifier output — falls through to
  building the preview. This is the fail-safe direction: never skip on uncertainty.
- **Config missing / `preview` block absent:** treat `enabled` as `true`
  (differentiator active). The classifier itself defaults to `needs_preview=true`
  on uncertainty, so an absent config never causes a wrongly-skipped preview.
- **`continue` run that is now docs-only but a preview already exists:** the diff is
  cumulative (`main...HEAD`), so any earlier code change keeps `needs_preview=true`
  and the preview rebuilds as before. A genuinely docs-only branch never had a
  preview to begin with. No teardown logic needed.

## Testing

Add shell regression tests under `dark-factory/tests/` mirroring the existing
`test_*.sh` style:

- `test_preview_differentiator.sh`:
  - Classifier rubric: a docs-only file list → `needs_preview=false`; a list
    touching `backend/app/**` → `needs_preview=true`; a mixed list → `true`; an
    empty list → `true`. (Tested by feeding crafted changesets to the classifier
    prompt logic, or by asserting the guard's branch on a mocked decision.)
  - `preview-up` guard: given `needs_preview=false`, asserts `preview_env.sh`
    contains `PREVIEW_SKIPPED=true` and that no `docker compose up` is invoked;
    given `false`-only-skips, a garbled value still builds.
  - `validate` skip path: with `PREVIEW_SKIPPED=true`, asserts pytest/tsc still run
    and endpoint curl tests are skipped.
- Verify `push-and-pr` and `report` render the "No preview environment" note when
  the marker is set.

Manual end-to-end check: run the factory against a docs-only issue (e.g. a fresh
test issue touching only `*.md`) and confirm no preview stack is created, the PR is
still opened, and the report explains the skip.

## Files to Change

| File | Change |
|------|--------|
| `.archon/workflows/archon-dark-factory.yaml` | Add `preview-changeset` + `classify-preview` nodes; modify `preview-up` (gated executor), `push-and-pr`, `report` |
| `.archon/commands/dark-factory-validate.md` | Branch on `PREVIEW_SKIPPED`; skip endpoint tests + network cleanup when skipped |
| `.claude/skills/refinement/config.yaml` | Add `preview:` block (`enabled`, `model`) |
| `dark-factory/tests/test_preview_differentiator.sh` | New regression test |
| `CLAUDE.md` / dark-factory design spec | Document the differentiator step |
