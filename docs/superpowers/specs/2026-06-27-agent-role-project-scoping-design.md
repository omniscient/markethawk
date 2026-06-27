# Agent Role and Project Scoping for Dark Factory Memory Calls

**Status:** design
**Date:** 2026-06-27
**Issue:** #651
**Epic:** #643 (Improve Dark Factory memory system using agent-native memory architecture)
**Size:** S

## Problem

The Dark Factory memory system (`/.archon/memory/*.md`) stores accumulated lessons as
markdown entries with inline metadata tags (`issue:`, `date:`, `expires:`, `source:`,
`path:`). As the factory prepares for a multi-agent deployment with distinct role identities
(13 named roles), two isolation properties are missing today:

1. **Project scoping.** Every entry implicitly belongs to `markethawk`, but the tag is
   absent. A future multi-project Hermes deployment reading these files has no way to filter
   by project without modifying the files.

2. **Agent role provenance.** The `source:` tag records the *phase* (`refine`, `implement`,
   `conformance`), not the *role identity* of the agent that wrote the entry. Cross-role
   contamination (e.g. a validation agent accidentally ingesting implementation reasoning)
   cannot be detected or prevented without knowing which role produced each entry.

## Requirements

- **R1.** Every memory entry written after this change includes `project:markethawk` in its
  inline comment.
- **R2.** Every memory entry written after this change includes `agentId:<role>` drawn from
  the stable 13-value role vocabulary.
- **R3.** `load_memory()` excludes entries where a `project:` tag is present but the value
  is not `markethawk`. Entries without any `project:` tag pass through (backward
  compatibility with legacy entries).
- **R4.** The 13 role IDs are defined once as shell constants in a sourced include file;
  every phase command sets its default `AGENT_ID` from that file.
- **R5.** Tests cover: (a) project-tag filtering in `load_memory()`; (b) presence of
  `project:` and `agentId:` in entries written by `write_memory_entry()`.
- **Non-goal.** No `agentId:` runtime filtering in `load_memory()` — deferred to a
  follow-up size:M ticket (see Open Questions).
- **Non-goal.** No backfilling of the ~134 existing memory entries. Legacy entries remain
  valid and load unfiltered.
- **Non-goal.** No Python files, structured backend, or new Docker services. (#643 handles
  those in later phases.)

## Architecture

### 1. New file: `dark-factory/scripts/agent_roles.sh`

A sourced-only shell include (no `set -euo pipefail`; must not alter caller shell options)
defining the 13 stable role-ID constants and a project constant:

```sh
#!/usr/bin/env bash
# Agent role-ID constants for Dark Factory memory scoping.
# Sourced by gate_lib.sh and by each phase command that writes or reads memory.
# Do NOT add set -euo pipefail — this file is sourced and must not alter caller shell options.

MEMORY_PROJECT="markethawk"

AGENT_ID_FACTORY_DIRECTOR="factory-director"
AGENT_ID_INTAKE_TRIAGE="intake-triage-agent"
AGENT_ID_REFINEMENT="refinement-agent"
AGENT_ID_PLANNING="planning-agent"
AGENT_ID_IMPLEMENTATION="implementation-agent"
AGENT_ID_VALIDATION="validation-agent"
AGENT_ID_CODE_REVIEW="code-review-agent"
AGENT_ID_SECURITY="security-agent"
AGENT_ID_DECONFLICT="deconflict-agent"
AGENT_ID_CI_RESCUE="ci-rescue-agent"
AGENT_ID_MERGE_GATE="merge-gate-agent"
AGENT_ID_COST_TELEMETRY="cost-telemetry-agent"
AGENT_ID_HUMAN_LIAISON="human-liaison-agent"
```

### 2. Update `dark-factory/scripts/gate_lib.sh`

- Source `agent_roles.sh` at the top (before the function definitions):
  ```sh
  GATE_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  # shellcheck source=dark-factory/scripts/agent_roles.sh
  source "${GATE_LIB_DIR}/agent_roles.sh"
  ```

- Extend `write_memory_entry()` with an optional 6th parameter `AGENT_ID`:
  ```sh
  write_memory_entry() {
    # Usage: write_memory_entry TARGET PATH_PREFIX VIOLATION_TEXT SOURCE ISSUE_NUM [AGENT_ID]
    local TARGET="$1" PATH_PREFIX="$2" TEXT="$3" SOURCE="$4" ISSUE="$5"
    local ROLE="${6:-${AGENT_ID:-unknown}}"
    ...
    ENTRY="- [AVOID] $TEXT <!-- project:${MEMORY_PROJECT} agentId:${ROLE} issue:#$ISSUE date:$(date +%Y-%m-%d) expires:$EXPIRES source:$SOURCE path:$PATH_PREFIX -->"
  ```

  The 6th parameter is optional; if omitted, the function falls back to the `AGENT_ID`
  environment variable (set by the calling command), then to the literal string `"unknown"`.

### 3. Update `load_memory()` in all three reader commands

`dark-factory-refine.md`, `dark-factory-plan.md`, and `dark-factory-implement.md` each
define `load_memory()` inline at Phase 1 LOAD. Add a `project:` guard before the existing
`path:` guard:

