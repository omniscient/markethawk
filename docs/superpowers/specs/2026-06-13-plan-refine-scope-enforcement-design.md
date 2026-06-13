# Plan/Refine Scope Enforcement — Design (issue #390)

**Date**: 2026-06-13
**Issue**: [#390](https://github.com/omniscient/markethawk/issues/390) — Plan stage implemented the full feature on the refine branch (#339) instead of stopping at the plan
**Component**: `dark-factory/` — `.archon/commands/dark-factory-plan.md`, `.archon/commands/dark-factory-refine.md`

## Problem

During the #339 plan run, the plan-stage agent went beyond its sanctioned scope and implemented the full feature (6 commits + 29-assertion test file) on the refinement branch. The pipeline has no path that consumes implementation code from a `refine/` branch, so the work was orphaned, unvalidated, and ultimately discarded — wasting tokens while making the ticket appear stuck.

Root cause: neither the plan command nor the refine command enforces a scope boundary. There is no prompt-level prohibition and no mechanical check to detect or revert out-of-scope file modifications before publishing.

## Requirements

1. The plan stage's only authorized file outputs are documents under `docs/superpowers/plans/`. Any other modified or created file is out of scope.
2. The refine stage's only authorized file outputs are documents under `docs/superpowers/specs/` and entries under `.archon/memory/`. Any other modified or created file is out of scope.
3. When out-of-scope files are detected, the run must revert them and continue publishing (not fail hard), matching the existing pipeline's excise-and-continue philosophy.
4. Reverted OOS files must be recorded to `$ARTIFACTS_DIR/out-of-scope.md` for downstream scope-spillover ticket creation (matching the conformance gate pattern).
5. The published issue comment must note any OOS excision that occurred.
6. Protection applies equally to both command files — the refine stage has the same failure mode as the plan stage.

## Approach

**Defense-in-depth: prompt prohibition + mechanical gate**

Two independently effective layers:

### Layer 1 — Prompt-level scope boundary

Add a `## SCOPE BOUNDARY` notice at the very top of each command file (before Phase 1: LOAD). This makes the restriction the first thing the agent reads, not something buried mid-document.

**For `dark-factory-plan.md`:**
```
## SCOPE BOUNDARY

This command's only authorized file outputs are:
- Documents under `docs/superpowers/plans/` (the plan file)

Do NOT create or modify any other files. Do NOT implement code, write tests, or edit configuration.
Implementation belongs to the `Fix issue #N` workflow on a `feat/issue-N-*` branch.
```

**For `dark-factory-refine.md`:**
```
## SCOPE BOUNDARY

This command's only authorized file outputs are:
- Documents under `docs/superpowers/specs/` (the spec file)
- Entries under `.archon/memory/` (optional architecture memory)

Do NOT create or modify any other files. Do NOT implement code, write tests, or edit configuration.
```

### Layer 2 — Mechanical OOS gate (pre-commit step)

In each command's publish phase, immediately before the "Commit the plan/spec" step, insert a shell gate:

```bash
# OOS gate — detect and revert any files outside the allowlist
ALLOWED_PREFIXES="docs/superpowers/plans/"       # plan; use "docs/superpowers/specs/ .archon/memory/" for refine

OOS_FILES=$(git diff --name-only origin/main HEAD 2>/dev/null | while read -r f; do
  ALLOWED=false
  for prefix in $ALLOWED_PREFIXES; do
    case "$f" in "$prefix"*) ALLOWED=true; break;; esac
  done
  $ALLOWED || echo "$f"
done)

if [ -n "$OOS_FILES" ]; then
  echo "OOS gate: excising out-of-scope files: $OOS_FILES"
  for f in $OOS_FILES; do
    if git show origin/main:"$f" > /dev/null 2>&1; then
      git checkout origin/main -- "$f"        # file exists on main: restore
    else
      git rm -f --cached "$f" 2>/dev/null; rm -f "$f"  # new file: remove
    fi
  done
  git commit -m "chore: excise out-of-scope files from plan/refine run" --allow-empty
  # Write to artifacts for scope-spillover ticket creation
  mkdir -p "$ARTIFACTS_DIR"
  echo "$OOS_FILES" | while read -r f; do
    echo "- $f: removed by plan/refine OOS gate (should not have been created/modified)" >> "$ARTIFACTS_DIR/out-of-scope.md"
  done
fi
```

Key choices:
- **Two-dot diff** (`git diff --name-only origin/main HEAD`) per codebase memory to avoid false positives from files main merged independently after the branch diverged.
- **Revert-and-continue**, not fail-hard — matches `conformance.excise_out_of_scope: true` behavior in the conformance gate.
- `$ARTIFACTS_DIR/out-of-scope.md` uses the established artifact convention so the scheduler's scope-spillover mechanism can file backlog tickets automatically.

The published issue comment should include a brief note if OOS files were excised:
```
> ⚠️ **OOS excision**: The following files were created outside the plan/spec scope and were reverted before publishing: `<list>`. Scope-spillover tickets may be filed automatically.
```

## Alternatives Considered

### A — Prompt-only (no mechanical gate)

Add the scope boundary notice to the command prompt but skip the `git diff` gate.

**Rejected**: This is exactly the failure mode that #339 demonstrated — the agent ignored (or was not bounded by) its implicit scope. Prompt language alone cannot guarantee scope compliance. The issue itself notes "Cheap mechanical check > prompt-only" as the key insight.

### B — Mechanical gate only (no prompt notice)

Add the gate without the scope prohibition text at the top.

**Rejected**: The gate catches OOS at commit time but doesn't reduce the probability of the agent attempting implementation in the first place (wasting tokens). The prompt notice is cheap to add and gives the model the correct frame before it begins generating.

### C — Gate in `entrypoint.sh` (shared location)

The product-owner research found that `entrypoint.sh` is not the right chokepoint: refine and plan commits happen inside the Claude command via the agent's own git calls, not via an entrypoint-controlled publish step. A gate in `entrypoint.sh` would fire after the branch is already pushed and would have no way to revert individual commits within the push.

## Open Questions (non-blocking)

- Should a high-volume OOS event (e.g. >10 files excised) escalate differently — e.g. add `needs-discussion` instead of just continuing? Deferred; the current pattern matches conformance gate behavior and can be tuned post-hoc.
- Should the scope boundary also include `docs/superpowers/specs/` as a readable (but not writable) allowlist in the plan stage? Not needed — the plan stage reads the spec in Phase 1 but does not commit it.

## Assumptions

- `$ARTIFACTS_DIR` is set by the factory container's `entrypoint.sh` before invoking the command. (True per existing pattern.)
- `origin/main` is fetchable from inside the factory container. (True per existing pipeline — the branch always branches from main.)
- The two-dot diff convention (`git diff --name-only origin/main HEAD`) is the correct form per `.archon/memory/codebase-patterns.md`.