```sh
load_memory() {
  local MEMFILE=".archon/memory/$1"
  [ -f "$MEMFILE" ] || return
  while IFS= read -r line; do
    # Project filter: skip entries tagged for a different project.
    # Entries without any project: tag are always included (legacy backward compat).
    if echo "$line" | grep -q 'project:'; then
      if ! echo "$line" | grep -q "project:${MEMORY_PROJECT}"; then
        continue
      fi
    fi
    # Path filter: existing behavior unchanged.
    if echo "$line" | grep -q 'path:'; then
      PATH_TAG=$(echo "$line" | sed 's/.*path:\([^ >]*\).*/\1/')
      if [ -z "$AFFECTED" ] || echo "$AFFECTED" | grep -q "^${PATH_TAG}"; then
        echo "$line"
      fi
    else
      echo "$line"
    fi
  done < "$MEMFILE"
}
```

Each reader command also sets its default `AGENT_ID` in its Phase 1 LOAD block (after
sourcing `agent_roles.sh` or `gate_lib.sh`):

| Command | Default AGENT_ID |
|---|---|
| `dark-factory-refine.md` | `$AGENT_ID_REFINEMENT` |
| `dark-factory-plan.md` | `$AGENT_ID_PLANNING` |
| `dark-factory-implement.md` | `$AGENT_ID_IMPLEMENTATION` |
| `dark-factory-conformance.md` | `$AGENT_ID_DECONFLICT` (writes memory only; no reads) |
| `dark-factory-code-review.md` | `$AGENT_ID_CODE_REVIEW` (writes memory only; no reads) |

### 4. Update refine command Phase 5 shell-appended entries

`dark-factory-refine.md` Phase 5 Step 7 uses shell appends (`echo '...' >> .archon/memory/`)
rather than `write_memory_entry()`. The inline comment format in those append instructions
must include `project:markethawk agentId:refinement-agent` alongside the existing tags.

### 5. Convention for validation/security roles (doc-only in this ticket)

`dark-factory-validate.md` and `dark-factory-conformance.md` currently do **not** read
memory. To prevent future accidental contamination:

> **Convention:** Validation, security, and gate agents MUST NOT call `load_memory()` for
> `agentId:implementation-agent` or `agentId:planning-agent` entries unless the caller
> explicitly declares the need. When a validation/security agent begins reading memory, a
> follow-up ticket (see Open Questions) must add an `allow_agent_ids=` parameter to
> `load_memory()` that filters by `agentId:` at load time.

This convention is documented here and in `docs/agents/domain.md`.

## Alternatives Considered

### A. Add role constants directly to `gate_lib.sh`

Rejected. `gate_lib.sh`'s header comment states it contains "only the three shared
primitives." A 13-constant vocabulary block would violate its stated contract and force
non-gate commands that only need role constants to pull in the gate writer functions.
`agent_roles.sh` as a sibling file is cheaper (one `source` line) and respects the
existing separation of concerns.

### B. Add `agentId:` runtime filtering to `load_memory()` now

Rejected for this size:S ticket. `dark-factory-validate.md` and `dark-factory-conformance.md`
do not read memory today, so there is no active leak to plug. Implementing an
`allow_agent_ids=` filter mechanism now would add control-flow complexity (and test
coverage) to guard a code path that no validation/security role currently exercises — that
pushes the ticket out of size:S. Deferred to a follow-up size:M ticket.

### C. Backfill existing entries

Rejected. The ~134 existing entries will load correctly under the new `load_memory()` because
the project filter only excludes entries where `project:` is *present but wrong*. A missing
`project:` tag means "always include" — the safe default. Backfilling would require choosing
a synthetic `agentId` for entries whose true origin is unknown (bootstrap entries predate
the role vocabulary), bloat the PR, and add risk with no functional payoff.

## Open Questions (non-blocking)

1. **Follow-up size:M ticket:** Implement `allow_agent_ids=` runtime filtering in
   `load_memory()` once a validation/security agent is wired to read memory. That ticket
   should also decide whether untagged legacy entries default to "allow all" or require a
   one-time backfill.

2. **`source:` vs `agentId:` in entry parsing:** The parent epic #643 Phase 2 (retrieval
   adapter) will consume both `source:` and `agentId:` tags. This spec does not prescribe
   which field takes precedence — that decision belongs in the #643 spec for the retrieval
   adapter.

3. **`MEMORY_PROJECT` sourcing in `load_memory()`:** The `load_memory()` function is
   defined inline in command files (not in `gate_lib.sh`), so it does not automatically
   have access to `MEMORY_PROJECT` from `agent_roles.sh`. Each command must either source
   `agent_roles.sh` before defining `load_memory()` or hardcode `project:markethawk` in
   the filter. The implementation plan should pick one approach consistently. Recommendation:
   each reader command's Phase 1 LOAD block should source `agent_roles.sh` before defining
   `load_memory()`.

## Assumptions

- **[A1]** All memory entries written by this codebase belong to `project:markethawk`. The
  project value is hardcoded, not configuration-driven.
- **[A2]** The 13 role IDs in `agent_roles.sh` are stable. Additions require a code change
  to `agent_roles.sh`; there is no dynamic registration.
- **[A3]** `BASH_SOURCE[0]` is reliable for locating `gate_lib.sh`'s directory when `gate_lib.sh`
  is sourced by the command files; this pattern already works in the existing test suite
  (`test_conformance_memory_write.sh` line 5).
- **[A4]** The `conformance` gate maps to `agentId:deconflict-agent` as its default. If a
  future ticket splits conformance into separate code-review and security sub-roles, the
  default can be overridden via the 6th parameter to `write_memory_entry()`.
